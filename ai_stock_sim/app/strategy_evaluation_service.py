from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Mapping

from .db import fetch_rows_by_sql
from .evaluation_service import EvaluationService
from .metrics_service import calc_max_drawdown
from .settings import Settings, load_settings


class StrategyEvaluationService:
    def __init__(self, settings: Settings | None = None, evaluation_service: EvaluationService | None = None) -> None:
        self.settings = settings or load_settings()
        self.evaluation_service = evaluation_service or EvaluationService(self.settings)

    def evaluate_strategy_performance(self, conn, window_days: int = 5) -> Dict[str, Dict[str, float | int | str]]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=max(window_days - 1, 0))
        strategy_names = self._strategy_names(conn, start_date, end_date)
        summary: Dict[str, Dict[str, float | int | str]] = {}
        for strategy_name in strategy_names:
            closed = self.evaluation_service._load_closed_trades(  # noqa: SLF001 - shared evaluation primitive
                conn,
                strategy_name=strategy_name,
                start_date=start_date,
                end_date=end_date,
                attribution="entry",
            )
            returns = [float(item.return_pct) for item in closed]
            pnls = [float(item.pnl) for item in closed]
            wins = [value for value in returns if value > 0]
            avg_return = sum(returns) / len(returns) if returns else 0.0
            win_rate = len(wins) / len(returns) if returns else 0.0
            drawdown = calc_max_drawdown(self.evaluation_service._equity_curve_from_returns(returns)).value if returns else 0.0  # noqa: SLF001
            daily_evaluations = self._load_daily_evaluations(conn, strategy_name, start_date, end_date)
            grouped_regime = self._group_by_regime(daily_evaluations)
            summary[strategy_name] = {
                "strategy_name": strategy_name,
                "window_days": window_days,
                "trades": len(closed),
                "win_rate": round(win_rate, 6),
                "avg_return": round(avg_return, 6),
                "max_drawdown": round(drawdown, 6),
                "avg_pnl": round(sum(pnls) / len(pnls), 6) if pnls else 0.0,
                "score_total": round(self._latest_score(daily_evaluations), 2),
                "regime_breakdown": grouped_regime,
            }
        return summary

    @staticmethod
    def _strategy_names(conn, start_date: date, end_date: date) -> list[str]:
        rows = fetch_rows_by_sql(
            conn,
            """
            SELECT DISTINCT strategy_name
            FROM strategy_evaluations
            WHERE strategy_name NOT IN ('portfolio_actual')
              AND strategy_name NOT LIKE 'exit::%'
              AND period_type = 'daily'
              AND date(ts) >= ?
              AND date(ts) <= ?
            ORDER BY strategy_name
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        return [str(row["strategy_name"]) for row in rows]

    @staticmethod
    def _load_daily_evaluations(conn, strategy_name: str, start_date: date, end_date: date) -> list[Mapping[str, object]]:
        return [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT *
                FROM strategy_evaluations
                WHERE strategy_name = ?
                  AND period_type = 'daily'
                  AND date(ts) >= ?
                  AND date(ts) <= ?
                ORDER BY ts ASC, id ASC
                """,
                (strategy_name, start_date.isoformat(), end_date.isoformat()),
            )
        ]

    @staticmethod
    def _latest_score(rows: list[Mapping[str, object]]) -> float:
        if not rows:
            return 0.0
        return float(rows[-1].get("score_total") or 0.0)

    @staticmethod
    def _group_by_regime(rows: list[Mapping[str, object]]) -> Dict[str, Dict[str, float | int]]:
        grouped: Dict[str, Dict[str, float | int]] = defaultdict(lambda: {"days": 0, "avg_return": 0.0, "avg_score": 0.0})
        for row in rows:
            metadata = {}
            try:
                metadata = json.loads(str(row.get("metadata_json") or "{}"))
            except Exception:
                metadata = {}
            runtime = metadata.get("runtime_event_metrics") or {}
            regime_name = str(runtime.get("market_regime") or metadata.get("market_regime") or "UNKNOWN")
            item = grouped[regime_name]
            item["days"] = int(item["days"]) + 1
            item["avg_return"] = float(item["avg_return"]) + float(row.get("total_return") or 0.0)
            item["avg_score"] = float(item["avg_score"]) + float(row.get("score_total") or 0.0)
        normalized: Dict[str, Dict[str, float | int]] = {}
        for regime_name, item in grouped.items():
            days = max(int(item["days"]), 1)
            normalized[regime_name] = {
                "days": days,
                "avg_return": round(float(item["avg_return"]) / days, 6),
                "avg_score": round(float(item["avg_score"]) / days, 4),
            }
        return normalized
