from datetime import datetime
from typing import List

from pydantic import BaseModel, Field

from .models import AuctionStatus, ChannelRole, RouletteStatus, SuggestionStatus


class EmailAuthRegister(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    login: str | None = Field(default=None, min_length=1, max_length=255)


class EmailAuthLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=255)


class AuthTokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_login: str


class UserCreate(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)


class UserRead(BaseModel):
    id: int
    login: str
    email: str | None
    display_name: str

    class Config:
        from_attributes = True


class MembershipAssign(BaseModel):
    channel_login: str = Field(min_length=1, max_length=255)
    user_login: str = Field(min_length=1, max_length=255)
    role: ChannelRole


class MembershipRead(BaseModel):
    id: int
    channel_login: str
    user_id: int
    role: ChannelRole

    class Config:
        from_attributes = True


class RewardPresetWrite(BaseModel):
    amounts: List[int] = Field(default_factory=list)


class RewardPresetRead(BaseModel):
    id: int
    channel_login: str
    amount: int
    is_enabled: bool

    class Config:
        from_attributes = True


class ChannelRewardRead(BaseModel):
    id: int
    auction_id: int
    channel_login: str
    title: str
    amount: int

    class Config:
        from_attributes = True


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class PositionRead(BaseModel):
    id: int
    auction_id: int
    title: str
    points: int

    class Config:
        from_attributes = True


class AuctionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    channel_login: str = Field(min_length=1, max_length=255)
    duration_minutes: int | None = Field(default=None, gt=0)


class AuctionRead(BaseModel):
    id: int
    title: str
    channel_login: str
    status: AuctionStatus
    winner_position_id: int | None
    source_auction_id: int | None
    duration_minutes: int | None
    ends_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class AuctionDetail(AuctionRead):
    positions: List[PositionRead]


class AuctionCloneRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    carry_scores: bool = True
    reset_position_titles: List[str] = Field(default_factory=list)


class AuctionRestartRequest(AuctionCloneRequest):
    auto_start: bool = False


class HistoryAuctionRead(BaseModel):
    auction_id: int
    title: str
    channel_login: str
    closed_at: datetime
    total_points: int
    winner_title: str | None


class HistoryAuctionDetail(HistoryAuctionRead):
    positions: List[PositionRead]


class SuggestionCreate(BaseModel):
    author: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)


class SuggestionRead(BaseModel):
    id: int
    auction_id: int
    author: str
    title: str
    status: SuggestionStatus
    created_at: datetime

    class Config:
        from_attributes = True


class WalletTopUp(BaseModel):
    viewer: str = Field(min_length=1, max_length=255)
    amount: int = Field(gt=0)


class WalletRead(BaseModel):
    id: int
    auction_id: int
    viewer: str
    balance_total: int
    balance_available: int

    class Config:
        from_attributes = True


class ContributionCreate(BaseModel):
    viewer: str = Field(min_length=1, max_length=255)
    position_id: int
    amount: int = Field(gt=0)


class ContributionSpinCreate(ContributionCreate):
    multipliers: List[float] = Field(default_factory=lambda: [0.5, 1.0, 2.0])


class ContributionRead(BaseModel):
    id: int
    auction_id: int
    position_id: int
    wallet_id: int
    base_amount: int
    multiplier: float
    amount: int
    created_at: datetime

    class Config:
        from_attributes = True


class RouletteRunRead(BaseModel):
    id: int
    auction_id: int
    status: RouletteStatus
    winner_position_id: int | None
    started_at: datetime
    finished_at: datetime | None

    class Config:
        from_attributes = True


class RouletteFinishRequest(BaseModel):
    winner_position_id: int


class AuditLogRead(BaseModel):
    id: int
    auction_id: int
    actor_login: str
    action: str
    details: str
    created_at: datetime

    class Config:
        from_attributes = True


class AuctionUiContextRead(BaseModel):
    auction_id: int
    stream_embed_url: str
    is_ending_soon: bool
    seconds_to_end: int | None


class ActivityEventRead(BaseModel):
    type: str
    actor: str
    created_at: datetime
    message: str


class AuctionEffectsRead(BaseModel):
    auction_id: int
    leader_changed: bool
    large_contribution: bool
    auction_ending_soon: bool
    new_vote_or_suggestion: bool


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict | list | str | None = None
