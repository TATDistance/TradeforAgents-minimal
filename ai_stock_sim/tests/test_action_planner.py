from __future__ import annotations

from app.action_planner import ActionPlanner
from app.models import ExecutionGateState, MarketPhaseState, PortfolioManagerAction
from app.settings import load_settings


def test_action_planner_rounds_buy_to_board_lot():
    planner = ActionPlanner(load_settings())
    actions = [
        PortfolioManagerAction(symbol="600036", action="BUY", position_pct=0.053, priority=0.8, source=["ai_pm"], reason="buy")
    ]
    phase_state = MarketPhaseState(is_trading_day=True, phase="CONTINUOUS_AUCTION_AM", allow_new_buy=True, allow_sell_reduce=True, allow_simulate_fill=True, allow_signal_generation=True, allow_ai_decision=True, allow_market_update=True, trade_date="2026-03-27")
    execution_gate = ExecutionGateState(can_update_market=True, can_generate_signal=True, can_run_ai_decision=True, can_plan_actions=True, can_open_position=True, can_reduce_position=True, can_execute_fill=True, phase="CONTINUOUS_AUCTION_AM", is_trading_day=True)
    planned = planner.plan(actions, {"cash": 100000, "equity": 100000, "positions_detail": []}, {"600036": 41.2}, phase_state, execution_gate)
    assert planned[0].planned_qty % 100 == 0
    assert planned[0].executable_now is True


def test_action_planner_handles_reduce():
    planner = ActionPlanner(load_settings())
    actions = [
        PortfolioManagerAction(symbol="600036", action="REDUCE", reduce_pct=0.5, priority=0.8, source=["ai_pm"], reason="reduce")
    ]
    phase_state = MarketPhaseState(is_trading_day=True, phase="MIDDAY_BREAK", allow_new_buy=False, allow_sell_reduce=False, allow_simulate_fill=False, allow_signal_generation=True, allow_ai_decision=True, allow_market_update=True, trade_date="2026-03-27")
    execution_gate = ExecutionGateState(can_update_market=True, can_generate_signal=True, can_run_ai_decision=True, can_plan_actions=True, can_open_position=False, can_reduce_position=False, can_execute_fill=False, intent_only_mode=True, phase="MIDDAY_BREAK", is_trading_day=True)
    planned = planner.plan(
        actions,
        {"cash": 10000, "equity": 100000, "positions_detail": [{"symbol": "600036", "can_sell_qty": 1300}]},
        {"600036": 40.0},
        phase_state,
        execution_gate,
    )
    assert planned[0].planned_qty == 600
    assert planned[0].intent_only is True
