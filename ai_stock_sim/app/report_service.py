from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .db import fetch_recent_rows
from .evaluation_service import EvaluationService
from .settings import Settings, load_settings


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
        account_rows = [dict(row) for row in fetch_recent_rows(conn, "account_snapshots", limit=20)]
        orders = [dict(row) for row in fetch_recent_rows(conn, "orders", limit=50)]
        positions = [dict(row) for row in fetch_recent_rows(conn, "positions", limit=50)]
        ai_rows = [dict(row) for row in fetch_recent_rows(conn, "ai_decisions", limit=50)]
        logs = [dict(row) for row in fetch_recent_rows(conn, "system_logs", limit=100) if str(row["module"]).lower() in {"risk", "risk_engine", "scheduler"}]
        return {
            "report_scope": report_scope,
            "label": label,
            "evaluation": evaluation.model_dump(),
            "account_tail": account_rows,
            "orders": orders,
            "positions": positions,
            "ai_decisions": ai_rows,
            "risk_logs": logs,
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
        ai_rows = payload["ai_decisions"]
        risk_logs = payload["risk_logs"]
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
            "",
            "## 当日成交",
        ]
        if orders:
            for row in orders[:20]:
                lines.append(f"- {row['ts']} {row['symbol']} {row['side']} {row['qty']} 股 @ {row['price']}")
        else:
            lines.append("- 无成交")
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
        return "\n".join(lines)

    def _render_html(self, payload: Mapping[str, Any]) -> str:
        markdown = self._render_markdown(payload)
        body = "<br/>".join(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for line in markdown.splitlines())
        return f"<html><head><meta charset='utf-8'><title>{payload['report_scope']} 报告</title></head><body>{body}</body></html>"
