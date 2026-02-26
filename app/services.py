from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Auction, AuctionStatus


def compute_auction_end(duration_minutes: int | None, now: datetime | None = None) -> datetime | None:
    if not duration_minutes:
        return None
    point = now or datetime.now(timezone.utc)
    return point + timedelta(minutes=duration_minutes)


def can_transition_auction(current: AuctionStatus, target: AuctionStatus) -> bool:
    allowed = {
        AuctionStatus.draft: {AuctionStatus.active, AuctionStatus.closed},
        AuctionStatus.active: {AuctionStatus.locked, AuctionStatus.closed},
        AuctionStatus.locked: {AuctionStatus.roulette_running, AuctionStatus.closed},
        AuctionStatus.roulette_running: {AuctionStatus.closed},
        AuctionStatus.closed: set(),
    }
    return target in allowed[current]


def apply_transition(auction: Auction, target: AuctionStatus, now: datetime | None = None) -> None:
    if not can_transition_auction(auction.status, target):
        raise ValueError(f"Invalid transition: {auction.status} -> {target}")
    auction.status = target
    if target == AuctionStatus.active:
        auction.ends_at = compute_auction_end(auction.duration_minutes, now=now)


def calculate_contribution_amount(base_amount: int, multiplier: float) -> int:
    return max(1, int(base_amount * multiplier))


def is_large_contribution(final_amount: int, threshold: int) -> bool:
    return final_amount >= threshold


def leader_changed(previous_leader_id: int | None, new_leader_id: int | None) -> bool:
    return new_leader_id is not None and new_leader_id != previous_leader_id


def should_reset_rate_limit_window(window_started_at: datetime, now: datetime, window_hours: int = 1) -> bool:
    reference = window_started_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return now - reference >= timedelta(hours=window_hours)


def build_effect_flags(actions: set[str], seconds_to_end: int | None) -> dict[str, bool]:
    return {
        "leader_changed": "auction.leader_changed" in actions,
        "large_contribution": "contribution.large" in actions,
        "auction_ending_soon": seconds_to_end is not None and seconds_to_end <= 300,
        "new_vote_or_suggestion": ("contribution.create" in actions or "suggestion.created" in actions),
    }


def build_stream_embed_url(channel_login: str, parent_host: str = "localhost") -> str:
    return f"https://player.twitch.tv/?channel={channel_login}&parent={parent_host}"


def clamp_limit(value: int, min_value: int = 1, max_value: int = 100) -> int:
    return max(min_value, min(max_value, value))


def seconds_to_end(ends_at: datetime | None, now: datetime | None = None) -> int | None:
    if ends_at is None:
        return None
    current = now or datetime.now(timezone.utc)
    target = ends_at
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0, int((target - current).total_seconds()))
