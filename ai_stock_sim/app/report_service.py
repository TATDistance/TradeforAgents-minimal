from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .db import fetch_recent_rows, fetch_rows_by_sql
from .evaluation_service import EvaluationService
from .settings import Settings, load_settings
from .watchlist_sync_service import load_runtime_watchlist
from .watchlist_service import get_active_watchlist


class ReportService:
    def __init__(self, settings: Settings | None = None, evaluation_service: EvaluationService | None = None) -> None:
        self.settings = settings or load_settings()
        self.evaluation_service = evaluation_service or EvaluationService(self.settings)
        for subdir in ("daily", "weekly", "monthly"):
            (self.settings.reports_dir / subdir).mkdir(parents=True, exist_ok=True)

    def export_daily_report(self, conn, trade_date: str) -> dict[str, Path]:
        evaluation = self.evaluation_service.compute_daily_metrics(conn, trade_date)
        payload = self._build_report_payload(conn, evaluation, trade_date, report_scope="daily")
        return self._write_report_bundle(self.settings.reports_dir / "daily", f"daily_{trade_date}", payload)

    def export_weekly_report(self, conn, week_start: str, week_end: str) -> dict[str, Path]:
        evaluation = self.evaluation_service.compute_weekly_metrics(conn, week_start, week_end)
        payload = self._build_report_payload(conn, evaluation, week_end, report_scope="weekly")
        return self._write_report_bundle(self.settings.reports_dir / "weekly", f"weekly_{week_start}_{week_end}", payload)

    def export_monthly_report(self, conn, month: str) -> dict[str, Path]:
        evaluation = self.evaluation_service.compute_monthly_metrics(conn, month)
        payload = self._build_report_payload(conn, evaluation, month, report_scope="monthly")
        return self._write_report_bundle(self.settings.reports_dir / "monthly", f"monthly_{month}", payload)

    def _build_report_payload(self, conn, evaluation, label: str, report_scope: str) -> dict[str, Any]:
        period_start = str(getattr(evaluation, "period_start", None) or label)
        period_end = str(getattr(evaluation, "period_end", None) or label)
        account_rows = [dict(row) for row in fetch_rows_by_sql(conn, "SELECT * FROM account_snapshots WHERE date(ts) BETWEEN ? AND ? ORDER BY id DESC LIMIT 50", (period_start, period_end))]
        orders = [dict(row) for row in fetch_rows_by_sql(conn, "SELECT * FROM orders WHERE date(ts) BETWEEN ? AND ? ORDER BY id DESC LIMIT 100", (period_start, period_end))]
        positions = [dict(row) for row in fetch_recent_rows(conn, "positions", limit=50)]
        ai_rows = [dict(row) for row in fetch_rows_by_sql(conn, "SELECT * FROM ai_decisions WHERE date(ts) BETWEEN ? AND ? ORDER BY id DESC LIMIT 50", (period_start, period_end))]
        logs = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT * FROM system_logs
                WHERE date(ts) BETWEEN ? AND ?
                  AND lower(module) IN ('risk', 'risk_engine', 'scheduler', 'market_phase')
                ORDER BY id DESC LIMIT 120
                """,
                (period_start, period_end),
            )
        ]
        phase_logs = [row for row in logs if str(row["module"]).lower() == "market_phase"]
        actual_orders = [row for row in orders if not bool(row.get("intent_only")) and str(row.get("status")) in {"FILLED", "PARTIAL_FILLED"}]
        intent_orders = [row for row in orders if bool(row.get("intent_only")) or str(row.get("status")) == "INTENT_ONLY"]
        tomorrow_actions = [row for row in intent_orders if str(row.get("phase") or "") == "POST_CLOSE"]
        watchlist = load_runtime_watchlist(self.settings)
        if not watchlist.get("symbols"):
            watchlist = get_active_watchlist(self.settings)
        return {
            "report_scope": report_scope,
            "label": label,
            "evaluation": evaluation.model_dump(),
            "account_tail": account_rows,
            "orders": orders,
            "actual_orders": actual_orders,
            "intent_orders": intent_orders,
            "positions": positions,
            "ai_decisions": ai_rows,
            "risk_logs": logs,
            "phase_logs": phase_logs,
            "tomorrow_actions": tomorrow_actions,
            "watchlist": watchlist,
            "summary": {
                "phase_blocked_actions": len(intent_orders),
                "actual_fills": len(actual_orders),
                "post_close_preparations": len(tomorrow_actions),
            },
        }

    def _write_report_bundle(self, output_dir: Path, stem: str, payload: Mapping[str, Any]) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{stem}.json"
        md_path = output_dir / f"{stem}.md"
        html_path = output_dir / f"{stem}.html"

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        md_path.write_text(self._render_markdown(payload), encoding="utf-8")
        html_path.write_text(self._render_html(payload), encoding="utf-8")
        return {"json": json_path, "markdown": md_path, "html": html_path}

    def _render_markdown(self, payload: Mapping[str, Any]) -> str:
        evaluation = payload["evaluation"]
        orders = payload["orders"]
        actual_orders = payload["actual_orders"]
        intent_orders = payload["intent_orders"]
        ai_rows = payload["ai_decisions"]
        risk_logs = payload["risk_logs"]
        phase_logs = payload["phase_logs"]
        tomorrow_actions = payload["tomorrow_actions"]
        summary = payload["summary"]
        runtime_metrics = evaluation.get("metadata_json")
        runtime_stats = {}
        if runtime_metrics:
            try:
                runtime_stats = json.loads(runtime_metrics).get("runtime_event_metrics") or {}
            except Exception:
                runtime_stats = {}
        lines = [
            f"# {payload['report_scope']} 报告",
            "",
            f"- 标签：{payload['label']}",
            f"- 总收益率：{evaluation['total_return']:.2%}",
            f"- 最大回撤：{evaluation['max_drawdown']:.2%}",
            f"- 胜率：{evaluation['win_rate']:.2%}",
            f"- 盈亏比：{evaluation['pnl_ratio']:.2f}",
            f"- 利润因子：{evaluation['profit_factor']:.2f}",
            f"- 期望收益：{evaluation['expectancy']:.4f}",
            f"- 策略评分：{evaluation['score_total']:.2f} / {evaluation['grade']}",
            f"- 今日真实成交数：{summary['actual_fills']}",
            f"- 今日阶段拦截动作数：{summary['phase_blocked_actions']}",
            f"- 盘后明日准备动作数：{summary['post_close_preparations']}",
            f"- 当前监控池来源：{str(payload.get('watchlist', {}).get('source') or 'unknown')}",
            f"- 事件触发数：{runtime_stats.get('trigger_count', 0)}",
            f"- 有效触发率：{float(runtime_stats.get('effective_trigger_rate', 0.0)):.2%}",
            f"- 触发后真实成交率：{float(runtime_stats.get('trigger_fill_rate', 0.0)):.2%}",
            f"- 平均 setup_score：{float(runtime_stats.get('avg_setup_score', 0.0)):.2f}",
            f"- 平均 execution_score：{float(runtime_stats.get('avg_execution_score', 0.0)):.2f}",
            "",
            "## 今日交易阶段流转",
        ]
        if phase_logs:
            for row in phase_logs[:20]:
                lines.append(f"- {row['ts']} {row['message']}")
        else:
            lines.append("- 无阶段流转日志")
        lines.extend([
            "",
            "## 当日成交",
        ])
        if actual_orders:
            for row in actual_orders[:20]:
                lines.append(f"- {row['ts']} {row['symbol']} {row['side']} {row['qty']} 股 @ {row['price']}")
        else:
            lines.append("- 无成交")
        lines.append("")
        lines.append("## 动作意图与盘后计划")
        if intent_orders:
            for row in intent_orders[:20]:
                phase = str(row.get("phase") or "-")
                lines.append(f"- {row['ts']} [{phase}] {row['symbol']} {row['side']} 意图 {row['qty']} 股：{row['note']}")
        else:
            lines.append("- 无动作意图")
        lines.append("")
        lines.append("## AI 审批摘要")
        if ai_rows:
            for row in ai_rows[:10]:
                lines.append(f"- {row['symbol']} {row['ai_action']} 置信度 {float(row['confidence']):.2f}：{row['reason']}")
        else:
            lines.append("- 无 AI 审批记录")
        lines.append("")
        lines.append("## 风控拦截与告警")
        if risk_logs:
            for row in risk_logs[:20]:
                lines.append(f"- [{row['level']}] {row['module']}：{row['message']}")
        else:
            lines.append("- 无告警")
        lines.append("")
        lines.append("## 明日观察与准备动作")
        if tomorrow_actions:
            for row in tomorrow_actions[:20]:
                lines.append(f"- {row['symbol']} {row['side']} 计划 {row['qty']} 股：{row['note']}")
        else:
            lines.append("- 无盘后准备动作")
        return "\n".join(lines)

    def _render_html(self, payload: Mapping[str, Any]) -> str:
        markdown = self._render_markdown(payload)
        body = "<br/>".join(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for line in markdown.splitlines())
        return f"<html><head><meta charset='utf-8'><title>{payload['report_scope']} 报告</title></head><body>{body}</body></html>"
