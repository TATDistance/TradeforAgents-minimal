from __future__ import annotations

from app.settings import load_settings
from app.symbol_runtime_state import SymbolRuntimeStateStore
from app.trigger_service import TriggerService


def test_trigger_service_detects_price_change() -> None:
    settings = load_settings()
    service = TriggerService(settings)
    store = SymbolRuntimeStateStore()
    store.update_market("300750", price=100.0, pct_change=0.01, amount=100_000_000, phase="CONTINUOUS_AUCTION_AM", market_regime="RANGE_BOUND")
    store.mark_trigger("300750", ["init"])

    results = service.detect(
        symbols=["300750"],
        snapshot_rows={"300750": {"latest_price": 101.0, "pct_change": 0.02, "amount": 130_000_000}},
        feature_scores={"300750": {"feature_score": 0.4}},
        market_regime="RANGE_BOUND",
        portfolio_feedback={"cash_pct": 0.8, "positions_detail": []},
        phase_name="CONTINUOUS_AUCTION_AM",
        state_store=store,
    )

    assert results
    assert results[0].symbol == "300750"
    assert "PRICE_UPDATED" in results[0].event_types


def test_trigger_service_ignores_noise_under_threshold() -> None:
    settings = load_settings()
    service = TriggerService(settings)
    store = SymbolRuntimeStateStore()
    store.update_market("300750", price=100.0, pct_change=0.01, amount=100_000_000, phase="CONTINUOUS_AUCTION_AM", market_regime="RANGE_BOUND")

    results = service.detect(
        symbols=["300750"],
        snapshot_rows={"300750": {"latest_price": 100.05, "pct_change": 0.0105, "amount": 100_500_000}},
        feature_scores={"300750": {"feature_score": 0.4}},
        market_regime="RANGE_BOUND",
        portfolio_feedback={"cash_pct": 0.8, "positions_detail": []},
        phase_name="CONTINUOUS_AUCTION_AM",
        state_store=store,
    )

    assert results == []
