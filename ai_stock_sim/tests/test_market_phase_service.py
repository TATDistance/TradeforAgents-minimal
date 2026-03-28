from __future__ import annotations

from datetime import datetime

from app.market_phase_service import MarketPhaseService
from app.settings import load_settings


def test_am_continuous_phase_allows_fill():
    service = MarketPhaseService(load_settings())
    phase = service.resolve(datetime.fromisoformat("2026-03-27T10:15:00+08:00"))
    assert phase.phase == "CONTINUOUS_AUCTION_AM"
    assert phase.allow_simulate_fill is True


def test_midday_break_blocks_fill():
    service = MarketPhaseService(load_settings())
    phase = service.resolve(datetime.fromisoformat("2026-03-27T12:00:00+08:00"))
    assert phase.phase == "MIDDAY_BREAK"
    assert phase.allow_simulate_fill is False


def test_post_close_allows_analysis_only():
    service = MarketPhaseService(load_settings())
    phase = service.resolve(datetime.fromisoformat("2026-03-27T15:30:00+08:00"))
    assert phase.phase == "POST_CLOSE"
    assert phase.allow_post_close_analysis is True
    assert phase.allow_simulate_fill is False
