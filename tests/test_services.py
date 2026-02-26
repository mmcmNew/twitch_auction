from datetime import datetime, timezone

from app.models import Auction, AuctionStatus
from app.services import (
    apply_transition,
    calculate_contribution_amount,
    can_transition_auction,
    compute_auction_end,
    is_large_contribution,
    leader_changed,
    build_effect_flags,
    should_reset_rate_limit_window,
    build_stream_embed_url,
    clamp_limit,
)


def test_compute_auction_end_returns_none_without_duration():
    assert compute_auction_end(None) is None


def test_compute_auction_end_uses_duration_minutes():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = compute_auction_end(15, now=now)
    assert end is not None
    assert int((end - now).total_seconds()) == 900


def test_transition_guard_allows_known_flow():
    assert can_transition_auction(AuctionStatus.active, AuctionStatus.locked) is True
    assert can_transition_auction(AuctionStatus.closed, AuctionStatus.active) is False


def test_apply_transition_updates_status_and_end_time():
    auction = Auction(title='Test', channel_login='alice', status=AuctionStatus.draft, duration_minutes=10)
    apply_transition(auction, AuctionStatus.active, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert auction.status == AuctionStatus.active
    assert auction.ends_at is not None


def test_contribution_amount_never_zero():
    assert calculate_contribution_amount(1, 0.1) == 1


def test_large_contribution_threshold_check():
    assert is_large_contribution(1000, 1000) is True
    assert is_large_contribution(999, 1000) is False


def test_leader_changed_flag_logic():
    assert leader_changed(None, 10) is True
    assert leader_changed(10, 10) is False


def test_rate_limit_window_reset_detection():
    started = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 11, 1, tzinfo=timezone.utc)
    assert should_reset_rate_limit_window(started, now=now, window_hours=1) is True


def test_effect_flags_builder():
    flags = build_effect_flags({"contribution.create", "auction.leader_changed"}, seconds_to_end=240)
    assert flags["leader_changed"] is True
    assert flags["large_contribution"] is False
    assert flags["auction_ending_soon"] is True
    assert flags["new_vote_or_suggestion"] is True


def test_build_stream_embed_url_default_parent():
    url = build_stream_embed_url("alice")
    assert "channel=alice" in url
    assert "parent=localhost" in url


def test_clamp_limit_bounds():
    assert clamp_limit(0) == 1
    assert clamp_limit(50) == 50
    assert clamp_limit(500) == 100


def test_seconds_to_end_handles_naive_and_none():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert seconds_to_end(None, now=now) is None

    naive_end = datetime(2026, 1, 1, 10, 5)
    assert seconds_to_end(naive_end, now=now) == 300
