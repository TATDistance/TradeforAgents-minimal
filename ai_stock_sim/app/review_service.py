from __future__ import annotations

import json
from pathlib import Path

from .db import fetch_recent_rows
from .models import ReviewReport


class ReviewService:
    def build_report(self, conn, trade_date: str) -> ReviewReport:
        orders = fetch_recent_rows(conn, "orders", limit=500)
        account_rows = fetch_recent_rows(conn, "account_snapshots", limit=500)
        filled = [row for row in orders if str(row["status"]).endswith("FILLED")]
        wins = []
        losses = []
        for row in filled:
            if str(row["side"]) != "SELL":
                continue
            pnl = -float(row["fee"]) - float(row["tax"])
            if pnl >= 0:
                wins.append(pnl)
            else:
                losses.append(abs(pnl))
        win_rate = len(wins) / max(len(wins) + len(losses), 1)
        avg_win = sum(wins) / max(len(wins), 1)
        avg_loss = sum(losses) / max(len(losses), 1)
        profit_factor = sum(wins) / max(sum(losses), 1e-6)
        latest_equity = float(account_rows[0]["equity"]) if account_rows else 0.0
        max_drawdown = max((float(row["drawdown"]) for row in account_rows), default=0.0)
        summary = "今日无成交" if not filled else f"今日共 {len(filled)} 笔模拟成交。"
        return ReviewReport(
            trade_date=trade_date,
            total_trades=len(filled),
            win_rate=round(win_rate, 4),
            avg_win=round(avg_win, 4),
            avg_loss=round(avg_loss, 4),
            profit_factor=round(profit_factor, 4),
            max_drawdown=round(max_drawdown, 4),
            ending_equity=round(latest_equity, 4),
            summary=summary,
        )

    def save_report(self, report: ReviewReport, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"review_{report.trade_date}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path
