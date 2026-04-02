from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, Mapping

from .db import fetch_rows_by_sql, write_decision_snapshot
from .models import DecisionSnapshot
from .settings import Settings, load_settings


class DecisionAttributionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    @staticmethod
    def _safe_json(payload: object) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)

    def record_decision_snapshot(
        self,
        conn,
        context: Mapping[str, object],
        action: Mapping[str, object],
        *,
        market_regime: str,
        style_profile: str,
    ) -> int:
        symbol = str(action.get("symbol") or context.get("symbol") or "").strip()
        if not symbol:
            return 0
        snapshot = DecisionSnapshot(
            symbol=symbol,
            decision_time=str(action.get("decision_time") or datetime.now().isoformat(timespec="seconds")),
            action=str(action.get("action") or "HOLD"),
            final_score=float(action.get("final_score") or action.get("execution_score") or 0.0),
            setup_score=float(action.get("setup_score") or 0.0),
            execution_score=float(action.get("execution_score") or 0.0),
            ai_score=float(action.get("ai_score") or 0.0),
            feature_json=self._safe_json(context.get("strategy_features") or {}),
            context_json=self._safe_json(context),
            market_regime=market_regime,
            style_profile=style_profile,
            reason=str(action.get("reason") or ""),
            metadata_json=self._safe_json(
                {
                    "warnings": list(action.get("warnings") or []),
                    "risk_mode": str(action.get("risk_mode") or ""),
                }
            ),
        )
        return write_decision_snapshot(conn, snapshot)

    def analyze_bad_decisions(self, conn, limit: int = 10) -> list[Dict[str, object]]:
        rows = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT *
                FROM decision_snapshots
                WHERE result_return IS NOT NULL AND result_return < 0
                ORDER BY result_return ASC, ts DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]
        if rows:
            return rows
        recent_buys = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT ds.ts, ds.symbol, ds.action, ds.execution_score, ds.ai_score, ds.market_regime, ds.style_profile, ds.reason,
                       o.price AS buy_price, p.last_price AS last_price
                FROM decision_snapshots ds
                JOIN orders o ON o.symbol = ds.symbol AND o.side = 'BUY' AND o.intent_only = 0
                LEFT JOIN positions p ON p.symbol = ds.symbol
                WHERE ds.action IN ('BUY', 'PREPARE_BUY')
                  AND datetime(ds.ts) >= datetime('now', '-10 day')
                ORDER BY ds.ts DESC
                LIMIT 40
                """
            )
        ]
        analyzed: list[Dict[str, object]] = []
        for row in recent_buys:
            buy_price = float(row.get("buy_price") or 0.0)
            last_price = float(row.get("last_price") or 0.0)
            if buy_price <= 0 or last_price <= 0:
                continue
            result_return = (last_price - buy_price) / buy_price
            if result_return >= 0:
                continue
            row["result_return"] = round(result_return, 6)
            analyzed.append(row)
        analyzed.sort(key=lambda item: float(item.get("result_return") or 0.0))
        return analyzed[:limit]

    def backfill_trade_results(self, conn, lookback_days: int = 5) -> int:
        snapshots = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT id, ts, symbol
                FROM decision_snapshots
                WHERE action IN ('BUY', 'PREPARE_BUY')
                  AND result_return IS NULL
                  AND date(ts) >= date('now', ?)
                ORDER BY ts DESC
                """,
                (f"-{int(max(lookback_days, 1))} day",),
            )
        ]
        updated = 0
        for row in snapshots:
            ts = datetime.fromisoformat(str(row["ts"]))
            symbol = str(row["symbol"])
            order_rows = [
                dict(item)
                for item in fetch_rows_by_sql(
                    conn,
                    """
                    SELECT price
                    FROM orders
                    WHERE symbol = ?
                      AND side = 'BUY'
                      AND intent_only = 0
                      AND datetime(ts) >= datetime(?)
                      AND datetime(ts) <= datetime(?)
                    ORDER BY ts ASC
                    LIMIT 1
                    """,
                    (symbol, (ts - timedelta(minutes=10)).isoformat(timespec="seconds"), (ts + timedelta(minutes=30)).isoformat(timespec="seconds")),
                )
            ]
            if not order_rows:
                continue
            position_rows = [dict(item) for item in fetch_rows_by_sql(conn, "SELECT last_price, unrealized_pnl, qty FROM positions WHERE symbol = ?", (symbol,))]
            if not position_rows:
                continue
            buy_price = float(order_rows[0].get("price") or 0.0)
            last_price = float(position_rows[0].get("last_price") or 0.0)
            if buy_price <= 0 or last_price <= 0:
                continue
            result_return = (last_price - buy_price) / buy_price
            result_pnl = float(position_rows[0].get("unrealized_pnl") or 0.0)
            conn.execute(
                "UPDATE decision_snapshots SET result_return = ?, result_pnl = ? WHERE id = ?",
                (round(result_return, 6), round(result_pnl, 6), int(row["id"])),
            )
            updated += 1
        return updated
