from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .db import compute_account_state, now_ts
from .market_data import midpoint


MAX_SINGLE_POSITION_PCT = 0.20
MAX_DAILY_NEW_POSITION_PCT = 0.40
MAX_TRADE_RISK_PCT = 0.02
DEFAULT_STOP_BUFFER_PCT = 0.05
BOARD_LOT = 100


@dataclass
class RiskDecision:
    signal_id: int
    ticker: str
    risk_state: str
    approved_qty: int
    notes: str


def floor_board_lot(quantity: int) -> int:
    if quantity <= 0:
        return 0
    return int(quantity / BOARD_LOT) * BOARD_LOT


def _entry_price(row: sqlite3.Row) -> Optional[float]:
    return midpoint(row["entry_price_min"], row["entry_price_max"])


def _approved_buy_value_for_date(conn: sqlite3.Connection, signal_date: str) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(approved_qty * COALESCE((entry_price_min + entry_price_max) / 2.0, entry_price_min, entry_price_max, 0)), 0) AS total
        FROM signals
        WHERE signal_date = ?
          AND action = 'buy'
          AND risk_state IN ('ALLOW', 'REDUCE_POSITION')
        """,
        (signal_date,),
    ).fetchone()
    return float(row["total"]) if row else 0.0


def _position_for_ticker(conn: sqlite3.Connection, ticker: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM positions WHERE ticker = ?",
        (ticker,),
    ).fetchone()


def _update_signal_risk(
    conn: sqlite3.Connection,
    signal_id: int,
    risk_state: str,
    approved_qty: int,
    notes: str,
) -> None:
    status = "PLANNED" if risk_state in ("ALLOW", "REDUCE_POSITION") else "BLOCKED"
    conn.execute(
        """
        UPDATE signals
        SET risk_state = ?, approved_qty = ?, risk_notes = ?, status = ?
        WHERE id = ?
        """,
        (risk_state, int(approved_qty), notes, status, int(signal_id)),
    )


def evaluate_pending_signals(conn: sqlite3.Connection) -> List[RiskDecision]:
    rows = conn.execute(
        """
        SELECT *
        FROM signals
        WHERE risk_state IS NULL
        ORDER BY signal_date, id
        """
    ).fetchall()

    account = compute_account_state(conn)
    equity = float(account["equity"])
    decisions = []

    for row in rows:
        signal_id = int(row["id"])
        ticker = str(row["ticker"])
        action = str(row["action"])
        entry_price = _entry_price(row)

        if action == "hold":
            decision = RiskDecision(signal_id, ticker, "ALLOW", 0, "Hold signal kept for manual review.")
            _update_signal_risk(conn, signal_id, decision.risk_state, decision.approved_qty, decision.notes)
            decisions.append(decision)
            continue

        if action == "sell":
            position = _position_for_ticker(conn, ticker)
            if not position or int(position["can_sell_qty"]) <= 0:
                decision = RiskDecision(signal_id, ticker, "REJECT", 0, "No sellable quantity available under T+1.")
            else:
                qty = floor_board_lot(int(position["can_sell_qty"]))
                if qty <= 0 and int(position["can_sell_qty"]) > 0:
                    qty = int(position["can_sell_qty"])
                decision = RiskDecision(signal_id, ticker, "ALLOW", qty, "Sellable quantity approved.")
            _update_signal_risk(conn, signal_id, decision.risk_state, decision.approved_qty, decision.notes)
            decisions.append(decision)
            continue

        if entry_price is None or entry_price <= 0:
            decision = RiskDecision(signal_id, ticker, "REJECT", 0, "Missing entry price range.")
            _update_signal_risk(conn, signal_id, decision.risk_state, decision.approved_qty, decision.notes)
            decisions.append(decision)
            continue

        position = _position_for_ticker(conn, ticker)
        current_position_value = float(position["market_value"]) if position else 0.0
        daily_used_value = _approved_buy_value_for_date(conn, str(row["signal_date"]))
        target_value = equity * float(row["position_pct"])
        position_cap_value = max(0.0, equity * MAX_SINGLE_POSITION_PCT - current_position_value)
        daily_cap_value = max(0.0, equity * MAX_DAILY_NEW_POSITION_PCT - daily_used_value)
        allowed_value = min(target_value, position_cap_value, daily_cap_value)

        if allowed_value <= 0:
            decision = RiskDecision(signal_id, ticker, "REJECT", 0, "Exposure cap reached.")
            _update_signal_risk(conn, signal_id, decision.risk_state, decision.approved_qty, decision.notes)
            decisions.append(decision)
            continue

        desired_qty = floor_board_lot(int(target_value / entry_price))
        qty_by_cap = floor_board_lot(int(allowed_value / entry_price))
        stop_loss = row["stop_loss"]
        stop_price = float(stop_loss) if stop_loss is not None else entry_price * (1.0 - DEFAULT_STOP_BUFFER_PCT)
        risk_per_share = max(0.01, entry_price - stop_price)
        qty_by_risk = floor_board_lot(int((equity * MAX_TRADE_RISK_PCT) / risk_per_share))
        approved_qty = min(desired_qty, qty_by_cap, qty_by_risk)

        if approved_qty <= 0:
            decision = RiskDecision(signal_id, ticker, "REJECT", 0, "Position size falls below one board lot.")
        else:
            reduced = approved_qty < desired_qty
            note_bits = []
            if reduced and approved_qty == qty_by_cap:
                note_bits.append("Reduced by exposure cap.")
            if reduced and approved_qty == qty_by_risk:
                note_bits.append("Reduced by stop-loss risk cap.")
            if not note_bits:
                note_bits.append("Signal passed A-share lot and exposure checks.")
            decision = RiskDecision(
                signal_id,
                ticker,
                "REDUCE_POSITION" if reduced else "ALLOW",
                approved_qty,
                " ".join(note_bits),
            )

        _update_signal_risk(conn, signal_id, decision.risk_state, decision.approved_qty, decision.notes)
        decisions.append(decision)

    conn.commit()
    return decisions
