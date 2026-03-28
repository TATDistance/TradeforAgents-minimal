from __future__ import annotations

from app.action_planner import ActionPlanner
from app.models import PortfolioManagerAction
from app.settings import load_settings


def test_action_planner_rounds_buy_to_board_lot():
    planner = ActionPlanner(load_settings())
    actions = [
        PortfolioManagerAction(symbol="600036", action="BUY", position_pct=0.053, priority=0.8, source=["ai_pm"], reason="buy")
    ]
    planned = planner.plan(actions, {"cash": 100000, "equity": 100000, "positions_detail": []}, {"600036": 41.2})
    assert planned[0].planned_qty % 100 == 0


def test_action_planner_handles_reduce():
    planner = ActionPlanner(load_settings())
    actions = [
        PortfolioManagerAction(symbol="600036", action="REDUCE", reduce_pct=0.5, priority=0.8, source=["ai_pm"], reason="reduce")
    ]
    planned = planner.plan(
        actions,
        {"cash": 10000, "equity": 100000, "positions_detail": [{"symbol": "600036", "can_sell_qty": 1300}]},
        {"600036": 40.0},
    )
    assert planned[0].planned_qty == 600

