from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from .db import delete_position, fetch_latest_account, fetch_positions, upsert_position, write_account_snapshot, write_order
from .models import AccountSnapshot, FinalSignal, OrderRecord, PlannedAction, PositionRecord, RiskCheckResult
from .settings import Settings, load_settings


class MockBroker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def execute_signal(self, conn, signal: FinalSignal, risk: RiskCheckResult, latest_price: float, signal_id: int | None = None) -> OrderRecord:
        if not risk.allowed or risk.adjusted_qty <= 0:
            order = OrderRecord(
                symbol=signal.symbol,
                side="BUY" if signal.action == "BUY" else "SELL",
                price=signal.entry_price,
                qty=0,
                status="REJECTED",
                note=risk.reject_reason or "风控拒绝",
                strategy_name=signal.strategy_name,
                mode_name=signal.mode_name,
                signal_id=signal_id,
            )
            write_order(conn, order)
            return order

        fill_ratio = 1.0 if signal.action == "SELL" else 0.7
        fill_qty = max(100, int(risk.adjusted_qty * fill_ratio) // 100 * 100)
        fill_qty = min(fill_qty, risk.adjusted_qty)
        execution_price = signal.entry_price * (1 + self.settings.slippage_rate if signal.action == "BUY" else 1 - self.settings.slippage_rate)
        turnover = fill_qty * execution_price
        fee = max(5.0, turnover * self.settings.commission_rate) + turnover * self.settings.transfer_fee_rate
        tax = turnover * self.settings.stamp_duty_rate if signal.action == "SELL" else 0.0
        order = OrderRecord(
            symbol=signal.symbol,
            side="BUY" if signal.action == "BUY" else "SELL",
            price=round(execution_price, 3),
            qty=fill_qty,
            fee=round(fee, 4),
            tax=round(tax, 4),
            slippage=round(turnover * self.settings.slippage_rate, 4),
            status="FILLED" if fill_qty == risk.adjusted_qty else "PARTIAL_FILLED",
            note="模拟成交",
            strategy_name=signal.strategy_name,
            mode_name=signal.mode_name,
            signal_id=signal_id,
        )
        write_order(conn, order)
        self._apply_fill(conn, order, latest_price=latest_price)
        return order

    def execute_action(self, conn, action: PlannedAction, risk: RiskCheckResult, latest_price: float, signal_id: int | None = None) -> OrderRecord | None:
        if action.action in {"HOLD", "AVOID_NEW_BUY", "ENTER_DEFENSIVE_MODE"}:
            return None
        side = "BUY" if action.action == "BUY" else "SELL"
        if not risk.allowed or risk.adjusted_qty <= 0:
            order = OrderRecord(
                symbol=action.symbol,
                side=side,  # type: ignore[arg-type]
                price=action.planned_price,
                qty=0,
                status="REJECTED",
                note=risk.reject_reason or action.reason or "风控拒绝",
                strategy_name="+".join(action.source),
                mode_name=action.mode_name,
                signal_id=signal_id,
            )
            write_order(conn, order)
            return order

        order = OrderRecord(
            symbol=action.symbol,
            side=side,  # type: ignore[arg-type]
            price=round(action.planned_price * (1 + self.settings.slippage_rate if side == "BUY" else 1 - self.settings.slippage_rate), 3),
            qty=risk.adjusted_qty,
            fee=round(risk.est_fee, 4),
            tax=round(risk.est_tax, 4),
            slippage=round(risk.est_slippage, 4),
            status="FILLED",
            note=action.reason,
            strategy_name="+".join(action.source),
            mode_name=action.mode_name,
            signal_id=signal_id,
        )
        write_order(conn, order)
        self._apply_fill(conn, order, latest_price=latest_price)
        return order

    def _apply_fill(self, conn, order: OrderRecord, latest_price: float) -> None:
        account = fetch_latest_account(conn)
        positions = {str(row["symbol"]): row for row in fetch_positions(conn)}
        existing = positions.get(order.symbol)

        if order.side == "BUY":
            cash = account["cash"] - (order.price * order.qty + order.fee + order.tax)
            if existing:
                new_qty = int(existing["qty"]) + order.qty
                total_cost = float(existing["avg_cost"]) * int(existing["qty"]) + order.price * order.qty
                avg_cost = total_cost / max(new_qty, 1)
            else:
                new_qty = order.qty
                avg_cost = order.price
            upsert_position(
                conn,
                PositionRecord(
                    symbol=order.symbol,
                    qty=new_qty,
                    avg_cost=round(avg_cost, 4),
                    last_price=latest_price,
                    market_value=round(latest_price * new_qty, 4),
                    unrealized_pnl=round((latest_price - avg_cost) * new_qty, 4),
                    can_sell_qty=int(existing["can_sell_qty"]) if existing else 0,
                    updated_at=datetime.now(),
                ),
            )
            position_rows = fetch_positions(conn)
            market_value = sum(float(row["market_value"]) for row in position_rows)
            unrealized = sum(float(row["unrealized_pnl"]) for row in position_rows)
            write_account_snapshot(
                conn,
                AccountSnapshot(
                    cash=cash,
                    equity=cash + market_value,
                    market_value=market_value,
                    realized_pnl=account["realized_pnl"],
                    unrealized_pnl=unrealized,
                    drawdown=account["drawdown"],
                ),
            )
            return

        if not existing:
            return
        sell_qty = min(order.qty, int(existing["can_sell_qty"]))
        remaining_qty = int(existing["qty"]) - sell_qty
        realized = (order.price - float(existing["avg_cost"])) * sell_qty - order.fee - order.tax
        cash = account["cash"] + order.price * sell_qty - order.fee - order.tax
        if remaining_qty <= 0:
            delete_position(conn, order.symbol)
        else:
            upsert_position(
                conn,
                PositionRecord(
                    symbol=order.symbol,
                    qty=remaining_qty,
                    avg_cost=float(existing["avg_cost"]),
                    last_price=latest_price,
                    market_value=round(latest_price * remaining_qty, 4),
                    unrealized_pnl=round((latest_price - float(existing["avg_cost"])) * remaining_qty, 4),
                    can_sell_qty=max(0, int(existing["can_sell_qty"]) - sell_qty),
                    updated_at=datetime.now(),
                ),
            )
        position_rows = fetch_positions(conn)
        market_value = sum(float(row["market_value"]) for row in position_rows)
        unrealized = sum(float(row["unrealized_pnl"]) for row in position_rows)
        write_account_snapshot(
            conn,
            AccountSnapshot(
                cash=cash,
                equity=cash + market_value,
                market_value=market_value,
                realized_pnl=account["realized_pnl"] + realized,
                unrealized_pnl=unrealized,
                drawdown=account["drawdown"],
            ),
        )

    def release_t1_positions(self, conn) -> None:
        for row in fetch_positions(conn):
            conn.execute(
                "UPDATE positions SET can_sell_qty = qty, updated_at = ? WHERE symbol = ?",
                (datetime.now().isoformat(timespec="seconds"), row["symbol"]),
            )
