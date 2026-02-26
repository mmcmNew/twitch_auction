import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .database import Base


class AuctionStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    locked = "locked"
    roulette_running = "roulette_running"
    closed = "closed"


class SuggestionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ChannelRole(str, enum.Enum):
    streamer = "streamer"
    moderator = "moderator"
    viewer = "viewer"


class RouletteStatus(str, enum.Enum):
    running = "running"
    finished = "finished"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    login = Column(String(255), nullable=False, unique=True)
    email = Column(String(255), nullable=True, unique=True)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChannelMembership(Base):
    __tablename__ = "channel_memberships"
    __table_args__ = (UniqueConstraint("channel_login", "user_id", "role", name="uq_channel_user_role"),)

    id = Column(Integer, primary_key=True, index=True)
    channel_login = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(ChannelRole), nullable=False)


class RewardPreset(Base):
    __tablename__ = "reward_presets"

    id = Column(Integer, primary_key=True, index=True)
    channel_login = Column(String(255), nullable=False)
    amount = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("channel_login", "amount", name="uq_reward_channel_amount"),)


class ChannelReward(Base):
    __tablename__ = "channel_rewards"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    channel_login = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    amount = Column(Integer, nullable=False)


class Auction(Base):
    __tablename__ = "auctions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    channel_login = Column(String(255), nullable=False)
    status = Column(Enum(AuctionStatus), default=AuctionStatus.draft, nullable=False)
    winner_position_id = Column(Integer, ForeignKey("positions.id", ondelete="SET NULL"), nullable=True)
    source_auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="SET NULL"), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    positions = relationship("Position", back_populates="auction", cascade="all, delete-orphan", foreign_keys="Position.auction_id")
    suggestions = relationship("Suggestion", back_populates="auction", cascade="all, delete-orphan")
    wallets = relationship("Wallet", back_populates="auction", cascade="all, delete-orphan")
    contributions = relationship("Contribution", back_populates="auction", cascade="all, delete-orphan")
    rewards = relationship("ChannelReward", cascade="all, delete-orphan")
    roulette_runs = relationship("RouletteRun", back_populates="auction", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="auction", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    points = Column(Integer, default=0, nullable=False)

    auction = relationship("Auction", back_populates="positions", foreign_keys=[auction_id])
    contributions = relationship("Contribution", back_populates="position", cascade="all, delete-orphan")


class RouletteRun(Base):
    __tablename__ = "roulette_runs"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(RouletteStatus), default=RouletteStatus.running, nullable=False)
    winner_position_id = Column(Integer, ForeignKey("positions.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    auction = relationship("Auction", back_populates="roulette_runs")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    author = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    status = Column(Enum(SuggestionStatus), default=SuggestionStatus.pending, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    auction = relationship("Auction", back_populates="suggestions")


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("auction_id", "viewer", name="uq_wallet_auction_viewer"),)

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    viewer = Column(String(255), nullable=False)
    balance_total = Column(Integer, default=0, nullable=False)
    balance_available = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    auction = relationship("Auction", back_populates="wallets")
    contributions = relationship("Contribution", back_populates="wallet", cascade="all, delete-orphan")


class Contribution(Base):
    __tablename__ = "contributions"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    position_id = Column(Integer, ForeignKey("positions.id", ondelete="CASCADE"), nullable=False)
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    base_amount = Column(Integer, nullable=False)
    multiplier = Column(Float, default=1.0, nullable=False)
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    auction = relationship("Auction", back_populates="contributions")
    position = relationship("Position", back_populates="contributions")
    wallet = relationship("Wallet", back_populates="contributions")


class SuggestionRateLimit(Base):
    __tablename__ = "suggestion_rate_limits"
    __table_args__ = (UniqueConstraint("auction_id", "author", name="uq_suggestion_rate_author"),)

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    author = Column(String(255), nullable=False)
    window_started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    attempts = Column(Integer, default=0, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False)
    actor_login = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    details = Column(String(1024), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    auction = relationship("Auction", back_populates="audit_logs")
