from __future__ import annotations

from typing import Iterable, List, Mapping

from .models import ExecutionGateState, MarketPhaseState, PlannedAction, PortfolioManagerAction
from .settings import Settings, load_settings


BOARD_LOT = 100


class ActionPlanner:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def plan(
        self,
        actions: Iterable[PortfolioManagerAction],
        portfolio_feedback: Mapping[str, object],
        quotes: Mapping[str, float],
        phase_state: MarketPhaseState,
        execution_gate: ExecutionGateState,
    ) -> List[PlannedAction]:
        planned: List[PlannedAction] = []
        cash = float(portfolio_feedback.get("cash", 0.0) or 0.0)
        equity = float(portfolio_feedback.get("equity", 0.0) or 0.0)
        positions = portfolio_feedback.get("positions_detail") or []
        position_map = {str(item.get("symbol")): item for item in positions if isinstance(item, Mapping)}

        for action in actions:
            price = float(quotes.get(action.symbol, 0.0) or 0.0)
            executable_now = self._is_executable(action.action, execution_gate)
            intent_only = action.action in {"BUY", "SELL", "REDUCE"} and not executable_now
            if action.action == "BUY":
                target_value = min(cash, equity * float(action.position_pct or 0.0))
                qty = self._round_lot(int(target_value / max(price, 0.01)))
                planned.append(
                    PlannedAction(
                        symbol=action.symbol,
                        action="BUY",
                        planned_qty=qty,
                        planned_price=round(price, 3),
                        estimated_cost=round(qty * price, 4),
                        position_pct=action.position_pct,
                        priority=action.priority,
                        source=action.source,
                        mode_name=action.mode_name,
                        reason=action.reason,
                        intent_only=intent_only,
                        executable_now=executable_now,
                        phase=phase_state.phase,
                        metadata=action.metadata,
                    )
                )
            elif action.action == "REDUCE":
                position = position_map.get(action.symbol, {})
                can_sell_qty = int(position.get("can_sell_qty", 0) or 0)
                qty = self._round_lot(int(can_sell_qty * float(action.reduce_pct or 0.0)))
                planned.append(
                    PlannedAction(
                        symbol=action.symbol,
                        action="REDUCE",
                        planned_qty=min(qty, can_sell_qty),
                        planned_price=round(price, 3),
                        estimated_cost=round(min(qty, can_sell_qty) * price, 4),
                        reduce_pct=action.reduce_pct,
                        priority=action.priority,
                        source=action.source,
                        mode_name=action.mode_name,
                        reason=action.reason,
                        intent_only=intent_only,
                        executable_now=executable_now,
                        phase=phase_state.phase,
                        metadata=action.metadata,
                    )
                )
            elif action.action == "SELL":
                position = position_map.get(action.symbol, {})
                can_sell_qty = int(position.get("can_sell_qty", 0) or 0)
                qty = self._round_lot(can_sell_qty)
                planned.append(
                    PlannedAction(
                        symbol=action.symbol,
                        action="SELL",
                        planned_qty=qty,
                        planned_price=round(price, 3),
                        estimated_cost=round(qty * price, 4),
                        priority=action.priority,
                        source=action.source,
                        mode_name=action.mode_name,
                        reason=action.reason,
                        intent_only=intent_only,
                        executable_now=executable_now,
                        phase=phase_state.phase,
                        metadata=action.metadata,
                    )
                )
            else:
                planned.append(
                    PlannedAction(
                        symbol=action.symbol,
                        action=action.action,
                        planned_qty=0,
                        planned_price=round(price, 3),
                        estimated_cost=0.0,
                        priority=action.priority,
                        source=action.source,
                        mode_name=action.mode_name,
                        reason=action.reason,
                        intent_only=False,
                        executable_now=False,
                        phase=phase_state.phase,
                        metadata=action.metadata,
                    )
                )
        return planned

    @staticmethod
    def _round_lot(quantity: int) -> int:
        if quantity <= 0:
            return 0
        return quantity // BOARD_LOT * BOARD_LOT

    @staticmethod
    def _is_executable(action: str, execution_gate: ExecutionGateState) -> bool:
        if action == "BUY":
            return execution_gate.can_open_position and execution_gate.can_execute_fill
        if action in {"SELL", "REDUCE"}:
            return execution_gate.can_reduce_position and execution_gate.can_execute_fill
        return False
