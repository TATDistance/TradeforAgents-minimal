from __future__ import annotations

import pandas as pd

from app.decision_context_builder import DecisionContextBuilder
from app.feature_service import FeatureService
from app.models import ExecutionGateState, MarketPhaseState, MarketRegimeState
from app.settings import load_settings


def _sample_frame() -> pd.DataFrame:
    close_values = [20 + idx * 0.12 for idx in range(120)]
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=120, freq="B"),
            "open": close_values,
            "high": [value * 1.01 for value in close_values],
            "low": [value * 0.99 for value in close_values],
            "close": close_values,
            "volume": [2_000_000 + idx * 1_500 for idx in range(120)],
            "amount": [100_000_000 + idx * 80_000 for idx in range(120)],
        }
    )


def test_decision_context_builder_contains_required_sections() -> None:
    settings = load_settings()
    frame = _sample_frame()
    feature_service = FeatureService(settings)
    builder = DecisionContextBuilder(settings)
    features = feature_service.build_for_symbol("600036", frame)
    context = builder.build_for_symbol(
        symbol="600036",
        snapshot={"latest_price": 34.5, "pct_change": 0.015, "amount": 120_000_000, "turnover_rate": 2.3},
        strategy_features=features,
        frame=frame,
        market_regime=MarketRegimeState(regime="TRENDING_UP", confidence=0.7, reason="测试", risk_bias="NORMAL"),
        portfolio_feedback={
            "cash": 100000,
            "equity": 100000,
            "cash_pct": 0.8,
            "total_position_pct": 0.2,
            "drawdown": 0.01,
            "today_open_ratio": 0.1,
            "risk_mode": "NORMAL",
            "positions_detail": [],
        },
        phase_state=MarketPhaseState(is_trading_day=True, phase="CONTINUOUS_AUCTION_AM", allow_market_update=True, allow_signal_generation=True, allow_ai_decision=True, allow_new_buy=True, allow_sell_reduce=True, allow_simulate_fill=True, trade_date="2026-03-27"),
        execution_gate=ExecutionGateState(can_update_market=True, can_generate_signal=True, can_run_ai_decision=True, can_plan_actions=True, can_open_position=True, can_reduce_position=True, can_execute_fill=True, phase="CONTINUOUS_AUCTION_AM", is_trading_day=True),
    )
    assert context["symbol"] == "600036"
    assert "snapshot" in context
    assert "strategy_features" in context
    assert "technical_features" in context
    assert "entry_structure" in context
    assert "exit_structure" in context
    assert "market_regime" in context
    assert "market_phase" in context
    assert "execution_gate" in context
    assert "portfolio_state" in context
    assert "position_state" in context
    assert "risk_constraints" in context
