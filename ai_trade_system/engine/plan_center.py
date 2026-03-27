from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .market_data import midpoint


ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "hold": "观察",
}

RISK_STATE_LABELS = {
    "ALLOW": "允许",
    "REDUCE_POSITION": "缩减仓位",
    "REJECT": "拒绝",
    "PENDING": "待处理",
}

SIGNAL_STATUS_LABELS = {
    "NEW": "新信号",
    "PLANNED": "已生成计划",
    "WAIT_MARKET": "等待下一交易日",
    "NO_ACTION": "仅观察",
    "EXECUTED": "已模拟成交",
    "ORDER_REJECTED": "模拟下单被拒",
    "ORDER_NOT_FILLED": "次日未成交",
    "BLOCKED": "被风控拦截",
}

ORDER_STATUS_LABELS = {
    "PENDING": "待撮合",
    "WAIT_MARKET": "等待行情",
    "FILLED": "已成交",
    "NOT_FILLED": "未成交",
    "REJECTED": "已拒绝",
}


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "待定"
    return "{0:.3f}".format(float(value))


def build_daily_plan(conn: sqlite3.Connection, trade_date: str, tickers: Optional[Sequence[str]] = None) -> Dict[str, object]:
    if tickers:
        placeholders = ",".join("?" for _ in tickers)
        rows = conn.execute(
            """
            SELECT *
            FROM signals
            WHERE signal_date = ?
              AND ticker IN ({0})
            ORDER BY
                CASE action
                    WHEN 'sell' THEN 0
                    WHEN 'buy' THEN 1
                    ELSE 2
                END,
                id
            """.format(placeholders),
            [trade_date] + list(tickers),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM signals
            WHERE signal_date = ?
            ORDER BY
                CASE action
                    WHEN 'sell' THEN 0
                    WHEN 'buy' THEN 1
                    ELSE 2
                END,
                id
            """,
            (trade_date,),
        ).fetchall()

    items = []
    buy_count = 0
    sell_count = 0
    hold_count = 0
    detail_lines: List[str] = []
    lines = [
        "# 每日交易计划",
        "",
        "交易日期：{0}".format(trade_date),
        "",
    ]

    if not rows:
        lines.append("当日没有发现任何信号。")
        return {"trade_date": trade_date, "items": items, "markdown": "\n".join(lines) + "\n"}

    for index, row in enumerate(rows, start=1):
        action = str(row["action"])
        action_label = ACTION_LABELS.get(action, action)
        risk_state = str(row["risk_state"] or "PENDING")
        risk_label = RISK_STATE_LABELS.get(risk_state, risk_state)
        if action == "buy":
            buy_count += 1
        elif action == "sell":
            sell_count += 1
        else:
            hold_count += 1

        item = {
            "signal_id": int(row["id"]),
            "ticker": str(row["ticker"]),
            "action": action,
            "action_label": action_label,
            "risk_state": risk_state,
            "risk_state_label": risk_label,
            "approved_qty": int(row["approved_qty"]),
            "entry_price": midpoint(row["entry_price_min"], row["entry_price_max"]),
            "entry_range": [_fmt_price(row["entry_price_min"]), _fmt_price(row["entry_price_max"])],
            "stop_loss": row["stop_loss"],
            "take_profit": row["take_profit"],
            "position_pct": float(row["position_pct"]),
            "confidence": float(row["confidence"]),
            "reason": str(row["reason"] or ""),
            "risk_notes": str(row["risk_notes"] or ""),
            "signal_status": str(row["status"] or "NEW"),
            "signal_status_label": SIGNAL_STATUS_LABELS.get(str(row["status"] or "NEW"), str(row["status"] or "NEW")),
        }
        order_row = conn.execute(
            """
            SELECT status, note, order_date, fill_price, fill_qty
            FROM sim_orders
            WHERE signal_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (item["signal_id"],),
        ).fetchone()
        if order_row:
            order_status = str(order_row["status"] or "PENDING")
            item["order_status"] = order_status
            item["order_status_label"] = ORDER_STATUS_LABELS.get(order_status, order_status)
            item["execution_note"] = str(order_row["note"] or "")
            item["execution_order_date"] = str(order_row["order_date"] or "")
            item["execution_fill_price"] = order_row["fill_price"]
            item["execution_fill_qty"] = int(order_row["fill_qty"] or 0)
        else:
            item["order_status"] = ""
            item["order_status_label"] = ""
            item["execution_note"] = ""
            item["execution_order_date"] = ""
            item["execution_fill_price"] = None
            item["execution_fill_qty"] = 0
        items.append(item)

        detail_lines.extend(
            [
                "{0}. {1} {2}".format(index, item["ticker"], item["action_label"]),
                "状态：{0} | 建议数量：{1}".format(item["risk_state_label"], item["approved_qty"]),
                "入场区间：{0} - {1}".format(item["entry_range"][0], item["entry_range"][1]),
                "止损：{0} | 止盈：{1}".format(
                    _fmt_price(item["stop_loss"]),
                    _fmt_price(item["take_profit"]),
                ),
                "建议仓位：{0:.1%} | 置信度：{1:.0%}".format(
                    item["position_pct"],
                    item["confidence"],
                ),
                "执行状态：{0}".format(item["signal_status_label"]),
                "风控说明：{0}".format(item["risk_notes"] or "无"),
                "AI 理由：{0}".format(item["reason"] or "无"),
                "",
            ]
        )
        if item["order_status_label"]:
            detail_lines.extend(
                [
                    "模拟结果：{0}".format(item["order_status_label"]),
                    "模拟说明：{0}".format(item["execution_note"] or "无"),
                    "",
                ]
            )

    actionable_count = len(
        [
            item
            for item in items
            if item["action"] in ("buy", "sell") and item["risk_state"] in ("ALLOW", "REDUCE_POSITION")
        ]
    )
    actionable_items = [
        item
        for item in items
        if item["action"] in ("buy", "sell") and item["risk_state"] in ("ALLOW", "REDUCE_POSITION")
    ]
    waiting_count = len([item for item in items if item["signal_status"] == "WAIT_MARKET"])
    filled_count = len([item for item in items if item["signal_status"] == "EXECUTED"])
    blocked_sell_count = len(
        [
            item
            for item in items
            if item["action"] == "sell" and item["risk_state"] == "REJECT"
        ]
    )
    if actionable_count:
        conclusion = "需要人工下单"
    elif waiting_count:
        conclusion = "已有信号在等待下一交易日撮合"
    else:
        conclusion = "无需下单，以观察为主"
    no_action_reason = "无"
    if not actionable_count:
        reason_bits = []
        if hold_count:
            reason_bits.append("{0} 只观察".format(hold_count))
        if blocked_sell_count:
            reason_bits.append("{0} 只卖出但无持仓或不可卖".format(blocked_sell_count))
        if waiting_count:
            reason_bits.append("{0} 只等待下一交易日".format(waiting_count))
        no_action_reason = "，".join(reason_bits) if reason_bits else "当前没有满足风控和执行条件的信号"
    lines[4:4] = [
        "计划摘要：",
        "- 买入信号：{0}".format(buy_count),
        "- 卖出信号：{0}".format(sell_count),
        "- 观察信号：{0}".format(hold_count),
        "- 可执行信号：{0}".format(actionable_count),
        "- 等待成交信号：{0}".format(waiting_count),
        "- 已模拟成交信号：{0}".format(filled_count),
        "- 今日结论：{0}".format(conclusion),
        "",
    ]

    lines.extend(["今日可执行清单："])
    if actionable_items:
        for item in actionable_items:
            lines.append(
                "- {0} {1} | 建议数量 {2} | 入场 {3} - {4} | 状态 {5}".format(
                    item["ticker"],
                    item["action_label"],
                    item["approved_qty"],
                    item["entry_range"][0],
                    item["entry_range"][1],
                    item["risk_state_label"],
                )
            )
    else:
        lines.extend(
            [
                "- 今日无可执行交易",
                "- 原因：{0}".format(no_action_reason),
            ]
        )
    lines.append("")
    lines.extend(detail_lines)

    lines.extend(
        [
            "人工执行清单：",
            "- 下单前确认是否停牌、是否临近涨跌停、是否存在重大公告。",
            "- 实盘成交后，建议把结果回填到系统，便于后续复盘。",
            "- A 股默认按 T+1 处理，当天买入不能当天卖出。",
            "",
        ]
    )

    return {
        "trade_date": trade_date,
        "summary": {
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
            "actionable_count": actionable_count,
            "waiting_count": waiting_count,
            "filled_count": filled_count,
            "blocked_sell_count": blocked_sell_count,
            "conclusion": conclusion,
            "no_action_reason": no_action_reason,
        },
        "actionable_items": actionable_items,
        "items": items,
        "markdown": "\n".join(lines),
    }


def save_daily_plan(plan: Dict[str, object], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    trade_date = str(plan["trade_date"])
    markdown_path = reports_dir / "daily_plan_{0}.md".format(trade_date)
    json_path = reports_dir / "daily_plan_{0}.json".format(trade_date)
    markdown_path.write_text(str(plan["markdown"]), encoding="utf-8")
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path
