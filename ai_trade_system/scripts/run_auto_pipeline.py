from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import List

from ai_trade_system.engine.config import load_config
from ai_trade_system.engine.pre_filter_engine import CandidateMetrics
from ai_trade_system.engine.pre_filter_engine import evaluate_candidate
from ai_trade_system.engine.ranking_engine import rank_candidates
from ai_trade_system.engine.scheduler import run_end_of_day_pipeline
from ai_trade_system.engine.universe_service import UniverseService


def _write_lines(path: Path, lines: List[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _data_source_status(warnings: List[str]) -> str:
    if not warnings:
        return "主行情正常，增强维度正常。"
    enhancement_warning = any("增强失败" in item for item in warnings)
    universe_warning = any("股票池抓取失败" in item for item in warnings)
    if universe_warning and enhancement_warning:
        return "主行情已自动切换到可用源，部分增强维度降级，不影响基础结果。"
    if enhancement_warning:
        return "主行情正常，部分增强维度降级，不影响基础结果。"
    return "主行情已自动切换到可用源，基础结果仍有效。"


def _build_execution_summary(plan_payload: dict) -> str:
    summary = plan_payload.get("summary") or {}
    actionable = int(summary.get("actionable_count", 0) or 0)
    hold_count = int(summary.get("hold_count", 0) or 0)
    blocked_sell = int(summary.get("blocked_sell_count", 0) or 0)
    conclusion = str(summary.get("conclusion") or "")
    if actionable > 0:
        return "本次找到 {0} 条可执行交易信号，请优先查看今日交易计划。".format(actionable)
    if blocked_sell > 0:
        return "本次找到 {0} 只强势候选，但今日无新开仓机会，{1} 只仅适合已有持仓者处理。".format(
            len(plan_payload.get("items") or []),
            blocked_sell,
        )
    return "本次找到 {0} 只强势候选，但今日无新开仓机会，主要以观察为主。".format(
        hold_count or len(plan_payload.get("items") or []),
    )


def _build_relaxed_fallback_candidates(
    fetch_result,
    rejected: List[dict],
    top_n: int,
) -> List[CandidateMetrics]:
    rejected_metrics = [row.get("metrics") for row in rejected if isinstance(row.get("metrics"), CandidateMetrics)]
    fallback_metrics: List[CandidateMetrics] = []
    seen = set()

    for metrics in rejected_metrics:
        if metrics.symbol in seen:
            continue
        if metrics.last_price <= 0 or metrics.avg_amount_20d <= 0:
            continue
        fallback_metrics.append(metrics)
        seen.add(metrics.symbol)
        if len(fallback_metrics) >= max(top_n * 2, 12):
            break

    if fallback_metrics:
        return fallback_metrics

    sorted_quotes = sorted(
        [quote for quote in fetch_result.quotes if quote.last_price > 0 and quote.amount > 0],
        key=lambda item: item.amount,
        reverse=True,
    )
    for quote in sorted_quotes:
        if quote.symbol in seen:
            continue
        if "ST" in quote.name.upper() or "退" in quote.name:
            continue
        if abs(quote.pct_change) >= 9.5:
            continue
        fallback_metrics.append(
            CandidateMetrics(
                symbol=quote.symbol,
                market=quote.market,
                name=quote.name,
                last_price=quote.last_price,
                pct_change=quote.pct_change,
                amount=quote.amount,
                volume=quote.volume,
                ma20=quote.last_price,
                ma60=quote.last_price,
                ret_5d=0.0,
                ret_20d=0.0,
                drawdown_20d=0.05,
                volatility_20d=0.02,
                avg_amount_20d=quote.amount,
                data_source="{0}_fallback".format(quote.data_source),
            )
        )
        seen.add(quote.symbol)
        if len(fallback_metrics) >= max(top_n * 2, 12):
            break
    return fallback_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="自动选股 -> AI 分析 -> 交易计划 的收盘后流水线。")
    parser.add_argument("--trade-date", default=date.today().isoformat(), help="交易日期，默认今天")
    parser.add_argument("--scan-limit", type=int, default=300, help="先抓取多少只流动性较高的 A 股做预筛选")
    parser.add_argument("--top-n", type=int, default=12, help="最终交给 AI 分析的候选数量")
    parser.add_argument("--bar-limit", type=int, default=120, help="每只股票抓取多少根日线")
    parser.add_argument("--min-amount", type=float, default=50_000_000.0, help="单只股票最低成交额门槛")
    parser.add_argument("--mode", choices=["quick", "deep"], default="quick", help="AI 分析模式")
    parser.add_argument("--request-timeout", type=int, default=120, help="单只 AI 分析超时秒数")
    parser.add_argument("--retries", type=int, default=1, help="单只 AI 分析重试次数")
    parser.add_argument("--direction-cache-days", type=int, default=3, help="方向缓存复用天数")
    parser.add_argument("--force-refresh-universe", action="store_true", help="强制刷新股票池行情缓存")
    parser.add_argument("--force-full-analysis", action="store_true", help="强制 AI 全量重分析")
    parser.add_argument("--skip-ai", action="store_true", help="只做自动选股，不触发 AI 分析")
    parser.add_argument("--execute-sim", action="store_true", help="生成计划后顺手执行模拟盘")
    args = parser.parse_args()

    config = load_config()
    reports_dir = config.reports_dir
    service = UniverseService(config=config)

    fetch_result = service.fetch_universe_quotes(limit=args.scan_limit, force_refresh=args.force_refresh_universe)
    universe_json_path = reports_dir / "auto_universe_{0}.json".format(args.trade_date)
    service.save_universe_snapshot(fetch_result, universe_json_path)
    print("股票池来源: {0}".format(fetch_result.source))
    for warning in fetch_result.warnings:
        print("提示: {0}".format(warning))

    passed_metrics = []
    rejected = []
    for quote in fetch_result.quotes:
        bars, bar_source = service.fetch_daily_bars(
            quote.symbol,
            market=quote.market,
            limit=args.bar_limit,
            force_refresh=args.force_refresh_universe,
        )
        result = evaluate_candidate(quote, bars, bar_source, min_amount=args.min_amount)
        if result.passed and result.metrics is not None:
            passed_metrics.append(result.metrics)
        else:
            rejected.append(
                {
                    "symbol": quote.symbol,
                    "name": quote.name,
                    "reason": result.reason,
                    "metrics": result.metrics,
                }
            )

    base_ranked = rank_candidates(passed_metrics)
    fallback_used = False
    if not base_ranked:
        fallback_metrics = _build_relaxed_fallback_candidates(fetch_result, rejected, args.top_n)
        if fallback_metrics:
            passed_metrics = fallback_metrics
            base_ranked = rank_candidates(fallback_metrics)
            fallback_used = True
            warning = "严格预筛选无候选，已回退到高流动性降级候选池。"
            fetch_result.warnings.append(warning)
            print("提示: {0}".format(warning))
    enhancement_symbols = [item.symbol for item in base_ranked[: max(args.top_n * 3, 24)]]
    enhancement_result = service.fetch_candidate_enhancements(
        enhancement_symbols,
        trade_date=args.trade_date,
        force_refresh=args.force_refresh_universe,
    )
    for warning in enhancement_result.warnings:
        print("提示: {0}".format(warning))

    metrics_map = {metrics.symbol: metrics for metrics in passed_metrics}
    enhanced_metrics = []
    for item in base_ranked[: max(args.top_n * 3, 24)]:
        metrics = metrics_map[item.symbol]
        enhancement = enhancement_result.items.get(item.symbol)
        if enhancement is not None:
            metrics = replace(
                metrics,
                industry_name=enhancement.industry_name,
                fund_flow_rank_5d=enhancement.fund_flow_rank_5d,
                fund_flow_main_net_inflow_5d=enhancement.fund_flow_main_net_inflow_5d,
                fund_flow_main_net_pct_5d=enhancement.fund_flow_main_net_pct_5d,
                notice_count_3d=enhancement.notice_count_3d,
                risk_notice_count_14d=enhancement.risk_notice_count_14d,
                latest_notice_date=enhancement.latest_notice_date,
                finance_report_date=enhancement.finance_report_date,
                revenue_yoy=enhancement.revenue_yoy,
                net_profit_yoy=enhancement.net_profit_yoy,
                roe=enhancement.roe,
                enhancement_source="、".join(enhancement.data_sources),
            )
        enhanced_metrics.append(metrics)

    ranked = rank_candidates(enhanced_metrics)
    selected = ranked[: args.top_n]
    if not selected:
        raise SystemExit("自动选股没有找到合格候选，请放宽条件或检查数据源。")

    watchlist_path = reports_dir / "auto_watchlist_{0}.txt".format(args.trade_date)
    _write_lines(watchlist_path, [item.symbol for item in selected])

    all_warnings = fetch_result.warnings + enhancement_result.warnings
    data_source_status = _data_source_status(all_warnings)
    markdown_lines = [
        "# 自动选股报告",
        "",
        "交易日期：{0}".format(args.trade_date),
        "股票池来源：{0}".format(fetch_result.source),
        "扫描数量：{0}".format(len(fetch_result.quotes)),
        "通过预筛选：{0}".format(len(passed_metrics)),
        "增强候选：{0}".format(len(enhanced_metrics)),
        "最终候选：{0}".format(len(selected)),
        "",
        "一句话总结：候选股已筛出，是否可执行以下方交易计划为准。",
        "数据源状态：{0}".format(data_source_status),
        "",
    ]
    if fallback_used:
        markdown_lines.extend(
            [
                "提示：本轮严格预筛选无候选，已自动回退到高流动性降级候选池，结果可用于继续分析，但质量低于标准候选。",
                "",
            ]
        )
    if all_warnings:
        markdown_lines.extend(["诊断明细（可选查看）："])
        markdown_lines.extend(["- {0}".format(warning) for warning in all_warnings])
        markdown_lines.append("")
    markdown_lines.extend([
        "候选清单：",
    ])
    for index, item in enumerate(selected, start=1):
        industry_name = str(item.metrics.get("industry_name") or "待补")
        fund_flow_pct = float(item.metrics.get("fund_flow_main_net_pct_5d") or 0.0)
        notice_count = int(item.metrics.get("notice_count_3d") or 0)
        risk_notice_count = int(item.metrics.get("risk_notice_count_14d") or 0)
        revenue_yoy = float(item.metrics.get("revenue_yoy") or 0.0)
        net_profit_yoy = float(item.metrics.get("net_profit_yoy") or 0.0)
        roe = float(item.metrics.get("roe") or 0.0)
        markdown_lines.extend(
            [
                "{0}. {1} {2} | 分数 {3:.2f} | {4}".format(index, item.symbol, item.name, item.score, item.stance),
                "理由：{0}".format("；".join(item.reasons) if item.reasons else "无"),
                "关键指标：最新价 {0}，MA20 {1}，MA60 {2}，20日涨幅 {3:.2%}，20日回撤 {4:.2%}".format(
                    item.metrics["last_price"],
                    item.metrics["ma20"],
                    item.metrics["ma60"],
                    item.metrics["ret_20d"],
                    item.metrics["drawdown_20d"],
                ),
                "增强维度：行业 {0}；5日主力净占比 {1:.2f}% ；近3日公告 {2} 条；近14日风险提示 {3} 条".format(
                    industry_name,
                    fund_flow_pct,
                    notice_count,
                    risk_notice_count,
                ),
                "财报维度：营收同比 {0:.2f}% ；净利同比 {1:.2f}% ；ROE {2:.2f}% ；报告日 {3}".format(
                    revenue_yoy,
                    net_profit_yoy,
                    roe,
                    str(item.metrics.get("finance_report_date") or "待补"),
                ),
                "",
            ]
        )
    if rejected:
        markdown_lines.extend(
            [
                "被过滤样例：",
            ]
        )
        for row in rejected[:20]:
            markdown_lines.append("- {0} {1}：{2}".format(row["symbol"], row["name"], row["reason"]))
        markdown_lines.append("")

    auto_report_path = reports_dir / "auto_candidates_{0}.md".format(args.trade_date)
    _write_lines(auto_report_path, markdown_lines)
    auto_json_path = reports_dir / "auto_candidates_{0}.json".format(args.trade_date)
    auto_json_path.write_text(
        json.dumps(
            {
                "trade_date": args.trade_date,
                "source": fetch_result.source,
                "warnings": all_warnings,
                "data_source_status": data_source_status,
                "one_line_summary": "候选股已筛出，是否可执行以下方交易计划为准。",
                "summary": {
                    "scan_count": len(fetch_result.quotes),
                    "passed_count": len(passed_metrics),
                    "enhanced_count": len(enhanced_metrics),
                    "selected_count": len(selected),
                },
                "fallback_used": fallback_used,
                "selected": [asdict(item) for item in selected],
                "rejected": [
                    {
                        "symbol": row["symbol"],
                        "name": row["name"],
                        "reason": row["reason"],
                    }
                    for row in rejected
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("自动选股报告: {0}".format(auto_report_path))
    print("候选股票池: {0}".format(watchlist_path))

    if not args.skip_ai:
        cmd = [
            sys.executable,
            "-m",
            "ai_trade_system.scripts.run_watchlist",
            "--symbols-file",
            str(watchlist_path),
            "--date",
            args.trade_date,
            "--mode",
            args.mode,
            "--request-timeout",
            str(args.request_timeout),
            "--retries",
            str(args.retries),
            "--direction-cache-days",
            str(args.direction_cache_days),
        ]
        if args.force_full_analysis:
            cmd.append("--force-full-analysis")
        print("开始批量 AI 分析: {0}".format(" ".join(cmd)))
        result = subprocess.run(cmd, cwd=str(config.home.parent.parent))
        if result.returncode != 0:
            raise SystemExit(result.returncode)

        pipeline_result = run_end_of_day_pipeline(
            config=config,
            limit=max(args.top_n, 20),
            trade_date=args.trade_date,
            execute_simulation=args.execute_sim,
            tickers=[item.symbol for item in selected],
        )
        plan_json_path = reports_dir / "daily_plan_{0}.json".format(args.trade_date)
        if plan_json_path.exists():
            plan_payload = json.loads(plan_json_path.read_text(encoding="utf-8"))
            one_line_summary = _build_execution_summary(plan_payload)
            auto_payload = json.loads(auto_json_path.read_text(encoding="utf-8"))
            auto_payload["one_line_summary"] = one_line_summary
            auto_json_path.write_text(json.dumps(auto_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            updated_lines = markdown_lines[:]
            for index, line in enumerate(updated_lines):
                if line.startswith("一句话总结："):
                    updated_lines[index] = "一句话总结：{0}".format(one_line_summary)
                    break
            _write_lines(auto_report_path, updated_lines)
        print("交易计划: {0}".format(pipeline_result["plan_path"]))
        if pipeline_result["execution_events"]:
            print("模拟执行事件:")
            for event in pipeline_result["execution_events"]:
                print("- {0}".format(event))


if __name__ == "__main__":
    main()
