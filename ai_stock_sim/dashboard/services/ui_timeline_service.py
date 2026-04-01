from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Dict, List

try:
    from ai_stock_sim.app.db import connect_db, fetch_rows_by_sql
    from ai_stock_sim.app.settings import Settings, load_settings
except ModuleNotFoundError:  # pragma: no cover - test/runtime import compatibility
    from app.db import connect_db, fetch_rows_by_sql
    from app.settings import Settings, load_settings


def _load_live_state(settings: Settings) -> Dict[str, object]:
    if not settings.live_state_path.exists():
        return {}
    try:
        return json.loads(settings.live_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_recent_action_timeline(limit: int = 50, settings: Settings | None = None) -> List[Dict[str, object]]:
    resolved_settings = settings or load_settings()
    conn = connect_db(resolved_settings)
    timeline: List[Dict[str, object]] = []
    try:
        orders = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT ts, symbol, side, price, qty, status, note, intent_only, phase
                FROM orders
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
        ]
    except sqlite3.Error:
        orders = []
    finally:
        conn.close()
    for row in orders:
        status = str(row.get("status") or "")
        intent_only = bool(row.get("intent_only"))
        execution_status = "intent" if intent_only or status == "INTENT_ONLY" else ("filled" if status in {"FILLED", "PARTIAL_FILLED"} else status.lower() or "unknown")
        timeline.append(
            {
                "ts": str(row.get("ts") or ""),
                "symbol": str(row.get("symbol") or ""),
                "action": str(row.get("side") or ""),
                "status": execution_status,
                "phase": str(row.get("phase") or ""),
                "reason": str(row.get("note") or ""),
                "qty": int(row.get("qty") or 0),
                "price": float(row.get("price") or 0.0),
            }
        )
    live_state = _load_live_state(resolved_settings)
    current_ts = str(live_state.get("ts") or datetime.now().isoformat(timespec="seconds"))
    for row in live_state.get("risk_results") or []:
        if bool(row.get("allowed")):
            continue
        timeline.append(
            {
                "ts": current_ts,
                "symbol": str(row.get("symbol") or ""),
                "action": str(row.get("action") or ""),
                "status": "rejected",
                "phase": str(row.get("phase") or ""),
                "reason": str(row.get("reason") or row.get("reject_reason") or ""),
                "qty": int(row.get("adjusted_qty") or 0),
                "price": 0.0,
            }
        )
    timeline.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return timeline[:limit]
