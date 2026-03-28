from __future__ import annotations

from typing import Dict, Iterable, List


EXECUTABLE_ACTIONS = {"BUY", "SELL", "REDUCE"}
IMPORTANT_NON_EXEC_ACTIONS = {"PREPARE_BUY"}
HOLD_ACTIONS = {"HOLD", "HOLD_FOR_TOMORROW"}
AVOID_ACTIONS = {"AVOID_NEW_BUY", "WATCH_NEXT_DAY"}
POSITION_MANAGEMENT_ACTIONS = {"SELL", "REDUCE", "PREPARE_REDUCE"}


def _risk_lookup(risk_results: Iterable[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    lookup: Dict[str, Dict[str, object]] = {}
    for item in risk_results:
        symbol = str(item.get("symbol") or "")
        action = str(item.get("action") or "")
        mode_name = str(item.get("mode_name") or "")
        if not symbol or not action:
            continue
        lookup[f"{symbol}|{action}|{mode_name}"] = item
    return lookup


def _display_action_label(action: str) -> str:
    mapping = {
        "BUY": "BUY",
        "SELL": "SELL",
        "REDUCE": "REDUCE",
        "HOLD": "HOLD",
        "HOLD_FOR_TOMORROW": "HOLD",
        "PREPARE_REDUCE": "REDUCE",
        "PREPARE_BUY": "BUY",
        "AVOID_NEW_BUY": "AVOID",
        "WATCH_NEXT_DAY": "AVOID",
        "ENTER_DEFENSIVE_MODE": "AVOID",
    }
    return mapping.get(action, action or "HOLD")


def _category(action: str, risk: Dict[str, object], executable_now: bool) -> str:
    allowed = bool(risk.get("allowed", False))
    phase_blocked = bool(risk.get("phase_blocked", False))
    blocked_important = action in (EXECUTABLE_ACTIONS | IMPORTANT_NON_EXEC_ACTIONS) and (
        phase_blocked or (not allowed and executable_now) or (not executable_now and action in IMPORTANT_NON_EXEC_ACTIONS)
    )
    if action in EXECUTABLE_ACTIONS and executable_now and allowed:
        return "executable"
    if blocked_important:
        return "blocked"
    if action in POSITION_MANAGEMENT_ACTIONS or action == "PREPARE_REDUCE":
        return "position"
    if action in HOLD_ACTIONS:
        return "hold"
    if action in AVOID_ACTIONS or action == "ENTER_DEFENSIVE_MODE":
        return "avoid"
    return "hold"


def _priority(category: str) -> int:
    order = {
        "executable": 0,
        "blocked": 1,
        "position": 2,
        "hold": 3,
        "avoid": 4,
    }
    return order.get(category, 5)


def _category_label(category: str) -> str:
    mapping = {
        "executable": "可执行动作",
        "blocked": "被拦截的重要动作",
        "position": "持仓管理动作",
        "hold": "保持持有/观察",
        "avoid": "避免开仓",
    }
    return mapping.get(category, "观察")


def _category_color(category: str) -> str:
    mapping = {
        "executable": "success",
        "blocked": "danger",
        "position": "warning",
        "hold": "neutral",
        "avoid": "muted",
    }
    return mapping.get(category, "neutral")


def build_action_cards(
    actions: Iterable[Dict[str, object]],
    risk_results: Iterable[Dict[str, object]],
    symbol_names: Dict[str, str] | None = None,
) -> List[Dict[str, object]]:
    names = symbol_names or {}
    risk_map = _risk_lookup(risk_results)
    cards: List[Dict[str, object]] = []
    for item in actions:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol or symbol == "*":
            continue
        action = str(item.get("action") or "HOLD").strip().upper()
        mode_name = str(item.get("mode_name") or "")
        risk = risk_map.get(f"{symbol}|{action}|{mode_name}", {})
        executable_now = bool(item.get("executable_now", False))
        category = _category(action, risk, executable_now)
        confidence = float(item.get("priority") or item.get("metadata", {}).get("confidence") or 0.0)
        reason = str(risk.get("reason") or item.get("reason") or "").strip()
        position_pct = float(item.get("position_pct") or 0.0)
        reduce_pct = float(item.get("reduce_pct") or 0.0)
        planned_qty = int(item.get("planned_qty") or 0)
        cards.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, symbol),
                "action": action,
                "display_action": _display_action_label(action),
                "category": category,
                "category_label": _category_label(category),
                "category_color": _category_color(category),
                "priority_group": _priority(category),
                "priority_score": confidence,
                "reason": reason,
                "position_pct": position_pct,
                "reduce_pct": reduce_pct,
                "planned_qty": planned_qty,
                "planned_price": float(item.get("planned_price") or 0.0),
                "executable_now": executable_now and bool(risk.get("allowed", False)),
                "blocked": category == "blocked",
                "risk_state": str(risk.get("risk_state") or ""),
                "phase": str(item.get("phase") or ""),
                "mode_name": mode_name,
                "source": list(item.get("source") or []),
            }
        )
    cards.sort(
        key=lambda row: (
            row["priority_group"],
            -float(row.get("priority_score") or 0.0),
            row["symbol"],
        )
    )
    return cards


def summarize_action_cards(cards: Iterable[Dict[str, object]]) -> Dict[str, int]:
    rows = list(cards)
    return {
        "intent_count": sum(1 for row in rows if not bool(row.get("executable_now"))),
        "executed_count": sum(1 for row in rows if bool(row.get("executable_now"))),
        "blocked_count": sum(1 for row in rows if bool(row.get("blocked"))),
    }
