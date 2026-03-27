from __future__ import annotations

import sqlite3
from typing import List, Optional

from .config import AppConfig, load_config
from .db import compute_account_state, latest_snapshot, max_historical_equity, now_ts
from .market_data import PriceBar, ResultBarStore, midpoint


COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
TRANSFER_FEE_RATE = 0.00001
STAMP_DUTY_RATE = 0.0005
EPSILON = 1e-6


def _commission(turnover: float) -> float:
    return max(turnover * COMMISSION_RATE, MIN_COMMISSION)


def _transfer_fee(turnover: float) -> float:
    return turnover * TRANSFER_FEE_RATE


def _stamp_duty(turnover: float) -> float:
    return turnover * STAMP_DUTY_RATE


def _calc_buy_cost(turnover: float) -> float:
    return round(_commission(turnover) + _transfer_fee(turnover), 4)


def _calc_sell_cost(turnover: float) -> float:
    return round(_commission(turnover) + _transfer_fee(turnover) + _stamp_duty(turnover), 4)


def _upsert_position(
    conn: sqlite3.Connection,
    ticker: str,
    market: str,
    quantity: int,
    can_sell_qty: int,
    pending_sellable_qty: int,
    avg_cost: float,
    last_price: float,
) -> None:
    market_value = round(quantity * last_price, 4)
    unrealized_pnl = round((last_price - avg_cost) * quantity, 4)
    existing = conn.execute(
        "SELECT ticker FROM positions WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE positions
            SET market = ?, quantity = ?, can_sell_qty = ?, pending_sellable_qty = ?,
                avg_cost = ?, last_price = ?, market_value = ?, unrealized_pnl = ?, updated_at = ?
            WHERE ticker = ?
            """,
            (
                market,
                quantity,
                can_sell_qty,
                pending_sellable_qty,
                avg_cost,
                last_price,
                market_value,
                unrealized_pnl,
                now_ts(),
                ticker,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO positions (
                ticker, market, quantity, can_sell_qty, pending_sellable_qty, avg_cost,
                last_price, market_value, unrealized_pnl, opened_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                market,
                quantity,
                can_sell_qty,
                pending_sellable_qty,
                avg_cost,
                last_price,
                market_value,
                unrealized_pnl,
                now_ts(),
                now_ts(),
            ),
        )


def _delete_position(conn: sqlite3.Connection, ticker: str) -> None:
    conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))


def _prepare_trade_date(conn: sqlite3.Connection, trade_date: str) -> None:
    snapshot = latest_snapshot(conn)
    if not snapshot:
        return
    last_date = str(snapshot["snapshot_date"])
    if last_date >= trade_date:
        return
    conn.execute(
        """
        UPDATE positions
        SET can_sell_qty = can_sell_qty + pending_sellable_qty,
            pending_sellable_qty = 0,
            updated_at = ?
        """,
        (now_ts(),),
    )


def _ensure_order_row(
    conn: sqlite3.Connection,
    signal_id: int,
    ticker: str,
    side: str,
    trade_date: str,
    requested_qty: int,
    approved_qty: int,
    order_price: Optional[float],
    note: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM sim_orders WHERE signal_id = ? AND order_date = ?",
        (signal_id, trade_date),
    ).fetchone()
    payload = (
        ticker,
        side,
        trade_date,
        "PENDING",
        requested_qty,
        approved_qty,
        order_price,
        note,
        now_ts(),
        now_ts(),
        signal_id,
        trade_date,
    )
    if existing:
        conn.execute(
            """
            UPDATE sim_orders
            SET ticker = ?, side = ?, order_date = ?, status = ?, requested_qty = ?,
                approved_qty = ?, order_price = ?, note = ?, updated_at = ?
            WHERE signal_id = ? AND order_date = ?
            """,
            (
                ticker,
                side,
                trade_date,
                "PENDING",
                requested_qty,
                approved_qty,
                order_price,
                note,
                now_ts(),
                signal_id,
                trade_date,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO sim_orders (
                ticker, side, order_date, status, requested_qty, approved_qty,
                order_price, note, created_at, updated_at, signal_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                side,
                trade_date,
                "PENDING",
                requested_qty,
                approved_qty,
                order_price,
                note,
                now_ts(),
                now_ts(),
                signal_id,
            ),
        )


def _mark_order(
    conn: sqlite3.Connection,
    signal_id: int,
    trade_date: str,
    status: str,
    fill_qty: int,
    fill_price: Optional[float],
    fees: float,
    taxes: float,
    realized_pnl: float,
    note: str,
) -> None:
    conn.execute(
        """
        UPDATE sim_orders
        SET status = ?, fill_qty = ?, fill_price = ?, fees = ?, taxes = ?,
            realized_pnl = ?, note = ?, updated_at = ?
        WHERE signal_id = ? AND order_date = ?
        """,
        (
            status,
            fill_qty,
            fill_price,
            fees,
            taxes,
            realized_pnl,
            note,
            now_ts(),
            signal_id,
            trade_date,
        ),
    )


def _update_order_approved_qty(conn: sqlite3.Connection, signal_id: int, trade_date: str, approved_qty: int) -> None:
    conn.execute(
        """
        UPDATE sim_orders
        SET approved_qty = ?, updated_at = ?
        WHERE signal_id = ? AND order_date = ?
        """,
        (int(approved_qty), now_ts(), signal_id, trade_date),
    )


def _update_signal_status(conn: sqlite3.Connection, signal_id: int, status: str) -> None:
    conn.execute(
        "UPDATE signals SET status = ? WHERE id = ?",
        (status, signal_id),
    )


def _record_snapshot(conn: sqlite3.Connection, trade_date: str, cash: float, note: str) -> None:
    state = compute_account_state(conn)
    prev = latest_snapshot(conn)
    market_value = float(state["market_value"])
    equity = cash + market_value
    daily_pnl = 0.0
    if prev:
        daily_pnl = round(equity - float(prev["equity"]), 4)
    peak_equity = max(max_historical_equity(conn), equity)
    drawdown = 0.0 if peak_equity <= 0 else round(max(0.0, (peak_equity - equity) / peak_equity), 6)

    existing = conn.execute(
        "SELECT id FROM account_snapshots WHERE snapshot_date = ?",
        (trade_date,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE account_snapshots
            SET cash = ?, equity = ?, market_value = ?, daily_pnl = ?, drawdown = ?,
                note = ?, created_at = ?
            WHERE snapshot_date = ?
            """,
            (
                round(float(cash), 4),
                round(equity, 4),
                round(market_value, 4),
                daily_pnl,
                drawdown,
                note,
                now_ts(),
                trade_date,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO account_snapshots (
                snapshot_date, cash, equity, market_value, daily_pnl, drawdown, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                round(float(cash), 4),
                round(equity, 4),
                round(market_value, 4),
                daily_pnl,
                drawdown,
                note,
                now_ts(),
            ),
        )


def _limit_band(previous_close: Optional[float], market: str, ticker: str) -> Optional[tuple[float, float]]:
    if previous_close is None or previous_close <= 0:
        return None
    pct = 0.10
    if str(ticker).startswith(("300", "301", "688")):
        pct = 0.20
    upper = round(previous_close * (1.0 + pct), 3)
    lower = round(previous_close * (1.0 - pct), 3)
    return lower, upper


def _bar_locked_limit_up(bar: PriceBar, previous_close: Optional[float], market: str, ticker: str) -> bool:
    band = _limit_band(previous_close, market, ticker)
    if not band:
        return False
    _, upper = band
    return (
        abs(bar.open_price - upper) <= 0.011
        and abs(bar.high_price - upper) <= 0.011
        and abs(bar.low_price - upper) <= 0.011
    )


def _bar_locked_limit_down(bar: PriceBar, previous_close: Optional[float], market: str, ticker: str) -> bool:
    band = _limit_band(previous_close, market, ticker)
    if not band:
        return False
    lower, _ = band
    return (
        abs(bar.open_price - lower) <= 0.011
        and abs(bar.high_price - lower) <= 0.011
        and abs(bar.low_price - lower) <= 0.011
    )


def _mark_positions_to_market(conn: sqlite3.Connection, bar_store: ResultBarStore, trade_date: str) -> None:
    rows = conn.execute("SELECT * FROM positions ORDER BY ticker").fetchall()
    for row in rows:
        ticker = str(row["ticker"])
        latest_bar = bar_store.latest_bar_on_or_before(ticker, trade_date)
        if latest_bar is None:
            continue
        quantity = int(row["quantity"])
        avg_cost = float(row["avg_cost"])
        last_price = latest_bar.close_price
        market_value = round(quantity * last_price, 4)
        unrealized_pnl = round((last_price - avg_cost) * quantity, 4)
        conn.execute(
            """
            UPDATE positions
            SET last_price = ?, market_value = ?, unrealized_pnl = ?, updated_at = ?
            WHERE ticker = ?
            """,
            (last_price, market_value, unrealized_pnl, now_ts(), ticker),
        )


def _candidate_fill_bar(
    bar_store: ResultBarStore,
    ticker: str,
    signal_date: str,
    run_trade_date: str,
) -> Optional[PriceBar]:
    bar = bar_store.get_next_bar(ticker, signal_date)
    if bar is None or bar.trade_date > run_trade_date:
        return None
    return bar


def _fill_buy_order(
    row: sqlite3.Row,
    bar: PriceBar,
    previous_close: Optional[float],
) -> tuple[str, Optional[float], str]:
    market = str(row["market"])
    ticker = str(row["ticker"])
    entry_min = float(row["entry_price_min"]) if row["entry_price_min"] is not None else None
    entry_max = float(row["entry_price_max"]) if row["entry_price_max"] is not None else None
    if entry_max is None or entry_max <= 0:
        return "REJECTED", None, "缺少有效买入限价。"
    if bar.volume <= 0:
        return "NOT_FILLED", None, "下一交易日无成交量，按停牌处理。"
    if _bar_locked_limit_up(bar, previous_close, market, ticker):
        return "NOT_FILLED", None, "下一交易日一字涨停，无法买入。"
    if bar.open_price <= entry_max + EPSILON:
        note = "次日开盘直接进入买入价位。"
        if entry_min is not None and bar.open_price < entry_min - EPSILON:
            note = "次日低开到理想区间下方，按开盘价成交。"
        return "FILLED", round(bar.open_price, 3), note
    if bar.low_price <= entry_max + EPSILON:
        return "FILLED", round(entry_max, 3), "盘中回落触发限价买入。"
    return "NOT_FILLED", None, "下一交易日未回落到买入区间。"


def _fill_sell_order(
    row: sqlite3.Row,
    bar: PriceBar,
    previous_close: Optional[float],
) -> tuple[str, Optional[float], str]:
    market = str(row["market"])
    ticker = str(row["ticker"])
    if bar.volume <= 0:
        return "NOT_FILLED", None, "下一交易日无成交量，按停牌处理。"
    if _bar_locked_limit_down(bar, previous_close, market, ticker):
        return "NOT_FILLED", None, "下一交易日一字跌停，无法卖出。"
    return "FILLED", round(bar.open_price, 3), "次日开盘按市价卖出。"


def run_paper_execution(
    conn: sqlite3.Connection,
    trade_date: str,
    config: Optional[AppConfig] = None,
) -> List[str]:
    _prepare_trade_date(conn, trade_date)
    snapshot = latest_snapshot(conn)
    cash = float(snapshot["cash"]) if snapshot else 0.0
    cfg = config or load_config()
    bar_store = ResultBarStore(cfg.tradeforagents_results_dir)
    events = []

    rows = conn.execute(
        """
        SELECT *
        FROM signals
        WHERE signal_date <= ?
          AND risk_state IN ('ALLOW', 'REDUCE_POSITION')
          AND status IN ('PLANNED', 'WAIT_MARKET')
        ORDER BY id
        """,
        (trade_date,),
    ).fetchall()

    for row in rows:
        signal_id = int(row["id"])
        ticker = str(row["ticker"])
        market = str(row["market"])
        action = str(row["action"])
        approved_qty = int(row["approved_qty"])
        signal_date = str(row["signal_date"])

        if action == "hold":
            _update_signal_status(conn, signal_id, "NO_ACTION")
            events.append("{0}: hold".format(ticker))
            continue

        _ensure_order_row(
            conn,
            signal_id,
            ticker,
            "BUY" if action == "buy" else "SELL",
            signal_date,
            approved_qty,
            approved_qty,
            midpoint(row["entry_price_min"], row["entry_price_max"]),
            "等待下一交易日行情撮合。",
        )

        if approved_qty <= 0:
            _mark_order(conn, signal_id, signal_date, "REJECTED", 0, None, 0.0, 0.0, 0.0, "Approved quantity is zero.")
            _update_signal_status(conn, signal_id, "ORDER_REJECTED")
            events.append("{0}: rejected".format(ticker))
            continue

        fill_bar = _candidate_fill_bar(bar_store, ticker, signal_date, trade_date)
        if fill_bar is None:
            _mark_order(conn, signal_id, signal_date, "WAIT_MARKET", 0, None, 0.0, 0.0, 0.0, "尚未拿到下一交易日行情，继续等待。")
            _update_signal_status(conn, signal_id, "WAIT_MARKET")
            events.append("{0}: waiting next bar".format(ticker))
            continue

        previous_bar = bar_store.get_previous_bar(ticker, fill_bar.trade_date)
        previous_close = float(previous_bar.close_price) if previous_bar else None

        if action == "buy":
            order_status, fill_price, note = _fill_buy_order(row, fill_bar, previous_close)
        else:
            order_status, fill_price, note = _fill_sell_order(row, fill_bar, previous_close)

        if order_status == "REJECTED" or fill_price is None or fill_price <= 0:
            _mark_order(conn, signal_id, signal_date, order_status, 0, fill_price, 0.0, 0.0, 0.0, note)
            _update_signal_status(conn, signal_id, "ORDER_REJECTED" if order_status == "REJECTED" else "ORDER_NOT_FILLED")
            events.append("{0}: {1}".format(ticker, "rejected" if order_status == "REJECTED" else "not filled"))
            continue

        if order_status != "FILLED":
            _mark_order(conn, signal_id, signal_date, order_status, 0, None, 0.0, 0.0, 0.0, note)
            _update_signal_status(conn, signal_id, "ORDER_NOT_FILLED")
            events.append("{0}: not filled".format(ticker))
            continue

        turnover = round(fill_price * approved_qty, 4)

        if action == "buy":
            fees = _calc_buy_cost(turnover)
            total_cost = turnover + fees
            while approved_qty > 0 and total_cost > cash:
                approved_qty -= 100
                turnover = round(fill_price * approved_qty, 4)
                fees = _calc_buy_cost(turnover) if approved_qty > 0 else 0.0
                total_cost = turnover + fees

            if approved_qty <= 0:
                _mark_order(conn, signal_id, signal_date, "REJECTED", 0, fill_price, 0.0, 0.0, 0.0, "账户现金不足，无法完成买入。")
                _update_signal_status(conn, signal_id, "ORDER_REJECTED")
                events.append("{0}: cash reject".format(ticker))
                continue
            _update_order_approved_qty(conn, signal_id, signal_date, approved_qty)

            cash = round(cash - total_cost, 4)
            position = conn.execute(
                "SELECT * FROM positions WHERE ticker = ?",
                (ticker,),
            ).fetchone()
            if position:
                new_qty = int(position["quantity"]) + approved_qty
                old_cost = float(position["avg_cost"]) * int(position["quantity"])
                avg_cost = round((old_cost + total_cost) / new_qty, 4)
                can_sell_qty = int(position["can_sell_qty"])
                pending_sellable_qty = int(position["pending_sellable_qty"]) + approved_qty
            else:
                new_qty = approved_qty
                avg_cost = round(total_cost / approved_qty, 4)
                can_sell_qty = 0
                pending_sellable_qty = approved_qty

            _upsert_position(
                conn,
                ticker,
                market,
                new_qty,
                can_sell_qty,
                pending_sellable_qty,
                avg_cost,
                fill_bar.close_price,
            )
            _mark_order(
                conn,
                signal_id,
                signal_date,
                "FILLED",
                approved_qty,
                fill_price,
                fees,
                0.0,
                0.0,
                "{0} 成交日：{1}".format(note, fill_bar.trade_date),
            )
            _update_signal_status(conn, signal_id, "EXECUTED")
            events.append("{0}: bought {1} on {2}".format(ticker, approved_qty, fill_bar.trade_date))
            continue

        position = conn.execute(
            "SELECT * FROM positions WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        if not position or int(position["can_sell_qty"]) <= 0:
            _mark_order(conn, signal_id, signal_date, "REJECTED", 0, fill_price, 0.0, 0.0, 0.0, "T+1 下无可卖数量。")
            _update_signal_status(conn, signal_id, "ORDER_REJECTED")
            events.append("{0}: sell reject".format(ticker))
            continue

        sell_qty = min(approved_qty, int(position["can_sell_qty"]))
        if sell_qty <= 0:
            _mark_order(conn, signal_id, signal_date, "REJECTED", 0, fill_price, 0.0, 0.0, 0.0, "卖出数量被缩减为 0。")
            _update_signal_status(conn, signal_id, "ORDER_REJECTED")
            events.append("{0}: zero sell".format(ticker))
            continue

        turnover = round(fill_price * sell_qty, 4)
        taxes = round(turnover * STAMP_DUTY_RATE, 4)
        fees = round(_commission(turnover) + _transfer_fee(turnover), 4)
        net_cash = round(turnover - fees - taxes, 4)
        cash = round(cash + net_cash, 4)
        avg_cost = float(position["avg_cost"])
        realized_pnl = round((fill_price - avg_cost) * sell_qty - fees - taxes, 4)
        remain_qty = int(position["quantity"]) - sell_qty
        remain_sell_qty = int(position["can_sell_qty"]) - sell_qty

        if remain_qty <= 0:
            _delete_position(conn, ticker)
        else:
            _upsert_position(
                conn,
                ticker,
                market,
                remain_qty,
                max(0, remain_sell_qty),
                int(position["pending_sellable_qty"]),
                avg_cost,
                fill_bar.close_price,
            )

        _mark_order(
            conn,
            signal_id,
            signal_date,
            "FILLED",
            sell_qty,
            fill_price,
            fees,
            taxes,
            realized_pnl,
            "{0} 成交日：{1}".format(note, fill_bar.trade_date),
        )
        _update_signal_status(conn, signal_id, "EXECUTED")
        events.append("{0}: sold {1} on {2}".format(ticker, sell_qty, fill_bar.trade_date))

    _mark_positions_to_market(conn, bar_store, trade_date)
    _record_snapshot(conn, trade_date, cash, "Paper execution run with next-bar A-share fills.")
    conn.commit()
    return events
