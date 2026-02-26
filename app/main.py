import asyncio
import hashlib
import json
import random
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    Auction,
    AuctionStatus,
    ChannelMembership,
    ChannelReward,
    ChannelRole,
    Contribution,
    Position,
    RewardPreset,
    RouletteRun,
    RouletteStatus,
    Suggestion,
    SuggestionRateLimit,
    SuggestionStatus,
    User,
    AuditLog,
    Wallet,
)
from .services import (
    apply_transition,
    calculate_contribution_amount,
    can_transition_auction,
    is_large_contribution,
    leader_changed,
    should_reset_rate_limit_window,
    build_effect_flags,
    build_stream_embed_url,
    clamp_limit,
    seconds_to_end,
)
from .schemas import (
    AuctionCreate,
    AuctionDetail,
    AuctionRead,
    ChannelRewardRead,
    ContributionCreate,
    ContributionRead,
    ContributionSpinCreate,
    HistoryAuctionDetail,
    HistoryAuctionRead,
    MembershipAssign,
    MembershipRead,
    PositionCreate,
    PositionRead,
    RewardPresetRead,
    RewardPresetWrite,
    RouletteFinishRequest,
    RouletteRunRead,
    SuggestionCreate,
    AuditLogRead,
    AuctionCloneRequest,
    AuctionRestartRequest,
    AuctionUiContextRead,
    ActivityEventRead,
    AuctionEffectsRead,
    SuggestionRead,
    UserCreate,
    UserRead,
    WalletRead,
    WalletTopUp,
    ErrorResponse,
    EmailAuthLogin,
    EmailAuthRegister,
    AuthTokenRead,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Twitch Auction API", version="0.4.0")
DEFAULT_REWARD_AMOUNTS = [5000, 10000, 50000, 100000]
SUGGESTION_LIMIT_PER_HOUR = 3
LARGE_CONTRIBUTION_THRESHOLD = 1000
EFFECTS_LOOKBACK_SECONDS = 120
AUTH_TOKEN_STORE: dict[str, str] = {}


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    payload = ErrorResponse(
        code=f"http_{exc.status_code}",
        message=str(exc.detail),
        details=None,
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    payload = ErrorResponse(
        code="validation_error",
        message="Request validation failed",
        details=exc.errors(),
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=AuthTokenRead, status_code=status.HTTP_201_CREATED)
def register_with_email(payload: EmailAuthRegister, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email is already registered")

    login = _normalize_login(payload.login) if payload.login else _generate_login_from_email(email)
    if db.query(User).filter(User.login == login).first():
        raise HTTPException(status_code=400, detail="Login is already taken")

    user = User(
        login=login,
        email=email,
        password_hash=_hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    db.commit()

    token = _create_access_token(login)
    return AuthTokenRead(access_token=token, user_login=login)


@app.post("/auth/login", response_model=AuthTokenRead)
def login_with_email(payload: EmailAuthLogin, db: Session = Depends(get_db)):
    email = _normalize_email(payload.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.password_hash != _hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = _create_access_token(user.login)
    return AuthTokenRead(access_token=token, user_login=user.login)


def _normalize_login(value: str) -> str:
    return value.strip().lower()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _generate_login_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    return _normalize_login(local.replace(".", "_").replace("-", "_"))


def _create_access_token(login: str) -> str:
    token = secrets.token_urlsafe(24)
    AUTH_TOKEN_STORE[token] = _normalize_login(login)
    return token


def _resolve_login_from_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "bearer "
    value = authorization.strip()
    if value.lower().startswith(prefix):
        token = value[len(prefix):].strip()
        return AUTH_TOKEN_STORE.get(token)
    return None


def get_current_user_login(
    x_user_login: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str | None:
    if x_user_login:
        return _normalize_login(x_user_login)
    return _resolve_login_from_token(authorization)


def _require_role(db: Session, channel_login: str, user_login: str | None, allowed_roles: set[ChannelRole]) -> None:
    if not user_login:
        raise HTTPException(status_code=401, detail="Missing authentication: X-User-Login or Authorization Bearer token")

    user = db.query(User).filter(User.login == _normalize_login(user_login)).first()
    if not user:
        raise HTTPException(status_code=403, detail="User is not registered")

    membership = (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_login == _normalize_login(channel_login),
            ChannelMembership.user_id == user.id,
            ChannelMembership.role.in_(list(allowed_roles)),
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Insufficient role for this channel")


def _audit_action(db: Session, auction_id: int, actor_login: str | None, action: str, details: str) -> None:
    db.add(
        AuditLog(
            auction_id=auction_id,
            actor_login=_normalize_login(actor_login or "system"),
            action=action,
            details=details,
        )
    )


def _get_auction_or_404(db: Session, auction_id: int) -> Auction:
    auction = db.query(Auction).filter(Auction.id == auction_id).first()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    return auction






def _build_realtime_payload(db: Session, auction: Auction) -> dict:
    positions = (
        db.query(Position)
        .filter(Position.auction_id == auction.id)
        .order_by(Position.points.desc(), Position.id.asc())
        .limit(10)
        .all()
    )
    activity_rows = (
        db.query(AuditLog)
        .filter(AuditLog.auction_id == auction.id)
        .order_by(AuditLog.id.desc())
        .limit(10)
        .all()
    )
    ttl_seconds = seconds_to_end(auction.ends_at)
    effects = build_effect_flags({row.action for row in activity_rows}, ttl_seconds)

    return {
        "auction_id": auction.id,
        "status": auction.status.value,
        "seconds_to_end": ttl_seconds,
        "positions": [
            {"id": p.id, "title": p.title, "points": p.points}
            for p in positions
        ],
        "activity": [
            {
                "type": row.action,
                "actor": row.actor_login,
                "message": row.details,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in activity_rows
        ],
        "effects": effects,
    }

def _get_wallet_or_404(db: Session, auction_id: int, viewer: str) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.auction_id == auction_id, Wallet.viewer == viewer).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


@app.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_or_update_user(payload: UserCreate, db: Session = Depends(get_db)):
    login = _normalize_login(payload.login)
    user = db.query(User).filter(User.login == login).first()
    if not user:
        user = User(login=login, display_name=payload.display_name)
        db.add(user)
    else:
        user.display_name = payload.display_name
    db.commit()
    db.refresh(user)
    return user


@app.post("/memberships", response_model=MembershipRead, status_code=status.HTTP_201_CREATED)
def assign_membership(payload: MembershipAssign, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.login == _normalize_login(payload.user_login)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    membership = (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_login == _normalize_login(payload.channel_login),
            ChannelMembership.user_id == user.id,
            ChannelMembership.role == payload.role,
        )
        .first()
    )
    if membership:
        return membership

    membership = ChannelMembership(
        channel_login=_normalize_login(payload.channel_login),
        user_id=user.id,
        role=payload.role,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


@app.put("/channels/{channel_login}/reward-presets", response_model=list[RewardPresetRead])
def set_reward_presets(
    channel_login: str,
    payload: RewardPresetWrite,
    db: Session = Depends(get_db),
    x_user_login: str | None = Depends(get_current_user_login),
):
    _require_role(db, channel_login, x_user_login, {ChannelRole.streamer})
    normalized_channel = _normalize_login(channel_login)

    db.query(RewardPreset).filter(RewardPreset.channel_login == normalized_channel).delete()
    target_amounts = sorted({amount for amount in payload.amounts if amount > 0}) or DEFAULT_REWARD_AMOUNTS

    for amount in target_amounts:
        db.add(RewardPreset(channel_login=normalized_channel, amount=amount, is_enabled=True))

    db.commit()
    return (
        db.query(RewardPreset)
        .filter(RewardPreset.channel_login == normalized_channel)
        .order_by(RewardPreset.amount.asc())
        .all()
    )


@app.get("/channels/{channel_login}/reward-presets", response_model=list[RewardPresetRead])
def get_reward_presets(channel_login: str, db: Session = Depends(get_db)):
    normalized_channel = _normalize_login(channel_login)
    presets = (
        db.query(RewardPreset)
        .filter(RewardPreset.channel_login == normalized_channel, RewardPreset.is_enabled.is_(True))
        .order_by(RewardPreset.amount.asc())
        .all()
    )
    if presets:
        return presets

    return [RewardPreset(channel_login=normalized_channel, amount=amount, is_enabled=True) for amount in DEFAULT_REWARD_AMOUNTS]


@app.post("/auctions", response_model=AuctionRead, status_code=status.HTTP_201_CREATED)
def create_auction(payload: AuctionCreate, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    _require_role(db, payload.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    auction = Auction(
        title=payload.title,
        channel_login=_normalize_login(payload.channel_login),
        duration_minutes=payload.duration_minutes,
    )
    db.add(auction)
    db.commit()
    db.refresh(auction)
    return auction


def _clone_auction_into_new(
    db: Session,
    source: Auction,
    title: str | None,
    carry_scores: bool,
    reset_position_titles: list[str],
) -> Auction:
    target = Auction(
        title=title or f"{source.title} (clone)",
        channel_login=source.channel_login,
        source_auction_id=source.id,
        duration_minutes=source.duration_minutes,
    )
    db.add(target)
    db.flush()

    source_positions = (
        db.query(Position)
        .filter(Position.auction_id == source.id)
        .order_by(Position.id.asc())
        .all()
    )
    reset_titles = {value.strip().lower() for value in reset_position_titles}

    for source_position in source_positions:
        points = source_position.points if carry_scores else 0
        if source_position.title.strip().lower() in reset_titles:
            points = 0
        db.add(Position(auction_id=target.id, title=source_position.title, points=points))

    return target


@app.post("/auctions/{auction_id}/clone", response_model=AuctionRead, status_code=status.HTTP_201_CREATED)
def clone_auction(
    auction_id: int,
    payload: AuctionCloneRequest,
    db: Session = Depends(get_db),
    x_user_login: str | None = Depends(get_current_user_login),
):
    source = _get_auction_or_404(db, auction_id)
    _require_role(db, source.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})

    target = _clone_auction_into_new(
        db=db,
        source=source,
        title=payload.title,
        carry_scores=payload.carry_scores,
        reset_position_titles=payload.reset_position_titles,
    )

    _audit_action(
        db,
        source.id,
        x_user_login,
        "auction.clone",
        f"Cloned to auction={target.id}, carry_scores={payload.carry_scores}",
    )
    db.commit()
    db.refresh(target)
    return target




@app.post("/auctions/{auction_id}/restart", response_model=AuctionRead, status_code=status.HTTP_201_CREATED)
def restart_auction_from_history(
    auction_id: int,
    payload: AuctionRestartRequest,
    db: Session = Depends(get_db),
    x_user_login: str | None = Depends(get_current_user_login),
):
    source = _get_auction_or_404(db, auction_id)
    _require_role(db, source.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    if source.status != AuctionStatus.closed:
        raise HTTPException(status_code=409, detail="Only closed auction can be restarted")

    target = _clone_auction_into_new(
        db=db,
        source=source,
        title=payload.title or f"{source.title} (restart)",
        carry_scores=payload.carry_scores,
        reset_position_titles=payload.reset_position_titles,
    )

    if payload.auto_start:
        apply_transition(target, AuctionStatus.active)

    _audit_action(
        db,
        source.id,
        x_user_login,
        "auction.restart",
        f"Restarted to auction={target.id}, auto_start={payload.auto_start}",
    )
    db.commit()
    db.refresh(target)
    return target


@app.get("/auctions", response_model=list[AuctionRead])
def list_auctions(
    channel_login: str | None = None,
    status_filter: AuctionStatus | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Auction)
    if channel_login:
        query = query.filter(Auction.channel_login == _normalize_login(channel_login))
    if status_filter:
        query = query.filter(Auction.status == status_filter)
    return query.order_by(Auction.id.desc()).limit(clamp_limit(limit)).all()


@app.get("/auctions/{auction_id}", response_model=AuctionDetail)
def get_auction(auction_id: int, db: Session = Depends(get_db)):
    return _get_auction_or_404(db, auction_id)


@app.post("/auctions/{auction_id}/start", response_model=AuctionRead)
def start_auction(auction_id: int, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    auction = _get_auction_or_404(db, auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer})

    if auction.status in {AuctionStatus.closed, AuctionStatus.roulette_running}:
        raise HTTPException(status_code=409, detail="Cannot start this auction in current state")

    presets = (
        db.query(RewardPreset)
        .filter(RewardPreset.channel_login == auction.channel_login, RewardPreset.is_enabled.is_(True))
        .order_by(RewardPreset.amount.asc())
        .all()
    )
    amounts = [preset.amount for preset in presets] or DEFAULT_REWARD_AMOUNTS

    if not auction.rewards:
        for amount in amounts:
            db.add(ChannelReward(auction_id=auction.id, channel_login=auction.channel_login, title=f"Пополнить баланс на {amount}", amount=amount))

    apply_transition(auction, AuctionStatus.active)
    db.commit()
    db.refresh(auction)
    return auction


@app.post("/auctions/{auction_id}/lock", response_model=AuctionRead)
def lock_auction(auction_id: int, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    auction = _get_auction_or_404(db, auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    if not can_transition_auction(auction.status, AuctionStatus.locked):
        raise HTTPException(status_code=409, detail="Only active auction can be locked")
    apply_transition(auction, AuctionStatus.locked)
    _audit_action(db, auction.id, x_user_login, "auction.lock", "Auction was locked for finalization")
    db.commit()
    db.refresh(auction)
    return auction


@app.post("/auctions/{auction_id}/roulette/start", response_model=RouletteRunRead, status_code=status.HTTP_201_CREATED)
def start_roulette(auction_id: int, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    auction = _get_auction_or_404(db, auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer})
    if not can_transition_auction(auction.status, AuctionStatus.roulette_running):
        raise HTTPException(status_code=409, detail="Auction must be locked before roulette")

    running = db.query(RouletteRun).filter(RouletteRun.auction_id == auction_id, RouletteRun.status == RouletteStatus.running).first()
    if running:
        return running

    run = RouletteRun(auction_id=auction_id, status=RouletteStatus.running)
    apply_transition(auction, AuctionStatus.roulette_running)
    db.add(run)
    _audit_action(db, auction.id, x_user_login, "roulette.start", f"Roulette run {run.id} started")
    db.commit()
    db.refresh(run)
    return run


@app.post("/auctions/{auction_id}/roulette/finish", response_model=RouletteRunRead)
def finish_roulette(
    auction_id: int,
    payload: RouletteFinishRequest,
    db: Session = Depends(get_db),
    x_user_login: str | None = Depends(get_current_user_login),
):
    auction = _get_auction_or_404(db, auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer})
    if auction.status != AuctionStatus.roulette_running:
        raise HTTPException(status_code=409, detail="Roulette is not running")

    position = db.query(Position).filter(Position.id == payload.winner_position_id, Position.auction_id == auction_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Winner position not found in auction")

    run = db.query(RouletteRun).filter(RouletteRun.auction_id == auction_id, RouletteRun.status == RouletteStatus.running).first()
    if not run:
        raise HTTPException(status_code=404, detail="Running roulette not found")

    run.status = RouletteStatus.finished
    run.winner_position_id = position.id
    run.finished_at = datetime.now(timezone.utc)
    auction.winner_position_id = position.id
    apply_transition(auction, AuctionStatus.closed)
    _audit_action(db, auction.id, x_user_login, "roulette.finish", f"Winner position={position.id}")
    db.commit()
    db.refresh(run)
    return run


@app.get("/auctions/{auction_id}/rewards", response_model=list[ChannelRewardRead])
def list_created_rewards(auction_id: int, db: Session = Depends(get_db)):
    _get_auction_or_404(db, auction_id)
    return db.query(ChannelReward).filter(ChannelReward.auction_id == auction_id).order_by(ChannelReward.amount).all()


@app.post("/auctions/{auction_id}/close", response_model=AuctionRead)
def close_auction(auction_id: int, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    auction = _get_auction_or_404(db, auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    if auction.status == AuctionStatus.roulette_running:
        raise HTTPException(status_code=409, detail="Finish roulette before closing auction")
    if not can_transition_auction(auction.status, AuctionStatus.closed):
        raise HTTPException(status_code=409, detail="Auction cannot be closed from current state")
    apply_transition(auction, AuctionStatus.closed)
    _audit_action(db, auction.id, x_user_login, "auction.close", "Auction closed directly")
    db.commit()
    db.refresh(auction)
    return auction


@app.get("/history/auctions", response_model=list[HistoryAuctionRead])
def list_closed_auctions_history(
    channel_login: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(Auction).filter(Auction.status == AuctionStatus.closed)
    if channel_login:
        query = query.filter(Auction.channel_login == _normalize_login(channel_login))
    closed_auctions = query.order_by(Auction.id.desc()).limit(clamp_limit(limit)).all()
    history: list[HistoryAuctionRead] = []
    for auction in closed_auctions:
        positions = db.query(Position).filter(Position.auction_id == auction.id).order_by(Position.points.desc(), Position.id.asc()).all()
        total_points = sum(position.points for position in positions)
        winner_title = next((p.title for p in positions if p.id == auction.winner_position_id), None)
        if not winner_title:
            winner_title = positions[0].title if positions and positions[0].points > 0 else None
        history.append(
            HistoryAuctionRead(
                auction_id=auction.id,
                title=auction.title,
                channel_login=auction.channel_login,
                closed_at=auction.created_at,
                total_points=total_points,
                winner_title=winner_title,
            )
        )
    return history


@app.get("/history/auctions/{auction_id}", response_model=HistoryAuctionDetail)
def get_closed_auction_history(auction_id: int, db: Session = Depends(get_db)):
    auction = _get_auction_or_404(db, auction_id)
    if auction.status != AuctionStatus.closed:
        raise HTTPException(status_code=409, detail="Auction is not closed")

    positions = db.query(Position).filter(Position.auction_id == auction.id).order_by(Position.points.desc(), Position.id.asc()).all()
    total_points = sum(position.points for position in positions)
    winner_title = next((p.title for p in positions if p.id == auction.winner_position_id), None)
    if not winner_title:
        winner_title = positions[0].title if positions and positions[0].points > 0 else None

    return HistoryAuctionDetail(
        auction_id=auction.id,
        title=auction.title,
        channel_login=auction.channel_login,
        closed_at=auction.created_at,
        total_points=total_points,
        winner_title=winner_title,
        positions=positions,
    )






@app.get("/auctions/{auction_id}/ui-context", response_model=AuctionUiContextRead)
def get_auction_ui_context(auction_id: int, db: Session = Depends(get_db)):
    auction = _get_auction_or_404(db, auction_id)
    ttl_seconds = seconds_to_end(auction.ends_at)
    is_ending_soon = ttl_seconds is not None and ttl_seconds <= 300

    return AuctionUiContextRead(
        auction_id=auction.id,
        stream_embed_url=build_stream_embed_url(auction.channel_login),
        is_ending_soon=is_ending_soon,
        seconds_to_end=ttl_seconds,
    )




@app.get("/auctions/{auction_id}/effects", response_model=AuctionEffectsRead)
def get_auction_effects(auction_id: int, db: Session = Depends(get_db)):
    auction = _get_auction_or_404(db, auction_id)
    since = datetime.now(timezone.utc) - timedelta(seconds=EFFECTS_LOOKBACK_SECONDS)

    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.auction_id == auction_id, AuditLog.created_at >= since)
        .all()
    )
    actions = {row.action for row in audit_rows}

    ttl_seconds = seconds_to_end(auction.ends_at)
    flags = build_effect_flags(actions, ttl_seconds)
    return AuctionEffectsRead(
        auction_id=auction.id,
        leader_changed=flags["leader_changed"],
        large_contribution=flags["large_contribution"],
        auction_ending_soon=flags["auction_ending_soon"],
        new_vote_or_suggestion=flags["new_vote_or_suggestion"],
    )




@app.get("/auctions/{auction_id}/events")
async def stream_auction_events(auction_id: int, db: Session = Depends(get_db)):
    auction = _get_auction_or_404(db, auction_id)

    async def event_generator():
        previous_signature: str | None = None
        # short-lived stream; frontend reconnects automatically
        for _ in range(30):
            db.expire_all()
            live_auction = _get_auction_or_404(db, auction_id)
            payload = _build_realtime_payload(db, live_auction)
            signature = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if signature != previous_signature:
                yield f"event: snapshot\ndata: {signature}\n\n"
                previous_signature = signature
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/auctions/{auction_id}/activity", response_model=list[ActivityEventRead])
def get_auction_activity(auction_id: int, limit: int = 20, db: Session = Depends(get_db)):
    _get_auction_or_404(db, auction_id)
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.auction_id == auction_id)
        .order_by(AuditLog.id.desc())
        .limit(clamp_limit(limit))
        .all()
    )
    return [
        ActivityEventRead(
            type=row.action,
            actor=row.actor_login,
            created_at=row.created_at,
            message=row.details,
        )
        for row in rows
    ]


@app.get("/audit-log", response_model=list[AuditLogRead])
def list_audit_log(auction_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    if auction_id is not None:
        query = query.filter(AuditLog.auction_id == auction_id)
    return query.all()


@app.post("/auctions/{auction_id}/positions", response_model=PositionRead, status_code=status.HTTP_201_CREATED)
def add_position(
    auction_id: int,
    payload: PositionCreate,
    db: Session = Depends(get_db),
    x_user_login: str | None = Depends(get_current_user_login),
):
    auction = _get_auction_or_404(db, auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    position = Position(auction_id=auction.id, title=payload.title)
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


@app.get("/auctions/{auction_id}/positions", response_model=list[PositionRead])
def list_positions(auction_id: int, db: Session = Depends(get_db)):
    return db.query(Position).filter(Position.auction_id == auction_id).order_by(Position.points.desc(), Position.id.asc()).all()


@app.post("/auctions/{auction_id}/suggestions", response_model=SuggestionRead, status_code=status.HTTP_201_CREATED)
def create_suggestion(auction_id: int, payload: SuggestionCreate, db: Session = Depends(get_db)):
    _get_auction_or_404(db, auction_id)
    now = datetime.now(timezone.utc)
    author = _normalize_login(payload.author)
    limiter = db.query(SuggestionRateLimit).filter(
        SuggestionRateLimit.auction_id == auction_id,
        SuggestionRateLimit.author == author,
    ).first()

    if not limiter:
        limiter = SuggestionRateLimit(auction_id=auction_id, author=author, window_started_at=now, attempts=0)
        db.add(limiter)

    window_start = limiter.window_started_at
    if should_reset_rate_limit_window(window_start, now=now, window_hours=1):
        limiter.window_started_at = now
        limiter.attempts = 0

    if limiter.attempts >= SUGGESTION_LIMIT_PER_HOUR:
        raise HTTPException(status_code=429, detail="Suggestion rate limit exceeded for this auction")

    limiter.attempts += 1
    suggestion = Suggestion(auction_id=auction_id, author=author, title=payload.title)
    db.add(suggestion)
    _audit_action(db, auction_id, author, "suggestion.created", f"Suggestion created: {payload.title}")
    db.commit()
    db.refresh(suggestion)
    return suggestion


@app.get("/auctions/{auction_id}/suggestions", response_model=list[SuggestionRead])
def list_suggestions(auction_id: int, db: Session = Depends(get_db)):
    return db.query(Suggestion).filter(Suggestion.auction_id == auction_id).order_by(Suggestion.id.desc()).all()


@app.post("/suggestions/{suggestion_id}/approve", response_model=SuggestionRead)
def approve_suggestion(suggestion_id: int, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    auction = _get_auction_or_404(db, suggestion.auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    if suggestion.status != SuggestionStatus.pending:
        raise HTTPException(status_code=409, detail="Suggestion already moderated")

    suggestion.status = SuggestionStatus.approved
    db.add(Position(auction_id=suggestion.auction_id, title=suggestion.title))
    _audit_action(db, auction.id, x_user_login, "suggestion.approve", f"Suggestion {suggestion.id} approved")
    db.commit()
    db.refresh(suggestion)
    return suggestion


@app.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionRead)
def reject_suggestion(suggestion_id: int, db: Session = Depends(get_db), x_user_login: str | None = Depends(get_current_user_login)):
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    auction = _get_auction_or_404(db, suggestion.auction_id)
    _require_role(db, auction.channel_login, x_user_login, {ChannelRole.streamer, ChannelRole.moderator})
    if suggestion.status != SuggestionStatus.pending:
        raise HTTPException(status_code=409, detail="Suggestion already moderated")

    suggestion.status = SuggestionStatus.rejected
    _audit_action(db, auction.id, x_user_login, "suggestion.reject", f"Suggestion {suggestion.id} rejected")
    db.commit()
    db.refresh(suggestion)
    return suggestion


@app.post("/auctions/{auction_id}/wallet/topup", response_model=WalletRead)
def wallet_topup(auction_id: int, payload: WalletTopUp, db: Session = Depends(get_db)):
    _get_auction_or_404(db, auction_id)
    wallet = db.query(Wallet).filter(Wallet.auction_id == auction_id, Wallet.viewer == payload.viewer).first()
    if not wallet:
        wallet = Wallet(auction_id=auction_id, viewer=payload.viewer)
        db.add(wallet)

    wallet.balance_total += payload.amount
    wallet.balance_available += payload.amount
    _audit_action(db, auction_id, payload.viewer, "wallet.topup", f"Top up +{payload.amount}")
    db.commit()
    db.refresh(wallet)
    return wallet


@app.get("/auctions/{auction_id}/wallet/{viewer}", response_model=WalletRead)
def get_wallet(auction_id: int, viewer: str, db: Session = Depends(get_db)):
    return _get_wallet_or_404(db, auction_id, viewer)


def _create_contribution(db: Session, auction_id: int, payload: ContributionCreate, multiplier: float) -> Contribution:
    auction = _get_auction_or_404(db, auction_id)
    if auction.status != AuctionStatus.active:
        raise HTTPException(status_code=409, detail="Auction is not active")

    position = db.query(Position).filter(Position.id == payload.position_id, Position.auction_id == auction_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found in auction")

    wallet = _get_wallet_or_404(db, auction_id, payload.viewer)
    if wallet.balance_available < payload.amount:
        raise HTTPException(status_code=409, detail="Insufficient balance")

    final_amount = calculate_contribution_amount(payload.amount, multiplier)

    previous_leader = (
        db.query(Position)
        .filter(Position.auction_id == auction_id)
        .order_by(Position.points.desc(), Position.id.asc())
        .first()
    )
    previous_leader_id = previous_leader.id if previous_leader and previous_leader.points > 0 else None

    wallet.balance_available -= payload.amount
    position.points += final_amount

    contribution = Contribution(
        auction_id=auction_id,
        position_id=position.id,
        wallet_id=wallet.id,
        base_amount=payload.amount,
        multiplier=multiplier,
        amount=final_amount,
    )
    db.add(contribution)
    _audit_action(
        db,
        auction_id,
        payload.viewer,
        "contribution.create",
        f"position={position.id}, base={payload.amount}, multiplier={multiplier}, amount={final_amount}",
    )

    if is_large_contribution(final_amount, LARGE_CONTRIBUTION_THRESHOLD):
        _audit_action(
            db,
            auction_id,
            payload.viewer,
            "contribution.large",
            f"Large contribution amount={final_amount} to position={position.id}",
        )

    new_leader = (
        db.query(Position)
        .filter(Position.auction_id == auction_id)
        .order_by(Position.points.desc(), Position.id.asc())
        .first()
    )
    new_leader_id = new_leader.id if new_leader and new_leader.points > 0 else None
    if leader_changed(previous_leader_id, new_leader_id):
        _audit_action(
            db,
            auction_id,
            payload.viewer,
            "auction.leader_changed",
            f"Leader changed to position={new_leader_id}",
        )

    db.commit()
    db.refresh(contribution)
    return contribution


@app.post("/auctions/{auction_id}/contributions", response_model=ContributionRead, status_code=status.HTTP_201_CREATED)
def create_contribution(auction_id: int, payload: ContributionCreate, db: Session = Depends(get_db)):
    return _create_contribution(db, auction_id, payload, multiplier=1.0)


@app.post("/auctions/{auction_id}/contributions/spin", response_model=ContributionRead, status_code=status.HTTP_201_CREATED)
def create_contribution_with_spin(auction_id: int, payload: ContributionSpinCreate, db: Session = Depends(get_db)):
    allowed = [value for value in payload.multipliers if value > 0]
    if not allowed:
        raise HTTPException(status_code=422, detail="At least one positive multiplier is required")
    multiplier = random.choice(allowed)
    base_payload = ContributionCreate(viewer=payload.viewer, position_id=payload.position_id, amount=payload.amount)
    return _create_contribution(db, auction_id, base_payload, multiplier=multiplier)


@app.get("/auctions/{auction_id}/contributions", response_model=list[ContributionRead])
def list_contributions(auction_id: int, db: Session = Depends(get_db)):
    return db.query(Contribution).filter(Contribution.auction_id == auction_id).order_by(Contribution.id.desc()).all()
