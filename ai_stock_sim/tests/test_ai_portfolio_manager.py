from __future__ import annotations

from app.ai_portfolio_manager import AIPortfolioManager
from app.models import FinalSignal, MarketRegimeState
from app.settings import load_settings


def test_ai_portfolio_manager_can_emit_reduce_and_sell():
    manager = AIPortfolioManager(load_settings())
    regime = MarketRegimeState(regime="RISK_OFF", confidence=0.8, reason="risk", risk_bias="RISK_OFF")
    feedback = {
        "drawdown": 0.06,
        "total_position_pct": 0.75,
        "positions_detail": [
            {"symbol": "600036", "can_sell_qty": 1000, "unrealized_pct": 0.08, "hold_days": 12},
            {"symbol": "600031", "can_sell_qty": 800, "unrealized_pct": -0.06, "hold_days": 3},
        ],
    }
    decision = manager.review(regime, feedback, [], {"momentum": 1.0})
    actions = {item.symbol: item.action for item in decision.actions if item.symbol != "*"}
    assert decision.risk_mode == "RISK_OFF"
    assert actions["600036"] in {"SELL", "REDUCE"}
    assert actions["600031"] == "SELL"


def test_ai_portfolio_manager_can_add_buy_actions():
    manager = AIPortfolioManager(load_settings())
    regime = MarketRegimeState(regime="TRENDING_UP", confidence=0.8, reason="up", risk_bias="NORMAL")
    feedback = {"drawdown": 0.0, "total_position_pct": 0.2, "positions_detail": []}
    signal = FinalSignal(
        symbol="600036",
        action="BUY",
        entry_price=40.0,
        position_pct=0.1,
        confidence=0.82,
        source_strategies=["momentum", "breakout"],
        ai_approved=True,
        weighted_score=0.88,
    )
    decision = manager.review(regime, feedback, [signal], {"momentum": 1.2})
    assert any(item.symbol == "600036" and item.action == "BUY" for item in decision.actions)
