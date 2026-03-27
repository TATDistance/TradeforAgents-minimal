from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List


def generate_review(conn: sqlite3.Connection) -> Dict[str, object]:
    snapshots = conn.execute(
        """
        SELECT *
        FROM account_snapshots
        ORDER BY snapshot_date, id
        """
    ).fetchall()
    orders = conn.execute(
        """
        SELECT *
        FROM sim_orders
        ORDER BY order_date, id
        """
    ).fetchall()
    filled_orders = [row for row in orders if str(row["status"]) == "FILLED"]
    mode_rows = conn.execute(
        """
        SELECT ar.mode AS mode,
               COUNT(so.id) AS trade_count,
               COALESCE(SUM(so.realized_pnl), 0) AS realized_pnl
        FROM sim_orders so
        JOIN signals s ON s.id = so.signal_id
        JOIN analysis_reports ar ON ar.id = s.report_id
        WHERE so.status = 'FILLED'
        GROUP BY ar.mode
        ORDER BY ar.mode
        """
    ).fetchall()

    if snapshots:
        start_equity = float(snapshots[0]["equity"])
        end_equity = float(snapshots[-1]["equity"])
        max_drawdown = max(float(row["drawdown"]) for row in snapshots)
        total_return = 0.0 if start_equity <= 0 else (end_equity - start_equity) / start_equity
    else:
        start_equity = 0.0
        end_equity = 0.0
        max_drawdown = 0.0
        total_return = 0.0

    realized_orders = [row for row in filled_orders if str(row["side"]) == "SELL"]
    wins = [float(row["realized_pnl"]) for row in realized_orders if float(row["realized_pnl"]) > 0]
    losses = [float(row["realized_pnl"]) for row in realized_orders if float(row["realized_pnl"]) < 0]
    order_status_breakdown = {}
    for row in orders:
        status = str(row["status"])
        order_status_breakdown[status] = order_status_breakdown.get(status, 0) + 1

    review = {
        "total_trades": len(filled_orders),
        "closing_trades": len(realized_orders),
        "win_rate": 0.0 if not realized_orders else len(wins) / len(realized_orders),
        "average_win": 0.0 if not wins else sum(wins) / len(wins),
        "average_loss": 0.0 if not losses else sum(losses) / len(losses),
        "profit_loss_ratio": 0.0 if not wins or not losses else (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)),
        "max_drawdown": max_drawdown,
        "total_return": total_return,
        "start_equity": start_equity,
        "end_equity": end_equity,
        "order_status_breakdown": order_status_breakdown,
        "mode_breakdown": [
            {
                "mode": str(row["mode"]),
                "trade_count": int(row["trade_count"]),
                "realized_pnl": float(row["realized_pnl"]),
            }
            for row in mode_rows
        ],
    }
    return review


def review_markdown(review: Dict[str, object]) -> str:
    no_trade = int(review["total_trades"]) == 0
    lines = [
        "# 模拟盘复盘报告",
        "",
        "总成交笔数：{0}".format(review["total_trades"]),
        "平仓笔数：{0}".format(review["closing_trades"]),
        "胜率：{0:.2%}".format(float(review["win_rate"])),
        "平均盈利：{0:.2f}".format(float(review["average_win"])),
        "平均亏损：{0:.2f}".format(float(review["average_loss"])),
        "盈亏比：{0:.2f}".format(float(review["profit_loss_ratio"])),
        "最大回撤：{0:.2%}".format(float(review["max_drawdown"])),
        "累计收益率：{0:.2%}".format(float(review["total_return"])),
        "期初权益：{0:.2f}".format(float(review["start_equity"])),
        "期末权益：{0:.2f}".format(float(review["end_equity"])),
        "",
        "结论：{0}".format("当前没有发生任何模拟成交，优先检查是否仍在等待下一交易日或是否次日未触发成交。" if no_trade else "已有模拟成交，可以开始看胜率、回撤和盈亏比。"),
        "",
        "订单状态拆分：",
    ]
    for status, count in sorted(review["order_status_breakdown"].items()):
        lines.append("- {0}：{1}".format(status, count))
    lines.extend(
        [
            "",
        "模式拆分：",
        ]
    )
    for row in review["mode_breakdown"]:
        lines.append(
            "- {0}：成交={1}，已实现盈亏={2:.2f}".format(
                row["mode"],
                row["trade_count"],
                float(row["realized_pnl"]),
            )
        )
    lines.append("")
    return "\n".join(lines)


def save_review(review: Dict[str, object], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = reports_dir / "paper_review.md"
    json_path = reports_dir / "paper_review.json"
    markdown_path.write_text(review_markdown(review), encoding="utf-8")
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path
