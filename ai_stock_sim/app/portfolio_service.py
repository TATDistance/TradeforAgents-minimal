from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from .db import fetch_latest_account, fetch_positions, max_equity
from .models import AccountSnapshot, PositionRecord
from .risk_engine import PortfolioState


def build_portfolio_state(conn) -> PortfolioState:
    account = fetch_latest_account(conn)
    positions = fetch_positions(conn)
    position_map: Dict[str, Dict[str, float]] = {}
    for row in positions:
        position_map[str(row["symbol"])] = {
            "qty": float(row["qty"]),
            "avg_cost": float(row["avg_cost"]),
            "last_price": float(row["last_price"]),
            "market_value": float(row["market_value"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "can_sell_qty": float(row["can_sell_qty"]),
        }
    return PortfolioState(
        cash=account["cash"],
        equity=account["equity"],
        market_value=account["market_value"],
        realized_pnl=account["realized_pnl"],
        unrealized_pnl=account["unrealized_pnl"],
        drawdown=account["drawdown"],
        current_positions=position_map,
        today_open_ratio=0.0 if account["equity"] <= 0 else account["market_value"] / max(account["equity"], 1.0),
    )


def mark_to_market(conn, latest_quotes: Dict[str, float]) -> AccountSnapshot:
    positions = fetch_positions(conn)
    total_value = 0.0
    total_unrealized = 0.0
    for row in positions:
        latest = latest_quotes.get(str(row["symbol"]), float(row["last_price"]))
        market_value = latest * int(row["qty"])
        unrealized = (latest - float(row["avg_cost"])) * int(row["qty"])
        conn.execute(
            """
            UPDATE positions
            SET last_price = ?, market_value = ?, unrealized_pnl = ?, updated_at = ?
            WHERE symbol = ?
            """,
            (latest, market_value, unrealized, datetime.now().isoformat(timespec="seconds"), row["symbol"]),
        )
        total_value += market_value
        total_unrealized += unrealized
    account = fetch_latest_account(conn)
    equity = account["cash"] + total_value
    peak = max(max_equity(conn), equity)
    drawdown = 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak)
    return AccountSnapshot(
        cash=account["cash"],
        equity=equity,
        market_value=total_value,
        realized_pnl=account["realized_pnl"],
        unrealized_pnl=total_unrealized,
        drawdown=drawdown,
    )
