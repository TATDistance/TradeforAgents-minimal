from __future__ import annotations

from .models import ExecutionGateState, MarketPhaseState
from .settings import Settings, load_settings


class ExecutionGateService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def resolve(self, phase_state: MarketPhaseState) -> ExecutionGateState:
        can_execute_fill = phase_state.allow_simulate_fill
        if self.settings.execution_gate.block_all_fill_outside_continuous_auction and phase_state.phase not in {
            "CONTINUOUS_AUCTION_AM",
            "CONTINUOUS_AUCTION_PM",
        }:
            can_execute_fill = False

        can_open_position = phase_state.allow_new_buy and can_execute_fill
        if self.settings.execution_gate.block_new_buy_in_closing_call and phase_state.phase == "CLOSING_AUCTION":
            can_open_position = False

        can_reduce_position = phase_state.allow_sell_reduce and can_execute_fill
        can_generate_report = phase_state.allow_report_generation and self.settings.execution_gate.allow_post_close_analysis

        return ExecutionGateState(
            can_update_market=phase_state.allow_market_update,
            can_generate_signal=phase_state.allow_signal_generation,
            can_run_ai_decision=phase_state.allow_ai_decision,
            can_plan_actions=phase_state.allow_signal_generation or phase_state.allow_post_close_analysis,
            can_open_position=can_open_position,
            can_reduce_position=can_reduce_position,
            can_execute_fill=can_execute_fill,
            can_generate_report=can_generate_report,
            can_mark_to_market=True,
            intent_only_mode=phase_state.allow_signal_generation and not can_execute_fill,
            reason=phase_state.reason,
            phase=phase_state.phase,
            is_trading_day=phase_state.is_trading_day,
        )
