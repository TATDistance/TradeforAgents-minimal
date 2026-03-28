from __future__ import annotations

from app.models import MarketRegimeState
from app.settings import load_settings
from app.strategy_weight_service import StrategyWeightService


def test_strategy_weights_shift_in_trending_up():
    service = StrategyWeightService(load_settings())
    weights = service.resolve_weights(MarketRegimeState(regime="TRENDING_UP", confidence=0.8, reason="up", risk_bias="NORMAL"))
    assert weights["breakout"] > weights["mean_reversion"]
    assert weights["momentum"] >= 1.0


def test_strategy_weights_reduce_under_drawdown_feedback():
    settings = load_settings()
    service = StrategyWeightService(settings)
    weights = service.resolve_weights(
        MarketRegimeState(regime="RANGE_BOUND", confidence=0.6, reason="range", risk_bias="NORMAL"),
        {"drawdown": 0.04, "total_position_pct": 0.8, "strategy_scores": {"momentum": 55}},
    )
    assert weights["momentum"] < 1.0
