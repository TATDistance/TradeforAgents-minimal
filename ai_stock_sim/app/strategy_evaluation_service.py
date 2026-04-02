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
            if closed:
                returns = [float(item.return_pct) for item in closed]
                pnls = [float(item.pnl) for item in closed]
                trades = len(closed)
            else:
                derived = self._derive_snapshot_trades(conn, strategy_name, start_date, end_date)
                returns = [float(item["return_pct"]) for item in derived]
                pnls = [float(item["pnl"]) for item in derived]
                trades = len(derived)
            wins = [value for value in returns if value > 0]
            avg_return = sum(returns) / len(returns) if returns else 0.0
            win_rate = len(wins) / len(returns) if returns else 0.0
            drawdown = calc_max_drawdown(self.evaluation_service._equity_curve_from_returns(returns)).value if returns else 0.0  # noqa: SLF001
            daily_evaluations = self._load_daily_evaluations(conn, strategy_name, start_date, end_date)
            grouped_regime = self._group_by_regime(daily_evaluations)
            summary[strategy_name] = {
                "strategy_name": strategy_name,
                "window_days": window_days,
                "trades": trades,
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
        names: list[str] = []
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
        names.extend(str(row["strategy_name"]) for row in rows)
        if not names:
            from .strategy_engine import STRATEGY_REGISTRY

            names.extend(sorted(STRATEGY_REGISTRY.keys()))
        return sorted(dict.fromkeys(name for name in names if name))

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

    @staticmethod
    def _dominant_long_strategy(feature_payload: object) -> str:
        try:
            feature_map = dict(feature_payload or {})
        except Exception:
            return ""
        best_name = ""
        best_score = 0.0
        for strategy_name, raw in feature_map.items():
            if not isinstance(raw, Mapping):
                continue
            score = float(raw.get("score") or 0.0)
            direction = str(raw.get("direction") or "NEUTRAL").upper()
            if direction != "LONG" or score <= best_score:
                continue
            best_name = str(strategy_name)
            best_score = score
        return best_name

    def _derive_snapshot_trades(
        self,
        conn,
        strategy_name: str,
        start_date: date,
        end_date: date,
    ) -> list[Dict[str, float]]:
        buy_orders = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT id, ts, symbol, price, qty, fee, tax, slippage
                FROM orders
                WHERE side = 'BUY'
                  AND intent_only = 0
                  AND status IN ('FILLED', 'PARTIAL_FILLED')
                  AND date(ts) >= ?
                  AND date(ts) <= ?
                ORDER BY ts ASC, id ASC
                """,
                (start_date.isoformat(), end_date.isoformat()),
            )
        ]
        derived: list[Dict[str, float]] = []
        for entry_order in buy_orders:
            symbol = str(entry_order.get("symbol") or "")
            if not symbol:
                continue
            ts = str(entry_order.get("ts") or "")
            snapshot_rows = [
                dict(row)
                for row in fetch_rows_by_sql(
                    conn,
                    """
                    SELECT feature_json
                    FROM decision_snapshots
                    WHERE symbol = ?
                      AND action IN ('BUY', 'PREPARE_BUY')
                      AND datetime(ts) >= datetime(?)
                      AND datetime(ts) <= datetime(?)
                    ORDER BY ABS(strftime('%s', ts) - strftime('%s', ?)) ASC, id DESC
                    LIMIT 1
                    """,
                    (
                        symbol,
                        (datetime.fromisoformat(ts) - timedelta(minutes=30)).isoformat(timespec="seconds"),
                        (datetime.fromisoformat(ts) + timedelta(minutes=10)).isoformat(timespec="seconds"),
                        ts,
                    ),
                )
            ]
            if not snapshot_rows:
                continue
            try:
                feature_payload = json.loads(str(snapshot_rows[0].get("feature_json") or "{}"))
            except Exception:
                feature_payload = {}
            if self._dominant_long_strategy(feature_payload) != strategy_name:
                continue
            entry_price = float(entry_order.get("price") or 0.0)
            qty = int(entry_order.get("qty") or 0)
            if entry_price <= 0 or qty <= 0:
                continue
            exit_rows = [
                dict(row)
                for row in fetch_rows_by_sql(
                    conn,
                    """
                    SELECT price, qty, fee, tax, slippage
                    FROM orders
                    WHERE symbol = ?
                      AND side = 'SELL'
                      AND intent_only = 0
                      AND status IN ('FILLED', 'PARTIAL_FILLED')
                      AND datetime(ts) >= datetime(?)
                    ORDER BY ts ASC, id ASC
                    LIMIT 1
                    """,
                    (symbol, str(entry_order.get("ts") or ts)),
                )
            ]
            if exit_rows:
                exit_row = exit_rows[0]
                exit_qty = max(1, min(qty, int(exit_row.get("qty") or qty)))
                exit_price = float(exit_row.get("price") or 0.0)
                pnl = (
                    (exit_price - entry_price) * exit_qty
                    - float(entry_order.get("fee") or 0.0)
                    - float(entry_order.get("tax") or 0.0)
                    - float(entry_order.get("slippage") or 0.0)
                    - float(exit_row.get("fee") or 0.0)
                    - float(exit_row.get("tax") or 0.0)
                    - float(exit_row.get("slippage") or 0.0)
                )
                return_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            else:
                position_rows = [
                    dict(row)
                    for row in fetch_rows_by_sql(
                        conn,
                        "SELECT last_price, qty, unrealized_pnl FROM positions WHERE symbol = ?",
                        (symbol,),
                    )
                ]
                if not position_rows:
                    continue
                position = position_rows[0]
                last_price = float(position.get("last_price") or 0.0)
                open_qty = int(position.get("qty") or 0)
                if last_price <= 0 or open_qty <= 0:
                    continue
                tracked_qty = max(1, min(qty, open_qty))
                pnl = (last_price - entry_price) * tracked_qty
                return_pct = (last_price - entry_price) / entry_price if entry_price > 0 else 0.0
            derived.append(
                {
                    "return_pct": round(return_pct, 6),
                    "pnl": round(pnl, 6),
                }
            )
        return derived
