from __future__ import annotations

from app.ai_decision_engine import AIDecisionEngine
from app.settings import load_settings


def test_ai_decision_engine_can_open_buy() -> None:
    engine = AIDecisionEngine(load_settings())
    context = {
        "symbol": "600036",
        "snapshot": {"latest_price": 40.0, "pct_change": 0.02, "amount": 150_000_000},
        "technical_features": {"rsi_14": 58, "trend_slope_20d": 0.08, "ma20_bias": 0.03, "macd_hist": 0.02},
        "portfolio_state": {"cash_pct": 0.9, "drawdown": 0.01, "risk_mode": "NORMAL"},
        "position_state": {"has_position": False, "can_sell_qty": 0},
        "risk_constraints": {"allow_new_buy": True},
        "market_regime": {"regime": "TRENDING_UP"},
        "market_phase": {"phase": "CONTINUOUS_AUCTION_AM"},
        "execution_gate": {"can_execute_fill": True, "can_open_position": True},
    }
    decision = engine.decide_symbol(
        symbol="600036",
        context=context,
        feature_score_payload={"feature_score": 0.78, "final_score": 0.81, "dominant_direction": "LONG"},
        trade_date="2026-03-28",
    )
    assert decision.action == "BUY"
    assert decision.position_pct > 0
    assert decision.ai_score > 0
    assert decision.execution_score >= decision.setup_score - 0.2


def test_ai_decision_engine_can_reduce_or_sell_position() -> None:
    engine = AIDecisionEngine(load_settings())
    context = {
        "symbol": "600036",
        "snapshot": {"latest_price": 39.0, "pct_change": -0.03, "amount": 130_000_000},
        "technical_features": {"rsi_14": 42, "trend_slope_20d": -0.04, "ma20_bias": -0.03, "macd_hist": -0.02},
        "portfolio_state": {"cash_pct": 0.2, "drawdown": 0.04, "risk_mode": "DEFENSIVE"},
        "position_state": {"has_position": True, "can_sell_qty": 1000, "unrealized_pct": 0.08, "hold_days": 12},
        "risk_constraints": {"allow_new_buy": False},
        "market_regime": {"regime": "HIGH_VOLATILITY"},
        "market_phase": {"phase": "CONTINUOUS_AUCTION_PM"},
        "execution_gate": {"can_execute_fill": True, "can_reduce_position": True},
    }
    decision = engine.decide_symbol(
        symbol="600036",
        context=context,
        feature_score_payload={"feature_score": -0.15, "final_score": -0.12, "dominant_direction": "SHORT"},
        trade_date="2026-03-28",
    )
    assert decision.action in {"REDUCE", "SELL", "HOLD"}
    assert decision.risk_mode in {"DEFENSIVE", "RISK_OFF"}
    assert decision.ai_score <= 0


def test_ai_decision_engine_does_not_treat_percent_value_as_limit_up() -> None:
    engine = AIDecisionEngine(load_settings())
    context = {
        "symbol": "300750",
        "snapshot": {"latest_price": 406.0, "pct_change": 1.07, "amount": 3_500_000_000},
        "technical_features": {"rsi_14": 56, "trend_slope_20d": 0.05, "ma20_bias": 0.02, "macd_hist": 0.01},
        "portfolio_state": {"cash_pct": 0.85, "drawdown": 0.01, "risk_mode": "NORMAL"},
        "position_state": {"has_position": False, "can_sell_qty": 0},
        "risk_constraints": {"allow_new_buy": True},
        "market_regime": {"regime": "RANGE_BOUND"},
        "market_phase": {"phase": "CONTINUOUS_AUCTION_AM"},
        "execution_gate": {"can_execute_fill": True},
    }
    decision = engine.decide_symbol(
        symbol="300750",
        context=context,
        feature_score_payload={"feature_score": 0.45, "final_score": 0.42, "dominant_direction": "LONG"},
        trade_date="2026-04-01",
    )
    assert "已接近涨停，不宜追高" not in decision.warnings
