from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from .db import fetch_latest_account, fetch_positions, fetch_rows_by_sql, max_equity
from .models import AccountSnapshot, PositionRecord
from .risk_engine import PortfolioState


def _calc_today_open_ratio(conn, equity: float) -> float:
    if equity <= 0:
        return 0.0
    today = datetime.now().date().isoformat()
    rows = fetch_rows_by_sql(
        conn,
        """
        SELECT price, qty
        FROM orders
        WHERE intent_only = 0
          AND side = 'BUY'
          AND status IN ('FILLED', 'PARTIAL_FILLED')
          AND date(ts) = ?
        """,
        (today,),
    )
    opened_value = sum(float(row["price"] or 0.0) * int(row["qty"] or 0) for row in rows)
    return max(0.0, opened_value / max(equity, 1.0))


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
        today_open_ratio=_calc_today_open_ratio(conn, float(account["equity"] or 0.0)),
    )


def build_portfolio_feedback(conn, settings) -> Dict[str, object]:
    portfolio = build_portfolio_state(conn)
    positions = fetch_positions(conn)
    positions_detail: List[Dict[str, object]] = []
    for row in positions:
        qty = int(row["qty"])
        avg_cost = float(row["avg_cost"])
        last_price = float(row["last_price"])
        unrealized_pct = 0.0 if avg_cost <= 0 else (last_price - avg_cost) / avg_cost
        updated_at = str(row["updated_at"])
        hold_days = 0
        try:
            hold_days = max(0, (datetime.now() - datetime.fromisoformat(updated_at)).days)
        except Exception:
            hold_days = 0
        positions_detail.append(
            {
                "symbol": str(row["symbol"]),
                "qty": qty,
                "avg_cost": avg_cost,
                "last_price": last_price,
                "market_value": float(row["market_value"]),
                "unrealized_pnl": float(row["unrealized_pnl"]),
                "unrealized_pct": unrealized_pct,
                "can_sell_qty": int(row["can_sell_qty"]),
                "hold_days": hold_days,
            }
        )

    eval_rows = [
        dict(row)
        for row in fetch_rows_by_sql(
            conn,
            """
            SELECT strategy_name, score_total
            FROM strategy_evaluations
            WHERE period_type = ?
            ORDER BY ts DESC
            """,
            (f"rolling_trade_{settings.evaluation.rolling_trade_windows[0]}",),
        )
    ]
    strategy_scores: Dict[str, float] = {}
    for row in eval_rows:
        strategy_name = str(row["strategy_name"])
        if strategy_name in {"portfolio_actual"} or strategy_name.startswith("exit::") or strategy_name in strategy_scores:
            continue
        strategy_scores[strategy_name] = float(row["score_total"] or 0.0)

    position_value = sum(float(item["market_value"]) for item in positions_detail)
    total_position_pct = 0.0 if portfolio.equity <= 0 else position_value / max(portfolio.equity, 1.0)
    cash_pct = 0.0 if portfolio.equity <= 0 else portfolio.cash / max(portfolio.equity, 1.0)
    risk_mode = "NORMAL"
    if portfolio.drawdown >= settings.portfolio_feedback.drawdown_risk_off_threshold:
        risk_mode = "RISK_OFF"
    elif (
        portfolio.drawdown >= settings.portfolio_feedback.drawdown_defensive_threshold
        or total_position_pct >= settings.portfolio_feedback.high_position_threshold
    ):
        risk_mode = "DEFENSIVE"
    return {
        "cash": portfolio.cash,
        "equity": portfolio.equity,
        "market_value": portfolio.market_value,
        "drawdown": portfolio.drawdown,
        "cash_pct": cash_pct,
        "total_position_pct": total_position_pct,
        "today_open_ratio": portfolio.today_open_ratio,
        "risk_mode": risk_mode,
        "positions_detail": positions_detail,
        "strategy_scores": strategy_scores,
    }


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
