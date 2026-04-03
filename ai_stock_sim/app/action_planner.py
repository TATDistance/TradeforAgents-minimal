from __future__ import annotations

from typing import Iterable, List, Mapping, Sequence, Tuple

from .models import ExecutionGateState, MarketPhaseState, PlannedAction, PortfolioManagerAction
from .settings import Settings, load_settings, resolve_max_single_position_pct


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
        action_list = list(actions)
        cash = float(portfolio_feedback.get("cash", 0.0) or 0.0)
        equity = float(portfolio_feedback.get("equity", 0.0) or 0.0)
        today_open_ratio = float(portfolio_feedback.get("today_open_ratio", 0.0) or 0.0)
        positions = portfolio_feedback.get("positions_detail") or []
        position_map = {str(item.get("symbol")): item for item in positions if isinstance(item, Mapping)}
        explicit_reduce_symbols = {
            str(item.symbol)
            for item in action_list
            if item.action in {"REDUCE", "SELL"} and str(item.symbol) not in {"", "*"}
        }

        for action in action_list:
            price = float(quotes.get(action.symbol, 0.0) or 0.0)
            executable_now = self._is_executable(action.action, execution_gate)
            intent_only = action.action in {"BUY", "SELL", "REDUCE"} and not executable_now
            if action.action == "BUY":
                target_value = min(cash, equity * float(action.position_pct or 0.0))
                qty = self._round_lot(int(target_value / max(price, 0.01)))
                adjusted_position_pct = float(action.position_pct or 0.0)
                rebalance_actions: List[PlannedAction] = []
                if executable_now and price > 0:
                    rebalance_actions, qty, adjusted_position_pct = self._plan_cash_rebalance_for_buy(
                        action=action,
                        price=price,
                        cash=cash,
                        equity=equity,
                        today_open_ratio=today_open_ratio,
                        positions=list(positions) if isinstance(positions, list) else [],
                        position_map=position_map,
                        quotes=quotes,
                        phase_state=phase_state,
                        explicit_reduce_symbols=explicit_reduce_symbols,
                    )
                    if rebalance_actions:
                        planned.extend(rebalance_actions)
                planned.append(
                    PlannedAction(
                        symbol=action.symbol,
                        action="BUY",
                        planned_qty=qty,
                        planned_price=round(price, 3),
                        estimated_cost=round(qty * price, 4),
                        position_pct=round(adjusted_position_pct, 4),
                        priority=action.priority,
                        source=action.source,
                        mode_name=action.mode_name,
                        reason=action.reason,
                        intent_only=intent_only,
                        executable_now=executable_now,
                        phase=phase_state.phase,
                        metadata={
                            **action.metadata,
                            "rebalance_actions": [item.model_dump() for item in rebalance_actions],
                        },
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
    def _round_lot_up(quantity: int) -> int:
        if quantity <= 0:
            return 0
        return ((quantity + BOARD_LOT - 1) // BOARD_LOT) * BOARD_LOT

    def _plan_cash_rebalance_for_buy(
        self,
        *,
        action: PortfolioManagerAction,
        price: float,
        cash: float,
        equity: float,
        today_open_ratio: float,
        positions: Sequence[Mapping[str, object]],
        position_map: Mapping[str, Mapping[str, object]],
        quotes: Mapping[str, float],
        phase_state: MarketPhaseState,
        explicit_reduce_symbols: set[str],
    ) -> Tuple[List[PlannedAction], int, float]:
        if equity <= 0 or price <= 0:
            return [], 0, float(action.position_pct or 0.0)

        one_lot_cost = BOARD_LOT * price
        max_single_position_pct = resolve_max_single_position_pct(self.settings, equity)
        current_value = float(position_map.get(action.symbol, {}).get("market_value", 0.0) or 0.0)
        single_cap = max(0.0, equity * max_single_position_pct - current_value)
        daily_cap = max(0.0, equity * self.settings.max_daily_open_position_pct - today_open_ratio * equity)
        required_budget = one_lot_cost * 1.01
        requested_pct = float(action.position_pct or 0.0)
        required_pct = min(max_single_position_pct, max(requested_pct, required_budget / max(equity, 1.0)))

        # If one lot itself breaches portfolio caps, selling existing positions cannot solve it.
        if required_budget > single_cap + 1e-6 or required_budget > daily_cap + 1e-6:
            target_value = min(cash, equity * requested_pct)
            return [], self._round_lot(int(target_value / max(price, 0.01))), requested_pct

        desired_qty = self._round_lot(int((equity * required_pct) / max(price, 0.01)))
        if desired_qty < BOARD_LOT:
            desired_qty = BOARD_LOT

        if cash >= required_budget:
            return [], desired_qty, required_pct

        remaining_shortfall = required_budget - cash
        temporary_actions: List[PlannedAction] = []
        candidates: List[Mapping[str, object]] = []
        for item in positions:
            if not isinstance(item, Mapping):
                continue
            symbol = str(item.get("symbol") or "")
            if not symbol or symbol == action.symbol or symbol in explicit_reduce_symbols:
                continue
            can_sell_qty = self._round_lot(int(item.get("can_sell_qty", 0) or 0))
            unrealized_pct = float(item.get("unrealized_pct", 0.0) or 0.0)
            if can_sell_qty < BOARD_LOT or unrealized_pct <= 0:
                continue
            candidates.append(item)

        candidates.sort(
            key=lambda item: (
                float(item.get("unrealized_pct", 0.0) or 0.0),
                float(item.get("market_value", 0.0) or 0.0),
            ),
            reverse=True,
        )

        for item in candidates:
            if remaining_shortfall <= 0:
                break
            symbol = str(item.get("symbol") or "")
            can_sell_qty = self._round_lot(int(item.get("can_sell_qty", 0) or 0))
            if can_sell_qty < BOARD_LOT:
                continue
            last_price = float(quotes.get(symbol) or item.get("last_price") or 0.0)
            if last_price <= 0:
                continue
            max_reduce_qty = self._round_lot(int(can_sell_qty * 0.5))
            if max_reduce_qty < BOARD_LOT:
                max_reduce_qty = can_sell_qty if can_sell_qty >= BOARD_LOT else 0
            if max_reduce_qty < BOARD_LOT:
                continue
            needed_qty = self._round_lot_up(int(remaining_shortfall / max(last_price, 0.01)))
            reduce_qty = min(max_reduce_qty, max(BOARD_LOT, needed_qty))
            reduce_qty = self._round_lot(reduce_qty)
            if reduce_qty < BOARD_LOT:
                continue
            reduce_pct = min(1.0, reduce_qty / max(can_sell_qty, 1))
            temporary_actions.append(
                PlannedAction(
                    symbol=symbol,
                    action="REDUCE",
                    planned_qty=reduce_qty,
                    planned_price=round(last_price, 3),
                    estimated_cost=round(reduce_qty * last_price, 4),
                    reduce_pct=round(reduce_pct, 4),
                    priority=round(min(0.99, action.priority + 0.12), 4),
                    source=["auto_rebalance_cash", *action.source],
                    mode_name=action.mode_name,
                    reason=f"为买入 {action.symbol} 腾挪资金，先减仓已有浮盈持仓。",
                    intent_only=False,
                    executable_now=True,
                    phase=phase_state.phase,
                    metadata={"rebalance_target": action.symbol, "auto_generated": True},
                )
            )
            remaining_shortfall -= reduce_qty * last_price * 0.995

        if remaining_shortfall > 0:
            target_value = min(cash, equity * requested_pct)
            return [], self._round_lot(int(target_value / max(price, 0.01))), requested_pct

        return temporary_actions, desired_qty, required_pct

    @staticmethod
    def _is_executable(action: str, execution_gate: ExecutionGateState) -> bool:
        if action == "BUY":
            return execution_gate.can_open_position and execution_gate.can_execute_fill
        if action in {"SELL", "REDUCE"}:
            return execution_gate.can_reduce_position and execution_gate.can_execute_fill
        return False
