#!/usr/bin/env python3
"""
DeepSeek 单模型多模块股票分析工具（CLI）

目标：
- 仅输入股票代码（可选日期）
- 仅用 DeepSeek API
- 产出接近原项目的多报告目录结构

用法:
  python scripts/minimal_deepseek_report.py 600028
  python scripts/minimal_deepseek_report.py 510300 --date 2026-03-26
  python scripts/minimal_deepseek_report.py AAPL --model deepseek-chat

输出目录:
  results/<输入代码>/<日期>/
    - analysis_metadata.json
    - decision.json
    - message_tool.log
    - reports/
      - market_report.md
      - fundamentals_report.md
      - news_report.md
      - research_team_decision.md
      - investment_plan.md
      - trader_investment_plan.md
      - risk_management_decision.md
      - final_trade_decision.md
      - final_report.md
      - market_snapshot.json
      - news_snapshot.json
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import yfinance as yf
from openai import OpenAI


# yfinance 会输出大量 warning（包含非致命网络重试），统一降级避免误判为失败
logging.getLogger("yfinance").setLevel(logging.ERROR)


def normalize_symbol(user_symbol: str) -> Tuple[str, str]:
    """返回 (原始输入, yfinance可用代码)"""
    raw = user_symbol.strip().upper()
    if not raw:
        raise ValueError("股票代码不能为空")

    if re.fullmatch(r"[A-Z0-9.\-]{1,20}", raw) and "." in raw:
        return raw, raw

    if re.fullmatch(r"\d{6}", raw):
        # 上交所常见前缀: 5(ETF/基金), 6(主板/科创), 9(B股)
        if raw.startswith(("5", "6", "9")):
            return raw, f"{raw}.SS"
        return raw, f"{raw}.SZ"

    if re.fullmatch(r"\d{4,5}", raw):
        hk_code = str(int(raw)).zfill(4)
        return raw, f"{hk_code}.HK"

    if re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", raw):
        return raw, raw

    raise ValueError(f"不支持的股票代码格式: {user_symbol}")


def infer_market_type(yf_symbol: str) -> str:
    if yf_symbol.endswith(".SS") or yf_symbol.endswith(".SZ"):
        return "A股"
    if yf_symbol.endswith(".HK"):
        return "港股"
    return "美股"


def candidate_yf_symbols(user_symbol: str, preferred_yf_symbol: str) -> List[str]:
    cands: List[str] = [preferred_yf_symbol]
    if re.fullmatch(r"\d{6}", user_symbol):
        cands.extend([f"{user_symbol}.SS", f"{user_symbol}.SZ"])

    seen = set()
    uniq: List[str] = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    old = float(series.iloc[-periods - 1])
    new = float(series.iloc[-1])
    if old == 0:
        return None
    return (new - old) / old


def fetch_market_data(yf_symbol: str, as_of_date: str) -> Dict[str, Any]:
    end_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=220)

    ticker = yf.Ticker(yf_symbol)
    hist = ticker.history(
        start=start_dt.strftime("%Y-%m-%d"),
        end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
    )

    if hist is None or hist.empty:
        raise RuntimeError(f"无法从 yfinance 获取行情: {yf_symbol}")

    close = hist["Close"].dropna()
    volume = hist["Volume"].dropna()

    latest = hist.iloc[-1]
    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    ma60 = float(close.tail(60).mean()) if len(close) >= 60 else None
    vol_avg20 = float(volume.tail(20).mean()) if len(volume) >= 20 else None

    p1w = pct_change(close, 5)
    p1m = pct_change(close, 21)
    p3m = pct_change(close, 63)

    high_52w = float(close.tail(252).max()) if len(close) >= 1 else None
    low_52w = float(close.tail(252).min()) if len(close) >= 1 else None

    info: Dict[str, Any] = {}
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    snapshot = {
        "symbol": yf_symbol,
        "as_of_date": as_of_date,
        "latest": {
            "date": str(hist.index[-1].date()),
            "open": float(latest.get("Open", 0.0)),
            "high": float(latest.get("High", 0.0)),
            "low": float(latest.get("Low", 0.0)),
            "close": float(latest.get("Close", 0.0)),
            "volume": float(latest.get("Volume", 0.0)),
        },
        "technical": {
            "ma20": ma20,
            "ma60": ma60,
            "volume_avg20": vol_avg20,
            "change_1w": p1w,
            "change_1m": p1m,
            "change_3m": p3m,
            "high_52w": high_52w,
            "low_52w": low_52w,
        },
        "fundamentals": {
            "longName": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "marketCap": info.get("marketCap"),
            "trailingPE": info.get("trailingPE"),
            "forwardPE": info.get("forwardPE"),
            "priceToBook": info.get("priceToBook"),
            "dividendYield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "currency": info.get("currency"),
        },
    }
    return snapshot


def fetch_news(yf_symbol: str, max_news: int = 8) -> List[Dict[str, Any]]:
    ticker = yf.Ticker(yf_symbol)
    try:
        items = ticker.news or []
    except Exception:
        items = []

    parsed: List[Dict[str, Any]] = []
    for item in items[:max_news]:
        content = item.get("content", {}) if isinstance(item, dict) else {}
        parsed.append(
            {
                "title": content.get("title") or item.get("title"),
                "summary": content.get("summary") or item.get("summary"),
                "source": (
                    (content.get("provider") or {}).get("displayName")
                    if isinstance(content.get("provider"), dict)
                    else item.get("publisher")
                ),
                "url": (
                    content.get("canonicalUrl", {}).get("url")
                    if isinstance(content.get("canonicalUrl"), dict)
                    else item.get("link")
                ),
                "published_at": content.get("pubDate") or item.get("providerPublishTime"),
            }
        )
    return parsed


def build_data_context(
    user_symbol: str,
    yf_symbol: str,
    analysis_date: str,
    market_type: str,
    market_snapshot: Dict[str, Any],
    news: List[Dict[str, Any]],
) -> str:
    return (
        f"用户输入代码: {user_symbol}\n"
        f"规范化代码: {yf_symbol}\n"
        f"市场类型: {market_type}\n"
        f"分析日期: {analysis_date}\n\n"
        "行情与基本面JSON:\n"
        f"{json.dumps(market_snapshot, ensure_ascii=False, indent=2)}\n\n"
        "新闻JSON:\n"
        f"{json.dumps(news, ensure_ascii=False, indent=2)}\n"
    )


def safe_json_extract(text: str) -> Dict[str, Any] | None:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def call_deepseek(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    module_name: str,
    module_logs: List[str],
    temperature: float = 0.2,
    request_timeout: float = 60.0,
    max_retries: int = 3,
) -> str:
    last_error = ""
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        print(f"  - 模块 {module_name}: 尝试 {attempt}/{max_retries}", flush=True)
        module_logs.append(
            f"[{datetime.now().isoformat()}] {module_name}: start attempt={attempt}/{max_retries} timeout={request_timeout}s"
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                timeout=request_timeout,
            )
            content = (resp.choices[0].message.content or "").strip()
            elapsed = time.time() - t0
            if not content:
                raise RuntimeError("返回空内容")
            module_logs.append(
                f"[{datetime.now().isoformat()}] {module_name}: success attempt={attempt} elapsed={elapsed:.2f}s len={len(content)}"
            )
            print(f"    -> 成功 ({elapsed:.2f}s)", flush=True)
            return content
        except Exception as e:
            elapsed = time.time() - t0
            last_error = str(e)
            module_logs.append(
                f"[{datetime.now().isoformat()}] {module_name}: fail attempt={attempt} elapsed={elapsed:.2f}s err={last_error}"
            )
            print(f"    -> 失败 ({elapsed:.2f}s): {last_error}", flush=True)
            if attempt < max_retries:
                time.sleep(min(2 * attempt, 5))

    raise RuntimeError(f"{module_name} 调用失败: {last_error}")


def generate_reports(
    client: OpenAI,
    model: str,
    data_context: str,
    market_snapshot: Dict[str, Any],
    news: List[Dict[str, Any]],
    module_logs: List[str],
    request_timeout: float,
    max_retries: int,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    reports: Dict[str, str] = {}

    total_modules = 8
    module_idx = 0

    def run_module(
        module_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        nonlocal module_idx
        module_idx += 1
        print(f"  - [{module_idx}/{total_modules}] 生成 {module_name}", flush=True)
        return call_deepseek(
            client=client,
            model=model,
            module_name=module_name,
            module_logs=module_logs,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )

    market_report = run_module(
        module_name="market_report",
        system_prompt="你是市场技术分析师。必须用中文Markdown输出，数据不足时明确写出。",
        user_prompt=(
            "请生成 market_report.md 内容，聚焦技术面和行情：\n"
            "- 均线、近期涨跌、成交量变化\n"
            "- 支撑位/压力位\n"
            "- 结尾给出技术面倾向（偏多/中性/偏空）\n\n"
            f"{data_context}"
        ),
    )
    reports["market_report.md"] = market_report

    fundamentals_report = run_module(
        module_name="fundamentals_report",
        system_prompt="你是基本面分析师。必须用中文Markdown输出。",
        user_prompt=(
            "请生成 fundamentals_report.md 内容：\n"
            "- 公司/标的性质（若是ETF请明确）\n"
            "- 估值与财务指标解读（PE/PB/市值/股息/beta等）\n"
            "- 指标缺失时请说明并给出保守判断\n"
            "- 给出中短期基本面结论\n\n"
            f"{data_context}"
        ),
    )
    reports["fundamentals_report.md"] = fundamentals_report

    news_report = run_module(
        module_name="news_report",
        system_prompt="你是新闻事件分析师。必须用中文Markdown输出。",
        user_prompt=(
            "请生成 news_report.md 内容：\n"
            "- 列出最近关键新闻（无新闻就写'暂无高相关新闻'）\n"
            "- 评估对价格可能影响（短期/中期）\n"
            "- 给出新闻面情绪判断（偏多/中性/偏空）\n\n"
            f"{data_context}"
        ),
    )
    reports["news_report.md"] = news_report

    research_team_decision = run_module(
        module_name="research_team_decision",
        system_prompt="你是研究团队主持人。必须用中文Markdown输出。",
        user_prompt=(
            "请生成 research_team_decision.md，必须包含三部分：\n"
            "## 多头研究员观点\n"
            "## 空头研究员观点\n"
            "## 研究经理综合决策\n"
            "要求：论据来自行情/基本面/新闻，不要空话。\n\n"
            f"market_report:\n{market_report}\n\n"
            f"fundamentals_report:\n{fundamentals_report}\n\n"
            f"news_report:\n{news_report}\n"
        ),
    )
    reports["research_team_decision.md"] = research_team_decision

    investment_plan = run_module(
        module_name="investment_plan",
        system_prompt="你是投资组合经理。必须用中文Markdown输出。",
        user_prompt=(
            "请生成 investment_plan.md：\n"
            "- 明确给出当前建议：买入/持有/卖出（三选一）\n"
            "- 给出仓位建议（如轻仓/中仓/空仓）\n"
            "- 给出触发条件（什么情况下改变观点）\n\n"
            f"research_team_decision:\n{research_team_decision}\n"
        ),
    )
    reports["investment_plan.md"] = investment_plan

    trader_investment_plan = run_module(
        module_name="trader_investment_plan",
        system_prompt="你是交易员。必须用中文Markdown输出。",
        user_prompt=(
            "请生成 trader_investment_plan.md：\n"
            "- 入场区间\n"
            "- 止损位\n"
            "- 第一/第二目标位\n"
            "- 执行节奏（分批、一次性等）\n"
            "- 如果是ETF请按指数型资产特点给计划\n\n"
            f"investment_plan:\n{investment_plan}\n\n"
            f"market_report:\n{market_report}\n"
        ),
    )
    reports["trader_investment_plan.md"] = trader_investment_plan

    risk_management_decision = run_module(
        module_name="risk_management_decision",
        system_prompt="你是风险管理委员会。必须用中文Markdown输出。",
        user_prompt=(
            "请生成 risk_management_decision.md，必须包含：\n"
            "## 激进风险观点\n"
            "## 保守风险观点\n"
            "## 中性风险观点\n"
            "## 风险委员会最终裁决\n"
            "并明确主要风险来源和应对动作。\n\n"
            f"trader_investment_plan:\n{trader_investment_plan}\n\n"
            f"investment_plan:\n{investment_plan}\n\n"
            f"news_report:\n{news_report}\n"
        ),
    )
    reports["risk_management_decision.md"] = risk_management_decision

    # 结构化最终决策
    raw_final_json = run_module(
        module_name="final_trade_decision_json",
        system_prompt="你是投资决策结构化助手，只返回JSON，不要返回markdown。",
        user_prompt=(
            "请仅返回一个JSON对象，字段必须完整：\n"
            "{\n"
            '  "action": "买入|持有|卖出",\n'
            '  "confidence": 0到1的小数,\n'
            '  "risk_score": 0到1的小数,\n'
            '  "target_price_range": "例如 4.50-5.20 CNY",\n'
            '  "reasoning": "不超过200字"\n'
            "}\n\n"
            f"market_report:\n{market_report}\n\n"
            f"fundamentals_report:\n{fundamentals_report}\n\n"
            f"news_report:\n{news_report}\n\n"
            f"investment_plan:\n{investment_plan}\n\n"
            f"risk_management_decision:\n{risk_management_decision}\n"
        ),
        temperature=0.0,
    )

    decision = safe_json_extract(raw_final_json) or {}

    action = str(decision.get("action", "持有"))
    if action not in {"买入", "持有", "卖出"}:
        action_lower = action.lower()
        if "buy" in action_lower:
            action = "买入"
        elif "sell" in action_lower:
            action = "卖出"
        else:
            action = "持有"

    def to_float(v: Any, default: float) -> float:
        try:
            x = float(v)
            if x < 0:
                return 0.0
            if x > 1:
                return 1.0
            return x
        except Exception:
            return default

    decision_obj = {
        "action": action,
        "confidence": to_float(decision.get("confidence", 0.68), 0.68),
        "risk_score": to_float(decision.get("risk_score", 0.42), 0.42),
        "target_price_range": str(decision.get("target_price_range", "待进一步确认")).strip(),
        "reasoning": str(decision.get("reasoning", "基于综合分析给出中性建议")).strip(),
    }

    final_trade_decision_md = (
        "# 最终交易决策\n\n"
        f"- **建议动作**: {decision_obj['action']}\n"
        f"- **置信度**: {decision_obj['confidence']:.2f}\n"
        f"- **风险评分**: {decision_obj['risk_score']:.2f}\n"
        f"- **目标区间**: {decision_obj['target_price_range']}\n\n"
        "## 决策理由\n\n"
        f"{decision_obj['reasoning']}\n"
    )
    reports["final_trade_decision.md"] = final_trade_decision_md

    final_report = (
        "# 综合分析总报告\n\n"
        "## 模块目录\n"
        "1. 市场分析\n"
        "2. 基本面分析\n"
        "3. 新闻分析\n"
        "4. 研究团队决策\n"
        "5. 投资计划\n"
        "6. 交易执行计划\n"
        "7. 风险管理决策\n"
        "8. 最终交易决策\n\n"
        "---\n\n"
        "## 1. 市场分析\n\n"
        f"{market_report}\n\n"
        "---\n\n"
        "## 2. 基本面分析\n\n"
        f"{fundamentals_report}\n\n"
        "---\n\n"
        "## 3. 新闻分析\n\n"
        f"{news_report}\n\n"
        "---\n\n"
        "## 4. 研究团队决策\n\n"
        f"{research_team_decision}\n\n"
        "---\n\n"
        "## 5. 投资计划\n\n"
        f"{investment_plan}\n\n"
        "---\n\n"
        "## 6. 交易执行计划\n\n"
        f"{trader_investment_plan}\n\n"
        "---\n\n"
        "## 7. 风险管理决策\n\n"
        f"{risk_management_decision}\n\n"
        "---\n\n"
        "## 8. 最终交易决策\n\n"
        f"{final_trade_decision_md}\n"
    )
    reports["final_report.md"] = final_report

    return reports, decision_obj


def normalize_report_markdown(text: str) -> str:
    """清理模型返回中常见的外层 markdown 代码块包裹，避免导出时显示异常。"""
    if not text:
        return ""
    cleaned = text.strip()
    # 去掉完整包裹的 ```markdown ... ``` 或 ``` ... ```
    fence_full = re.match(r"^```(?:markdown)?\s*([\s\S]*?)\s*```$", cleaned, flags=re.IGNORECASE)
    if fence_full:
        cleaned = fence_full.group(1).strip()
    # 去掉残留的单独 fence 行
    cleaned = re.sub(r"(?m)^\s*```(?:markdown)?\s*$", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*```\s*$", "", cleaned)
    return cleaned.strip()


def build_share_markdown(
    user_symbol: str,
    analysis_date: str,
    decision_obj: Dict[str, Any],
    reports: Dict[str, str],
    market_snapshot: Dict[str, Any],
) -> str:
    latest = market_snapshot.get("latest", {})
    fundamentals = market_snapshot.get("fundamentals", {})
    technical = market_snapshot.get("technical", {})

    market_txt = normalize_report_markdown(reports.get("market_report.md", "无"))
    fundamentals_txt = normalize_report_markdown(reports.get("fundamentals_report.md", "无"))
    news_txt = normalize_report_markdown(reports.get("news_report.md", "无"))
    research_txt = normalize_report_markdown(reports.get("research_team_decision.md", "无"))
    invest_txt = normalize_report_markdown(reports.get("investment_plan.md", "无"))
    trader_txt = normalize_report_markdown(reports.get("trader_investment_plan.md", "无"))
    risk_txt = normalize_report_markdown(reports.get("risk_management_decision.md", "无"))
    final_txt = normalize_report_markdown(reports.get("final_trade_decision.md", "无"))

    return (
        f"# {user_symbol} 投资分析简报（可转发版）\n\n"
        f"> 分析日期：{analysis_date}\n\n"
        "## 一句话结论\n\n"
        f"- 建议动作：**{decision_obj.get('action', '持有')}**\n"
        f"- 置信度：**{decision_obj.get('confidence', 0):.2f}**\n"
        f"- 风险评分：**{decision_obj.get('risk_score', 0):.2f}**\n"
        f"- 目标区间：**{decision_obj.get('target_price_range', '待确认')}**\n\n"
        "## 核心理由\n\n"
        f"{decision_obj.get('reasoning', '无')}\n\n"
        "## 关键行情快照\n\n"
        f"- 最新收盘：{latest.get('close', 'N/A')}\n"
        f"- 最新成交量：{latest.get('volume', 'N/A')}\n"
        f"- 近1周涨跌：{technical.get('change_1w', 'N/A')}\n"
        f"- 近1月涨跌：{technical.get('change_1m', 'N/A')}\n"
        f"- 行业：{fundamentals.get('industry', 'N/A')}\n"
        f"- 市值：{fundamentals.get('marketCap', 'N/A')}\n\n"
        "## 详细分析（节选）\n\n"
        "### 市场面\n\n"
        f"{market_txt}\n\n"
        "### 基本面\n\n"
        f"{fundamentals_txt}\n\n"
        "### 新闻面\n\n"
        f"{news_txt}\n\n"
        "### 研究团队决策\n\n"
        f"{research_txt}\n\n"
        "### 投资计划\n\n"
        f"{invest_txt}\n\n"
        "### 交易执行计划\n\n"
        f"{trader_txt}\n\n"
        "### 风险管理\n\n"
        f"{risk_txt}\n\n"
        "### 最终交易决策\n\n"
        f"{final_txt}\n\n"
        "---\n\n"
        "风险提示：以上内容仅供学习交流，不构成投资建议。\n"
    )


def markdown_to_simple_html(md_text: str, title: str) -> str:
    try:
        import markdown as mdlib  # type: ignore

        body = mdlib.markdown(
            md_text,
            extensions=["extra", "tables", "fenced_code", "sane_lists", "nl2br"],
            output_format="html5",
        )
        return (
            "<!doctype html>\n"
            "<html lang='zh-CN'>\n"
            "<head>\n"
            "  <meta charset='utf-8'/>\n"
            "  <meta name='viewport' content='width=device-width, initial-scale=1'/>\n"
            f"  <title>{html.escape(title)}</title>\n"
            "  <style>\n"
            "    body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
            "max-width:900px;margin:0 auto;padding:24px;line-height:1.75;color:#1f2937;background:#f7fafc;}\n"
            "    h1,h2,h3{line-height:1.35;color:#0f172a;}\n"
            "    h1{font-size:28px;margin-top:0;} h2{font-size:22px;margin-top:28px;} h3{font-size:18px;margin-top:20px;}\n"
            "    p,li{font-size:16px;} ul{padding-left:22px;} li{margin:6px 0;}\n"
            "    blockquote{background:#eef2ff;border-left:4px solid #6366f1;padding:10px 14px;border-radius:8px;}\n"
            "    code{background:#eef2f7;padding:2px 6px;border-radius:6px;}\n"
            "    pre{background:#0f172a;color:#e5e7eb;padding:14px;border-radius:10px;overflow:auto;}\n"
            "    table{border-collapse:collapse;width:100%;font-size:14px;margin:14px 0;}\n"
            "    th,td{border:1px solid #d1d5db;padding:8px;text-align:left;vertical-align:top;}\n"
            "    th{background:#f3f4f6;}\n"
            "    @media (max-width:768px){body{padding:14px;} h1{font-size:24px;} h2{font-size:20px;}}\n"
            "  </style>\n"
            "</head>\n"
            f"<body>{body}</body>\n"
            "</html>\n"
        )
    except Exception:
        pass

    lines = md_text.splitlines()
    html_parts: List[str] = []
    in_list = False

    def inline(text: str) -> str:
        rendered = html.escape(text)
        rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
        rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
        return rendered

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("<p></p>")
            continue

        if line == "---":
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("<hr/>")
            continue

        if line.startswith("# "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h1>{inline(line[2:])}</h1>")
            continue
        if line.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h2>{inline(line[3:])}</h2>")
            continue
        if line.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h3>{inline(line[4:])}</h3>")
            continue

        if line.startswith("> "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<blockquote>{inline(line[2:])}</blockquote>")
            continue

        if line.startswith("- "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{inline(line[2:])}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False
        html_parts.append(f"<p>{inline(line)}</p>")

    if in_list:
        html_parts.append("</ul>")

    body = "\n".join(html_parts)
    return (
        "<!doctype html>\n"
        "<html lang='zh-CN'>\n"
        "<head>\n"
        "  <meta charset='utf-8'/>\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1'/>\n"
        f"  <title>{html.escape(title)}</title>\n"
        "  <style>\n"
        "    body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
        "max-width:900px;margin:0 auto;padding:24px;line-height:1.75;color:#1f2937;background:#f7fafc;}\n"
        "    h1,h2,h3{line-height:1.35;color:#0f172a;}\n"
        "    h1{font-size:28px;margin-top:0;} h2{font-size:22px;margin-top:28px;} h3{font-size:18px;margin-top:20px;}\n"
        "    p,li{font-size:16px;} ul{padding-left:22px;} li{margin:6px 0;}\n"
        "    blockquote{background:#eef2ff;border-left:4px solid #6366f1;padding:10px 14px;border-radius:8px;}\n"
        "    @media (max-width:768px){body{padding:14px;} h1{font-size:24px;} h2{font-size:20px;}}\n"
        "  </style>\n"
        "</head>\n"
        f"<body>{body}</body>\n"
        "</html>\n"
    )


def export_docx_from_markdown(md_text: str, out_path: Path) -> bool:
    try:
        from docx import Document  # type: ignore
    except Exception:
        return False

    doc = Document()
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if not line:
            doc.add_paragraph("")
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
            continue
        if line.startswith("- "):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
            continue
        doc.add_paragraph(line)

    doc.save(str(out_path))
    return True


def write_outputs(
    results_dir: Path,
    user_symbol: str,
    analysis_date: str,
    yf_symbol: str,
    model: str,
    market_type: str,
    reports: Dict[str, str],
    market_snapshot: Dict[str, Any],
    news: List[Dict[str, Any]],
    decision_obj: Dict[str, Any],
    module_logs: List[str],
) -> Path:
    stock_root = results_dir / user_symbol / analysis_date
    reports_dir = stock_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in reports.items():
        (reports_dir / filename).write_text(content, encoding="utf-8")

    (reports_dir / "market_snapshot.json").write_text(
        json.dumps(market_snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (reports_dir / "news_snapshot.json").write_text(
        json.dumps(news, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (stock_root / "decision.json").write_text(
        json.dumps(decision_obj, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report_types = [
        "market_report",
        "fundamentals_report",
        "news_report",
        "research_team_decision",
        "investment_plan",
        "trader_investment_plan",
        "risk_management_decision",
        "final_trade_decision",
    ]

    metadata = {
        "stock_symbol": user_symbol,
        "normalized_symbol": yf_symbol,
        "analysis_date": analysis_date,
        "timestamp": datetime.now().isoformat(),
        "status": "completed",
        "market_type": market_type,
        "research_depth": 3,
        "analysts": ["market", "fundamentals", "news"],
        "model": model,
        "generator": "minimal_deepseek_report.py",
        "reports_count": len(report_types),
        "report_types": report_types,
    }

    (stock_root / "analysis_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 兼容原项目目录习惯
    (stock_root / "message_tool.log").write_text("\n".join(module_logs) + "\n", encoding="utf-8")

    # 便于微信/IM转发的简版输出
    share_dir = stock_root / "share"
    share_dir.mkdir(parents=True, exist_ok=True)
    share_md = build_share_markdown(
        user_symbol=user_symbol,
        analysis_date=analysis_date,
        decision_obj=decision_obj,
        reports=reports,
        market_snapshot=market_snapshot,
    )
    share_md_path = share_dir / "wechat_share.md"
    share_html_path = share_dir / "wechat_share.html"
    share_txt_path = share_dir / "wechat_share.txt"
    share_docx_path = share_dir / "wechat_share.docx"

    share_md_path.write_text(share_md, encoding="utf-8")
    share_txt_path.write_text(share_md, encoding="utf-8")
    share_html_path.write_text(
        markdown_to_simple_html(share_md, title=f"{user_symbol} 投资分析简报"),
        encoding="utf-8",
    )

    if export_docx_from_markdown(share_md, share_docx_path):
        module_logs.append(f"[{datetime.now().isoformat()}] share_docx ok path={share_docx_path}")
    else:
        module_logs.append(f"[{datetime.now().isoformat()}] share_docx skip reason=python-docx not installed")

    return stock_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeepSeek 单模型多模块股票分析工具")
    parser.add_argument("stock_symbol", help="股票代码，如 600028 / 000630 / AAPL / 0700")
    parser.add_argument(
        "--date",
        dest="analysis_date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="分析日期，默认今天 YYYY-MM-DD",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        help="DeepSeek模型，可选 deepseek-chat / deepseek-reasoner，默认 deepseek-chat",
    )
    parser.add_argument("--api-key", default="", help="DeepSeek API Key，不传则读取 DEEPSEEK_API_KEY")
    parser.add_argument(
        "--base-url",
        default=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        help="DeepSeek Base URL",
    )
    parser.add_argument(
        "--results-dir",
        default=os.getenv("TRADINGAGENTS_RESULTS_DIR", "results"),
        help="输出根目录",
    )
    parser.add_argument("--max-news", type=int, default=8, help="新闻条数上限")
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=float(os.getenv("DEEPSEEK_REQUEST_TIMEOUT", "45")),
        help="单次模型请求超时秒数，默认45秒",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("DEEPSEEK_RETRIES", "2")),
        help="单模块重试次数，默认2次",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    model_alias = {
        "chat": "deepseek-chat",
        "deepseek_chat": "deepseek-chat",
        "reasoner": "deepseek-reasoner",
        "deepseek_reasoner": "deepseek-reasoner",
    }
    args.model = model_alias.get(args.model.strip().lower(), args.model.strip())

    try:
        datetime.strptime(args.analysis_date, "%Y-%m-%d")
    except ValueError:
        raise SystemExit("--date 格式错误，应为 YYYY-MM-DD")

    api_key = args.api_key.strip() or os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("未检测到 DeepSeek API Key。请设置 DEEPSEEK_API_KEY 或传 --api-key")

    project_root = Path(__file__).resolve().parents[1]
    results_dir = Path(args.results_dir)
    if not results_dir.is_absolute():
        results_dir = project_root / results_dir

    user_symbol, yf_symbol = normalize_symbol(args.stock_symbol)

    module_logs: List[str] = []
    module_logs.append(f"[{datetime.now().isoformat()}] start symbol={user_symbol} preferred={yf_symbol} date={args.analysis_date}")

    # 1) 行情
    last_error: Exception | None = None
    symbol_used = yf_symbol
    symbols_to_try = candidate_yf_symbols(user_symbol, yf_symbol)

    market_snapshot: Dict[str, Any] | None = None
    per_symbol_retries = 2
    for idx, sym in enumerate(symbols_to_try, start=1):
        for retry in range(1, per_symbol_retries + 1):
            print(
                f"[1/6] 获取行情数据: {sym} (候选 {idx}/{len(symbols_to_try)}, 重试 {retry}/{per_symbol_retries})"
            )
            try:
                market_snapshot = fetch_market_data(sym, args.analysis_date)
                symbol_used = sym
                break
            except Exception as e:
                last_error = e
                module_logs.append(
                    f"[{datetime.now().isoformat()}] market_fetch fail symbol={sym} retry={retry}/{per_symbol_retries} err={e}"
                )
                print(f"  - 失败: {e}")
                if retry < per_symbol_retries:
                    time.sleep(2)
        if market_snapshot is not None:
            break

    if market_snapshot is None:
        raise SystemExit(f"所有候选代码都获取失败: {symbols_to_try}; 最后错误: {last_error}")

    market_type = infer_market_type(symbol_used)

    # 2) 新闻
    print(f"[2/6] 获取新闻数据: {symbol_used}")
    news = fetch_news(symbol_used, max_news=args.max_news)
    module_logs.append(f"[{datetime.now().isoformat()}] news_fetch ok count={len(news)}")

    # 3) DeepSeek多模块生成
    print(
        f"[3/6] 调用 DeepSeek 生成多模块报告 (model={args.model}, timeout={args.request_timeout}s, retries={args.retries})"
    )
    client = OpenAI(api_key=api_key, base_url=args.base_url, max_retries=0)

    data_context = build_data_context(
        user_symbol=user_symbol,
        yf_symbol=symbol_used,
        analysis_date=args.analysis_date,
        market_type=market_type,
        market_snapshot=market_snapshot,
        news=news,
    )

    reports, decision_obj = generate_reports(
        client=client,
        model=args.model,
        data_context=data_context,
        market_snapshot=market_snapshot,
        news=news,
        module_logs=module_logs,
        request_timeout=args.request_timeout,
        max_retries=args.retries,
    )

    # 4) 写文件
    print("[4/6] 写入结果目录")
    out_dir = write_outputs(
        results_dir=results_dir,
        user_symbol=user_symbol,
        analysis_date=args.analysis_date,
        yf_symbol=symbol_used,
        model=args.model,
        market_type=market_type,
        reports=reports,
        market_snapshot=market_snapshot,
        news=news,
        decision_obj=decision_obj,
        module_logs=module_logs,
    )

    # 5) 输出摘要
    print("[5/6] 生成摘要")
    print(f"  - 最终建议: {decision_obj.get('action')} | 目标区间: {decision_obj.get('target_price_range')}")

    # 6) 完成
    print("[6/6] 完成")
    print("\n✅ 生成完成")
    print(f"目录: {out_dir}")
    print(f"主报告: {out_dir / 'reports' / 'final_report.md'}")
    print(f"最终决策: {out_dir / 'reports' / 'final_trade_decision.md'}")
    print(f"转发简版(MD): {out_dir / 'share' / 'wechat_share.md'}")
    print(f"转发简版(HTML): {out_dir / 'share' / 'wechat_share.html'}")
    print(f"转发简版(Word): {out_dir / 'share' / 'wechat_share.docx'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
