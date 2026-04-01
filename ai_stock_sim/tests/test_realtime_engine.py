from __future__ import annotations

from app.realtime_engine import RealtimeEngine
from app.settings import load_settings


def test_realtime_engine_only_returns_changed_symbols() -> None:
    engine = RealtimeEngine(load_settings())

    first = engine.select_symbols_for_cycle(
        symbols=["300750", "688525"],
        snapshot_rows={
            "300750": {"latest_price": 100.0, "pct_change": 0.01, "amount": 100_000_000},
            "688525": {"latest_price": 200.0, "pct_change": 0.01, "amount": 120_000_000},
        },
        feature_scores={},
        market_regime="RANGE_BOUND",
        portfolio_feedback={"cash_pct": 0.8, "positions_detail": []},
        phase_name="CONTINUOUS_AUCTION_AM",
    )
    assert set(first["changed_symbols"]) == {"300750", "688525"}

    second = engine.select_symbols_for_cycle(
        symbols=["300750", "688525"],
        snapshot_rows={
            "300750": {"latest_price": 100.0, "pct_change": 0.01, "amount": 100_000_000},
            "688525": {"latest_price": 200.0, "pct_change": 0.01, "amount": 120_000_000},
        },
        feature_scores={},
        market_regime="RANGE_BOUND",
        portfolio_feedback={"cash_pct": 0.8, "positions_detail": []},
        phase_name="CONTINUOUS_AUCTION_AM",
    )
    assert second["changed_symbols"] == []

    third = engine.select_symbols_for_cycle(
        symbols=["300750", "688525"],
        snapshot_rows={
            "300750": {"latest_price": 101.5, "pct_change": 0.025, "amount": 150_000_000},
            "688525": {"latest_price": 200.0, "pct_change": 0.01, "amount": 120_000_000},
        },
        feature_scores={},
        market_regime="RANGE_BOUND",
        portfolio_feedback={"cash_pct": 0.8, "positions_detail": []},
        phase_name="CONTINUOUS_AUCTION_AM",
    )
    assert third["changed_symbols"] == ["300750"]
