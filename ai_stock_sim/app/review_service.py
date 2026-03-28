from __future__ import annotations

import json
from pathlib import Path

from .db import fetch_recent_rows
from .evaluation_service import EvaluationService
from .models import ReviewReport
from .settings import Settings, load_settings


class ReviewService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.evaluation_service = EvaluationService(self.settings)

    def build_report(self, conn, trade_date: str) -> ReviewReport:
        orders = fetch_recent_rows(conn, "orders", limit=500)
        account_rows = fetch_recent_rows(conn, "account_snapshots", limit=500)
        evaluation = self.evaluation_service.compute_daily_metrics(conn, trade_date)
        filled = [row for row in orders if str(row["status"]).endswith("FILLED") and str(row["ts"]).startswith(trade_date)]
        latest_equity = float(account_rows[0]["equity"]) if account_rows else 0.0
        max_drawdown = max((float(row["drawdown"]) for row in account_rows), default=0.0)
        summary = (
            "今日无成交"
            if not filled
            else f"今日共 {len(filled)} 笔模拟成交，胜率 {evaluation.win_rate:.2%}，利润因子 {evaluation.profit_factor:.2f}。"
        )
        return ReviewReport(
            trade_date=trade_date,
            total_trades=len(filled),
            win_rate=round(evaluation.win_rate, 4),
            avg_win=round(float(json.loads(evaluation.metadata_json or "{}").get("avg_win", 0.0) or 0.0), 4),
            avg_loss=round(float(json.loads(evaluation.metadata_json or "{}").get("avg_loss", 0.0) or 0.0), 4),
            profit_factor=round(evaluation.profit_factor, 4),
            max_drawdown=round(max_drawdown, 4),
            ending_equity=round(latest_equity, 4),
            summary=summary,
        )

    def save_report(self, report: ReviewReport, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"review_{report.trade_date}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path
