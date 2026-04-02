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


def _load_live_state(settings: Settings, account_id: str | None = None) -> Dict[str, object]:
    live_state_path = settings.resolved_account_live_state_path(account_id or "") if account_id else settings.live_state_path
    if not live_state_path.exists():
        return {}
    try:
        return json.loads(live_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_recent_action_timeline(
    limit: int = 50,
    settings: Settings | None = None,
    account_id: str | None = None,
) -> List[Dict[str, object]]:
    resolved_settings = settings or load_settings()
    conn = connect_db(resolved_settings, account_id=account_id)
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
    live_state = _load_live_state(resolved_settings, account_id=account_id)
    current_ts = str(live_state.get("ts") or datetime.now().isoformat(timespec="seconds"))
    runtime_states = live_state.get("runtime_states") or {}
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
    for symbol, payload in (runtime_states.items() if isinstance(runtime_states, dict) else []):
        if not isinstance(payload, dict):
            continue
        reject_reason = str(payload.get("last_reject_reason") or "").strip()
        reject_ts = str(payload.get("last_reject_at") or "").strip()
        reject_action = str(payload.get("last_reject_action") or "").strip().upper()
        if not reject_reason or not reject_ts or reject_action != "BUY":
            continue
        if "系统将在冷却后再尝试" in reject_reason:
            reason = reject_reason
        else:
            reason = f"{reject_reason}；系统将在冷却后再尝试，避免连续重复下单"
        timeline.append(
            {
                "ts": reject_ts,
                "symbol": str(symbol or ""),
                "action": reject_action,
                "status": "cooldown",
                "phase": str(payload.get("last_phase") or ""),
                "reason": reason,
                "qty": 0,
                "price": 0.0,
            }
        )
    timeline.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    timeline = _collapse_repeated_rejections(timeline)
    return timeline[:limit]


def _collapse_repeated_rejections(timeline: List[Dict[str, object]]) -> List[Dict[str, object]]:
    collapsed: List[Dict[str, object]] = []
    seen_keys: Dict[tuple[str, str, str], int] = {}
    for item in timeline:
        status = str(item.get("status") or "")
        symbol = str(item.get("symbol") or "")
        action = str(item.get("action") or "")
        reason = str(item.get("reason") or "")
        if status not in {"rejected", "cooldown"}:
            collapsed.append(item)
            continue
        normalized_reason = reason.replace("；系统将在冷却后再尝试，避免连续重复下单", "").strip()
        key = (symbol, action, normalized_reason)
        if key in seen_keys:
            first_index = seen_keys[key]
            first = collapsed[first_index]
            repeat_count = int(first.get("repeat_count") or 1) + 1
            first["repeat_count"] = repeat_count
            if first.get("status") != "cooldown" and status == "cooldown":
                first["status"] = "cooldown"
                first["reason"] = reason
            continue
        item["repeat_count"] = 1
        seen_keys[key] = len(collapsed)
        collapsed.append(item)
    for item in collapsed:
        repeat_count = int(item.get("repeat_count") or 1)
        if repeat_count > 1:
            item["reason"] = f"{item.get('reason') or ''}（近阶段重复 {repeat_count} 次）".strip()
    return collapsed
