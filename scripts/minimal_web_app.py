#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "minimal_deepseek_report.py"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDED_AI_TRADE_HOME = PROJECT_ROOT / "ai_trade_system"
AI_TRADE_HOME = Path(
    os.environ.get(
        "AI_TRADE_SYSTEM_HOME",
        str(EMBEDDED_AI_TRADE_HOME if EMBEDDED_AI_TRADE_HOME.exists() else (WORKSPACE_ROOT / "tools" / "ai_trade_system")),
    )
).resolve()
AI_TRADE_REPORTS_DIR = AI_TRADE_HOME / "reports"
AI_TRADE_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
AI_TRADE_DB_PATH = AI_TRADE_HOME / "data" / "db.sqlite3"
AI_STOCK_SIM_HOME = PROJECT_ROOT / "ai_stock_sim"
AI_STOCK_SIM_DB_PATH = AI_STOCK_SIM_HOME / "data" / "db.sqlite3"
AI_STOCK_SIM_LOG_DIR = AI_STOCK_SIM_HOME / "data" / "logs"
AI_STOCK_SIM_ENGINE_LOG = AI_STOCK_SIM_LOG_DIR / "engine.log"
AI_STOCK_SIM_DASHBOARD_LOG = AI_STOCK_SIM_LOG_DIR / "dashboard.log"
AI_STOCK_SIM_ENGINE_PID = AI_STOCK_SIM_HOME / "data" / "engine.pid"
AI_STOCK_SIM_DASHBOARD_PID = AI_STOCK_SIM_HOME / "data" / "dashboard.pid"
AI_STOCK_SIM_DASHBOARD_URL = "http://127.0.0.1:8610"
AI_STOCK_SIM_DASHBOARD_HEALTH_URL = "http://127.0.0.1:8610/_stcore/health"
AI_STOCK_SIM_RUNTIME_SYMBOLS = AI_STOCK_SIM_HOME / "config" / "runtime_symbols.yaml"
WEB_BUILD_TAG = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
SYMBOL_NAME_CACHE: Dict[str, str] = {}


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=64)
    mode: str = Field(default="quick")
    model: str = Field(default="deepseek-chat")
    request_timeout: float = Field(default=60.0, ge=10.0, le=600.0)
    retries: int = Field(default=2, ge=0, le=5)
    api_key: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=256)


class WatchlistRequest(BaseModel):
    symbols_text: str = Field(..., min_length=1, max_length=4000)
    mode: str = Field(default="quick")
    request_timeout: float = Field(default=120.0, ge=10.0, le=1200.0)
    retries: int = Field(default=1, ge=0, le=5)
    direction_cache_days: int = Field(default=3, ge=0, le=30)
    force_full_analysis: bool = Field(default=False)
    api_key: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=256)


class AutoPipelineRequest(BaseModel):
    scan_limit: int = Field(default=300, ge=20, le=2000)
    top_n: int = Field(default=12, ge=1, le=100)
    bar_limit: int = Field(default=120, ge=60, le=500)
    mode: str = Field(default="quick")
    request_timeout: float = Field(default=120.0, ge=10.0, le=1200.0)
    retries: int = Field(default=1, ge=0, le=5)
    direction_cache_days: int = Field(default=3, ge=0, le=30)
    execute_sim: bool = Field(default=True)
    skip_ai: bool = Field(default=False)
    force_refresh_universe: bool = Field(default=False)
    force_full_analysis: bool = Field(default=False)
    api_key: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=256)


@dataclass
class TaskState:
    task_id: str
    symbol: str
    mode: str
    model: str
    task_type: str = "single"  # single|watchlist|auto
    status: str = "queued"  # queued|running|done|failed
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""
    share_url: Optional[str] = None
    report_url: Optional[str] = None


TASKS: Dict[str, TaskState] = {}
TASK_LOCK = threading.Lock()

app = FastAPI(title="TradingAgents-CN Minimal Web")
app.mount("/results", StaticFiles(directory=str(RESULTS_DIR)), name="results")
app.mount("/ai_trade_reports", StaticFiles(directory=str(AI_TRADE_REPORTS_DIR)), name="ai_trade_reports")


def _python_bin() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"


def _workspace_python() -> str:
    candidates = [
        AI_TRADE_HOME / ".venv310" / "bin" / "python",
        AI_TRADE_HOME / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable or _python_bin()


def _latest_daily_plan() -> Optional[Path]:
    files = sorted(AI_TRADE_REPORTS_DIR.glob("daily_plan_*.md"))
    if not files:
        return None
    return files[-1]


def _latest_daily_plan_json() -> Optional[Path]:
    files = sorted(AI_TRADE_REPORTS_DIR.glob("daily_plan_*.json"))
    if not files:
        return None
    return files[-1]


def _latest_review() -> Optional[Path]:
    path = AI_TRADE_REPORTS_DIR / "paper_review.md"
    if path.exists():
        return path
    return None


def _latest_auto_candidates() -> Optional[Path]:
    files = sorted(AI_TRADE_REPORTS_DIR.glob("auto_candidates_*.md"))
    if not files:
        return None
    return files[-1]


def _latest_auto_candidates_json() -> Optional[Path]:
    files = sorted(AI_TRADE_REPORTS_DIR.glob("auto_candidates_*.json"))
    if not files:
        return None
    return files[-1]


def _read_text(path: Optional[Path]) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_json(path: Optional[Path]) -> Dict[str, object]:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _report_url(path: Optional[Path]) -> Optional[str]:
    if not path or not path.exists():
        return None
    return "/ai_trade_reports/{0}".format(path.name)


def _read_tail(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[-limit:]
    except Exception:
        return ""


def _pid_from_file(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _service_status(pid_file: Path) -> Tuple[bool, Optional[int]]:
    pid = _pid_from_file(pid_file)
    if pid and not _pid_alive(pid):
        try:
            pid_file.unlink()
        except Exception:
            pass
        return False, None
    return bool(pid), pid


def _url_healthy(url: str, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, ValueError, ConnectionResetError, OSError):
        return False


def _latest_auto_watchlist() -> Optional[Path]:
    files = sorted(AI_TRADE_REPORTS_DIR.glob("auto_watchlist_*.txt"))
    return files[-1] if files else None


def _classify_asset_type(symbol: str) -> str:
    code = str(symbol).strip()
    return "etf" if code.startswith(("1", "5")) else "stock"


def _eastmoney_secid(symbol: str) -> str:
    code = str(symbol).strip()
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    return "{0}.{1}".format(market, code)


def _fetch_eastmoney_symbol_names(symbols: List[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    pending = [str(symbol).strip() for symbol in symbols if re.fullmatch(r"\d{6}", str(symbol).strip())]
    if not pending:
        return result
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for symbol in pending:
        cached_name = SYMBOL_NAME_CACHE.get(symbol)
        if cached_name:
            result[symbol] = cached_name
            continue
        url = (
            "https://push2.eastmoney.com/api/qt/stock/get"
            "?secid={0}&ut=bd1d9ddb04089700cf9c27f6f7426281&invt=2&fltt=2&fields=f57,f58"
        ).format(_eastmoney_secid(symbol))
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        try:
            with opener.open(request, timeout=2.5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            data = payload.get("data") or {}
            name = str(data.get("f58") or "").strip()
            if name:
                SYMBOL_NAME_CACHE[symbol] = name
                result[symbol] = name
        except Exception:
            continue
    return result


def _sync_ai_stock_sim_runtime_watchlist(source_path: Optional[Path] = None) -> Tuple[bool, str]:
    watchlist_path = source_path or _latest_auto_watchlist()
    symbols: List[str] = []
    if watchlist_path and watchlist_path.exists():
        symbols = [line.strip() for line in watchlist_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not symbols:
        auto_payload = _read_json(_latest_auto_candidates_json())
        selected = auto_payload.get("selected") or []
        if isinstance(selected, list):
            symbols = [str(item.get("symbol") or "").strip() for item in selected if isinstance(item, dict) and str(item.get("symbol") or "").strip()]
    if not symbols:
        return False, "未找到最新自动选股候选池，实时模拟中心将继续沿用默认观察池。"

    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return False, "最新自动选股候选池为空，未同步到实时模拟中心。"

    stocks = [symbol for symbol in symbols if _classify_asset_type(symbol) == "stock"]
    etfs = [symbol for symbol in symbols if _classify_asset_type(symbol) == "etf"]
    lines = ["watchlist:"]
    if stocks:
        lines.append("  stocks:")
        lines.extend([f"    - {symbol}" for symbol in stocks])
    else:
        lines.append("  stocks: []")
    if etfs:
        lines.append("  etfs:")
        lines.extend([f"    - {symbol}" for symbol in etfs])
    else:
        lines.append("  etfs: []")
    lines.extend(
        [
            "blacklist: []",
            "universe:",
            "  include_stocks: true",
            "  include_etfs: true",
        ]
    )
    AI_STOCK_SIM_RUNTIME_SYMBOLS.parent.mkdir(parents=True, exist_ok=True)
    AI_STOCK_SIM_RUNTIME_SYMBOLS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, "已把最新自动选股候选池同步到实时模拟中心，共 {0} 只。".format(len(symbols))


def _read_ai_stock_sim_default_watchlist() -> List[str]:
    symbols_path = AI_STOCK_SIM_HOME / "config" / "symbols.yaml"
    if not symbols_path.exists():
        return []
    try:
        payload = yaml.safe_load(symbols_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    watchlist = payload.get("watchlist") or {}
    stocks = [str(item).strip() for item in watchlist.get("stocks", [])]
    etfs = [str(item).strip() for item in watchlist.get("etfs", [])]
    return [symbol for symbol in stocks + etfs if symbol]


def _start_background_service(
    args: List[str],
    pid_file: Path,
    log_file: Path,
    health_url: Optional[str] = None,
    health_timeout_seconds: float = 8.0,
    truncate_log: bool = False,
) -> Tuple[bool, str]:
    running, pid = _service_status(pid_file)
    if running and (not health_url or _url_healthy(health_url)):
        return True, "服务已在运行，PID={0}".format(pid)
    if running and health_url and not _url_healthy(health_url):
        _stop_background_service(pid_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if truncate_log:
        try:
            log_file.write_text("", encoding="utf-8")
        except Exception:
            pass
    env = os.environ.copy()
    pythonpath_parts = [str(PROJECT_ROOT), str(WORKSPACE_ROOT), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(part for part in pythonpath_parts if part)
    with log_file.open("a", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            args,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    if health_url:
        deadline = time.time() + health_timeout_seconds
        while time.time() < deadline:
            if _url_healthy(health_url):
                return True, "服务已启动，PID={0}".format(proc.pid)
            if proc.poll() is not None:
                break
            time.sleep(0.4)
        log_tail = _read_tail(log_file, limit=1200).strip()
        log_hint = ""
        if log_tail:
            lines = [line for line in log_tail.splitlines() if line.strip()]
            snippet = "\n".join(lines[-8:])
            log_hint = "\n最近日志:\n{0}".format(snippet)
        if proc.poll() is not None:
            return False, "服务启动失败，请查看日志。{0}".format(log_hint)
        return False, "服务进程已启动，但健康检查未通过，请查看日志。{0}".format(log_hint)
    return True, "服务已启动，PID={0}".format(proc.pid)


def _stop_background_service(pid_file: Path) -> str:
    pid = _pid_from_file(pid_file)
    if not pid:
        return "服务未运行"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        pid_file.unlink()
    except Exception:
        pass
    return "停止信号已发送"


def _cleanup_processes(pattern: str) -> None:
    try:
        subprocess.run(
            ["pkill", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def _query_sqlite_rows(db_path: Path, sql: str, params: Tuple[object, ...] = ()) -> List[Dict[str, object]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _ai_stock_sim_status_payload() -> Dict[str, object]:
    engine_running, engine_pid = _service_status(AI_STOCK_SIM_ENGINE_PID)
    dashboard_running, dashboard_pid = _service_status(AI_STOCK_SIM_DASHBOARD_PID)
    dashboard_healthy = _url_healthy(AI_STOCK_SIM_DASHBOARD_HEALTH_URL)
    if dashboard_running and not dashboard_healthy:
        dashboard_running = False
    symbol_names = _symbol_name_map()
    account_rows = _query_sqlite_rows(
        AI_STOCK_SIM_DB_PATH,
        "SELECT * FROM account_snapshots ORDER BY id DESC LIMIT 1",
    )
    positions = _query_sqlite_rows(
        AI_STOCK_SIM_DB_PATH,
        "SELECT symbol, qty, avg_cost, last_price, market_value, unrealized_pnl, can_sell_qty, updated_at FROM positions ORDER BY symbol LIMIT 10",
    )
    orders = _query_sqlite_rows(
        AI_STOCK_SIM_DB_PATH,
        "SELECT ts, symbol, side, price, qty, fee, tax, status FROM orders ORDER BY id DESC LIMIT 10",
    )
    logs = _query_sqlite_rows(
        AI_STOCK_SIM_DB_PATH,
        "SELECT ts, level, module, message FROM system_logs ORDER BY id DESC LIMIT 12",
    )
    review_files = sorted((AI_STOCK_SIM_HOME / "data" / "reports").glob("review_*.json"))
    latest_review = review_files[-1] if review_files else None
    watchlist_source = "default_config"
    watchlist_symbols: List[str] = []
    if AI_STOCK_SIM_RUNTIME_SYMBOLS.exists():
        watchlist_source = "latest_auto_watchlist"
        for line in AI_STOCK_SIM_RUNTIME_SYMBOLS.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value.startswith("- "):
                watchlist_symbols.append(value[2:].strip())
    if not watchlist_symbols:
        watchlist_symbols = _read_ai_stock_sim_default_watchlist()
    for row in positions:
        symbol = str(row.get("symbol") or "")
        row["name"] = symbol_names.get(symbol, symbol)
    for row in orders:
        symbol = str(row.get("symbol") or "")
        row["name"] = symbol_names.get(symbol, symbol)
    return {
        "bootstrap_ready": (AI_STOCK_SIM_HOME / ".venv310" / "bin" / "python").exists(),
        "db_exists": AI_STOCK_SIM_DB_PATH.exists(),
        "engine_running": engine_running,
        "engine_pid": engine_pid,
        "dashboard_running": dashboard_running,
        "dashboard_pid": dashboard_pid,
        "dashboard_url": AI_STOCK_SIM_DASHBOARD_URL,
        "dashboard_healthy": dashboard_healthy,
        "account": account_rows[0] if account_rows else {},
        "positions": positions,
        "orders": orders,
        "logs": logs,
        "engine_log_tail": _read_tail(AI_STOCK_SIM_ENGINE_LOG),
        "dashboard_log_tail": _read_tail(AI_STOCK_SIM_DASHBOARD_LOG),
        "latest_review_filename": latest_review.name if latest_review else None,
        "watchlist_source": watchlist_source,
        "watchlist_symbols": watchlist_symbols[:12],
        "watchlist_display": [
            "{0} {1}".format(symbol, symbol_names.get(symbol, symbol)).strip()
            for symbol in watchlist_symbols[:12]
        ],
    }


def _latest_share_cards(limit: int = 12) -> List[Dict[str, object]]:
    cards: List[Dict[str, object]] = []
    symbol_names = _symbol_name_map()
    for decision_path in sorted(RESULTS_DIR.glob("*/**/decision.json"), reverse=True):
        result_dir = decision_path.parent
        share_dir = result_dir / "share"
        analysis_date = result_dir.name
        symbol = result_dir.parent.name
        share_html = share_dir / "{0}_{1}_share.html".format(symbol, analysis_date)
        if not share_html.exists():
            legacy = share_dir / "wechat_share.html"
            if legacy.exists():
                share_html = legacy
            else:
                continue
        try:
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
        except Exception:
            decision = {}
        cards.append(
            {
                "symbol": symbol,
                "name": symbol_names.get(symbol, symbol),
                "analysis_date": analysis_date,
                "action": str(decision.get("action", "持有")),
                "confidence": float(decision.get("confidence", 0.0) or 0.0),
                "reasoning": str(decision.get("reasoning", "") or ""),
                "share_url": "/results/{0}/{1}/share/{2}".format(
                    symbol,
                    analysis_date,
                    share_html.name,
                ),
            }
        )
        if len(cards) >= limit:
            break
    return cards


def _latest_share_card_map(limit: int = 80) -> Dict[str, Dict[str, object]]:
    return {str(card.get("symbol") or ""): card for card in _latest_share_cards(limit=limit)}


def _extract_auto_summary(payload: Dict[str, object]) -> Dict[str, object]:
    summary = {
        "source": "暂无",
        "scan_count": 0,
        "passed_count": 0,
        "enhanced_count": 0,
        "selected_count": 0,
        "warnings_count": 0,
        "data_source_status": "暂无",
        "one_line_summary": "暂无",
    }
    if not payload:
        return summary
    inner = payload.get("summary") or {}
    summary["source"] = str(payload.get("source") or summary["source"])
    summary["scan_count"] = int(inner.get("scan_count", 0) or 0)
    summary["passed_count"] = int(inner.get("passed_count", 0) or 0)
    summary["enhanced_count"] = int(inner.get("enhanced_count", 0) or 0)
    summary["selected_count"] = int(inner.get("selected_count", 0) or 0)
    summary["warnings_count"] = len(payload.get("warnings") or [])
    summary["data_source_status"] = str(payload.get("data_source_status") or summary["data_source_status"])
    summary["one_line_summary"] = str(payload.get("one_line_summary") or summary["one_line_summary"])
    return summary


def _latest_plan_item_map() -> Dict[str, Dict[str, object]]:
    payload = _read_json(_latest_daily_plan_json())
    items = payload.get("items") or []
    if not isinstance(items, list):
        return {}
    result: Dict[str, Dict[str, object]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        if ticker:
            result[ticker] = item
    return result


def _card_status_tag(plan_item: Dict[str, object]) -> Tuple[str, str]:
    action = str(plan_item.get("action") or "")
    risk_state = str(plan_item.get("risk_state") or "")
    approved_qty = int(plan_item.get("approved_qty", 0) or 0)
    risk_notes = str(plan_item.get("risk_notes") or "")
    if action in ("buy", "sell") and risk_state in ("ALLOW", "REDUCE_POSITION") and approved_qty > 0:
        return "可执行", "这只票当前满足执行条件，可优先查看交易计划。"
    if action == "hold":
        return "观察", "这只票当前主要用于观察，不建议今天直接新开仓。"
    if action == "sell" and ("No sellable quantity" in risk_notes or "持仓" in str(plan_item.get("reason") or "")):
        return "仅持仓者处理", "这类信号主要针对已有持仓者，空仓用户不用处理。"
    if risk_state == "REJECT":
        return "风控拦截", "这只票有交易意图，但已被风控拦截。"
    return "观察", "这只票暂时没有形成可执行动作。"


def _latest_auto_cards(limit: int = 12) -> List[Dict[str, object]]:
    payload = _read_json(_latest_auto_candidates_json())
    selected = payload.get("selected") or []
    if not isinstance(selected, list):
        return []
    share_map = _latest_share_card_map(limit=120)
    plan_map = _latest_plan_item_map()
    cards: List[Dict[str, object]] = []
    auto_report_url = _report_url(_latest_auto_candidates())
    for item in selected[:limit]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "")
        metrics = item.get("metrics") or {}
        share_card = share_map.get(symbol, {})
        plan_item = plan_map.get(symbol, {})
        status_tag, status_reason = _card_status_tag(plan_item)
        cards.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or symbol),
                "score": float(item.get("score", 0.0) or 0.0),
                "stance": str(item.get("stance") or ""),
                "industry_name": str(metrics.get("industry_name") or "待补"),
                "fund_flow_main_net_pct_5d": float(metrics.get("fund_flow_main_net_pct_5d", 0.0) or 0.0),
                "notice_count_3d": int(metrics.get("notice_count_3d", 0) or 0),
                "risk_notice_count_14d": int(metrics.get("risk_notice_count_14d", 0) or 0),
                "net_profit_yoy": float(metrics.get("net_profit_yoy", 0.0) or 0.0),
                "roe": float(metrics.get("roe", 0.0) or 0.0),
                "share_url": share_card.get("share_url"),
                "analysis_action": share_card.get("action"),
                "analysis_confidence": share_card.get("confidence"),
                "report_url": auto_report_url,
                "status_tag": status_tag,
                "status_reason": status_reason,
            }
        )
    return cards


def _clean_symbol_name(name: str, symbol: str) -> str:
    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*\(\s*%s(?:\.[A-Z]+)?\s*\)" % re.escape(symbol), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[（(]\s*%s(?:\.[A-Z]+)?\s*[)）]\s*" % re.escape(symbol), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(技术分析报告\s*[-:：]\s*)", "", cleaned)
    cleaned = re.sub(r"(基本面分析报告|投资分析简报)$", "", cleaned).strip(" -:：")
    return cleaned.strip()


def _guess_symbol_name_from_result_dir(symbol: str, result_dir: Path) -> str:
    candidate_files = [
        result_dir / "reports" / "market_report.md",
        result_dir / "reports" / "fundamentals_report.md",
        result_dir / "share" / "{0}_{1}_share.html".format(symbol, result_dir.name),
    ]
    patterns = [
        r"技术分析报告\s*[-:：]\s*([^\n(（]+)\s*[（(]\s*%s(?:\.[A-Z]+)?\s*[)）]" % re.escape(symbol),
        r"#\s*([^\n（(]+)\s*[（(]\s*%s(?:\.[A-Z]+)?\s*[)）]" % re.escape(symbol),
        r"公司名称[：:]\s*([^\n(（]+)",
        r"<h1[^>]*>\s*([^\n<（(]+)\s*[（(]\s*%s(?:\.[A-Z]+)?\s*[)）]" % re.escape(symbol),
    ]
    for candidate in candidate_files:
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")[:8000]
        except Exception:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            cleaned = _clean_symbol_name(match.group(1), symbol)
            if cleaned and cleaned != symbol:
                return cleaned
    return ""


def _symbol_name_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    market_cache_dir = AI_STOCK_SIM_HOME / "data" / "cache" / "market"
    for cache_path in sorted(market_cache_dir.glob("snapshot_combined_*.json"), reverse=True):
        payload = _read_json(cache_path)
        rows = payload.get("rows") or []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "")
                name = str(row.get("name") or "")
                if symbol and name and symbol not in mapping:
                    mapping[symbol] = name
        if mapping:
            break
    payload = _read_json(_latest_auto_candidates_json())
    selected = payload.get("selected") or []
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            name = str(item.get("name") or "")
            if symbol and name and symbol not in mapping:
                mapping[symbol] = name
    decision_paths = sorted(RESULTS_DIR.glob("*/**/decision.json"), reverse=True)
    unresolved_symbols = [decision_path.parent.parent.name for decision_path in decision_paths if decision_path.parent.parent.name not in mapping]
    mapping.update(_fetch_eastmoney_symbol_names(unresolved_symbols))
    for decision_path in decision_paths:
        result_dir = decision_path.parent
        symbol = result_dir.parent.name
        if symbol in mapping:
            continue
        guessed_name = _guess_symbol_name_from_result_dir(symbol, result_dir)
        if guessed_name:
            mapping[symbol] = guessed_name
    return mapping


def _run_workspace_command(
    args: List[str],
    timeout: int = 300,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str]:
    env = os.environ.copy()
    pythonpath_parts = [str(PROJECT_ROOT), str(WORKSPACE_ROOT)]
    existing = env.get("PYTHONPATH", "")
    if existing:
        pythonpath_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(part for part in pythonpath_parts if part)
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    completed = subprocess.run(
        args,
        cwd=str(WORKSPACE_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout[-50000:]


def _stream_workspace_command(
    task_id: str,
    args: List[str],
    timeout: int = 300,
    extra_env: Optional[Dict[str, str]] = None,
) -> int:
    env = os.environ.copy()
    pythonpath_parts = [str(PROJECT_ROOT), str(WORKSPACE_ROOT)]
    existing = env.get("PYTHONPATH", "")
    if existing:
        pythonpath_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(part for part in pythonpath_parts if part)
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

    start_ts = time.time()
    proc = subprocess.Popen(
        args,
        cwd=str(WORKSPACE_ROOT),
        env=env,
        stdout=subprocess.PIPE,  # type: ignore[arg-type]
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_output(task_id, line)
            if time.time() - start_ts > timeout:
                proc.kill()
                _append_output(task_id, "\n[watchlist] 超时终止\n")
                break
    except Exception as exc:
        _append_output(task_id, "\n[watchlist] 读取输出异常: {0}\n".format(exc))

    proc.wait()
    return int(proc.returncode)


def _extract_plan_summary(content: str) -> Dict[str, object]:
    summary = {
        "buy_count": 0,
        "sell_count": 0,
        "hold_count": 0,
        "actionable_count": 0,
        "conclusion": "暂无",
    }
    if not content:
        return summary

    patterns = {
        "buy_count": r"- 买入信号：(\d+)",
        "sell_count": r"- 卖出信号：(\d+)",
        "hold_count": r"- 观察信号：(\d+)",
        "actionable_count": r"- 可执行信号：(\d+)",
        "conclusion": r"- 今日结论：(.+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if not match:
            continue
        value = match.group(1).strip()
        summary[key] = int(value) if key.endswith("_count") else value
    return summary


def _extract_review_summary(content: str) -> Dict[str, object]:
    summary = {
        "total_trades": 0,
        "win_rate": "0.00%",
        "max_drawdown": "0.00%",
        "total_return": "0.00%",
        "conclusion": "暂无",
    }
    if not content:
        return summary

    patterns = {
        "total_trades": r"总成交笔数：(\d+)",
        "win_rate": r"胜率：([0-9.]+%)",
        "max_drawdown": r"最大回撤：([0-9.]+%)",
        "total_return": r"累计收益率：([0-9.]+%)",
        "conclusion": r"结论：(.+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if not match:
            continue
        value = match.group(1).strip()
        summary[key] = int(value) if key == "total_trades" else value
    return summary


def _append_output(task_id: str, text: str) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.output = (task.output + text)[-50000:]


def _run_task(task_id: str, req: AnalyzeRequest) -> None:
    with TASK_LOCK:
        task = TASKS[task_id]
        task.status = "running"
        task.started_at = datetime.now().isoformat()

    analysis_date = datetime.now().strftime("%Y-%m-%d")
    cmd = [
        _python_bin(),
        str(SCRIPT_PATH),
        req.symbol.strip(),
        "--date",
        analysis_date,
        "--mode",
        req.mode.strip(),
        "--model",
        req.model.strip(),
        "--request-timeout",
        str(req.request_timeout),
        "--retries",
        str(req.retries),
    ]
    if req.api_key.strip():
        cmd.extend(["--api-key", req.api_key.strip()])
    if req.base_url.strip():
        cmd.extend(["--base-url", req.base_url.strip()])

    env = os.environ.copy()
    # 若没有导出，尝试读项目 .env
    if not env.get("DEEPSEEK_API_KEY") and not req.api_key.strip():
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if raw.startswith("DEEPSEEK_API_KEY="):
                    key = raw.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        env["DEEPSEEK_API_KEY"] = key
                        break

    if not env.get("DEEPSEEK_API_KEY") and not req.api_key.strip():
        with TASK_LOCK:
            task = TASKS[task_id]
            task.status = "failed"
            task.error = "未设置 DEEPSEEK_API_KEY（可在页面填写或配置 .env）"
            task.finished_at = datetime.now().isoformat()
        return

    env["PYTHONUNBUFFERED"] = "1"
    max_task_seconds = int(os.getenv("MINIMAL_TASK_MAX_SECONDS", "1800"))
    start_ts = time.time()

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,  # type: ignore[arg-type]
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    _append_output(
        task_id,
        f"[web] 任务开始: {req.symbol.strip().upper()} mode={req.mode} model={req.model}\n",
    )

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_output(task_id, line)
            if time.time() - start_ts > max_task_seconds:
                proc.kill()
                _append_output(task_id, f"\n[web] 超时终止: 超过 {max_task_seconds} 秒\n")
                break
    except Exception as e:
        _append_output(task_id, f"\n[web] 读取子进程输出异常: {e}\n")

    proc.wait()

    symbol = req.symbol.strip().upper()
    share_filename = f"{symbol}_{analysis_date}_share.html"
    share_rel = f"/results/{symbol}/{analysis_date}/share/{share_filename}"
    share_abs = RESULTS_DIR / symbol / analysis_date / "share" / share_filename
    legacy_share_rel = f"/results/{symbol}/{analysis_date}/share/wechat_share.html"
    legacy_share_abs = RESULTS_DIR / symbol / analysis_date / "share" / "wechat_share.html"

    with TASK_LOCK:
        task = TASKS[task_id]
        task.exit_code = proc.returncode
        task.finished_at = datetime.now().isoformat()
        if proc.returncode == 0 and share_abs.exists():
            task.status = "done"
            task.share_url = share_rel
        elif proc.returncode == 0 and legacy_share_abs.exists():
            task.status = "done"
            task.share_url = legacy_share_rel
        else:
            task.status = "failed"
            task.error = "分析失败，请查看日志输出"


def _run_watchlist_task(task_id: str, req: WatchlistRequest) -> None:
    with TASK_LOCK:
        task = TASKS[task_id]
        task.status = "running"
        task.started_at = datetime.now().isoformat()

    analysis_date = datetime.now().strftime("%Y-%m-%d")
    cmd = [
        _workspace_python(),
        "-m",
        "ai_trade_system.scripts.run_watchlist",
        "--symbols",
    ]
    symbols = [line.strip().upper() for line in req.symbols_text.splitlines() if line.strip()]
    cmd.extend(symbols)
    cmd.extend(
        [
            "--date",
            analysis_date,
            "--mode",
            req.mode.strip(),
            "--request-timeout",
            str(int(req.request_timeout)),
            "--retries",
            str(req.retries),
            "--direction-cache-days",
            str(req.direction_cache_days),
        ]
    )
    if req.force_full_analysis:
        cmd.append("--force-full-analysis")

    extra_env = {}
    if req.api_key.strip():
        extra_env["DEEPSEEK_API_KEY"] = req.api_key.strip()
    if req.base_url.strip():
        extra_env["DEEPSEEK_BASE_URL"] = req.base_url.strip()
    for proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        extra_env[proxy_key] = None
    _append_output(
        task_id,
        "[watchlist] 开始批量分析，共 {0} 只，模式={1}，方向缓存={2}天，强制全量={3}\n".format(
            len(symbols),
            req.mode.strip(),
            req.direction_cache_days,
            "是" if req.force_full_analysis else "否",
        ),
    )
    per_symbol_budget = int(req.request_timeout) * (6 * max(1, req.retries)) + 45
    total_budget = max(300, per_symbol_budget * max(1, len(symbols)))
    _append_output(
        task_id,
        "[watchlist] 预计超时预算约 {0} 秒（单票预算 {1} 秒）\n".format(total_budget, per_symbol_budget),
    )

    try:
        code = _stream_workspace_command(
            task_id,
            cmd,
            timeout=total_budget,
            extra_env=extra_env,
        )
    except subprocess.TimeoutExpired:
        with TASK_LOCK:
            task = TASKS[task_id]
            task.status = "failed"
            task.error = "股票池批量分析超时"
            task.finished_at = datetime.now().isoformat()
        return

    plan_path = _latest_daily_plan()
    with TASK_LOCK:
        task = TASKS[task_id]
        task.exit_code = code
        task.finished_at = datetime.now().isoformat()
        if code == 0:
            task.status = "done"
            task.report_url = _report_url(plan_path)
        else:
            task.status = "failed"
            task.error = "股票池批量分析失败，请查看日志输出"


def _run_auto_pipeline_task(task_id: str, req: AutoPipelineRequest) -> None:
    with TASK_LOCK:
        task = TASKS[task_id]
        task.status = "running"
        task.started_at = datetime.now().isoformat()

    analysis_date = datetime.now().strftime("%Y-%m-%d")
    cmd = [
        _workspace_python(),
        "-m",
        "ai_trade_system.scripts.run_auto_pipeline",
        "--trade-date",
        analysis_date,
        "--scan-limit",
        str(req.scan_limit),
        "--top-n",
        str(req.top_n),
        "--bar-limit",
        str(req.bar_limit),
        "--mode",
        req.mode.strip(),
        "--request-timeout",
        str(int(req.request_timeout)),
        "--retries",
        str(req.retries),
        "--direction-cache-days",
        str(req.direction_cache_days),
    ]
    if req.execute_sim:
        cmd.append("--execute-sim")
    if req.skip_ai:
        cmd.append("--skip-ai")
    if req.force_refresh_universe:
        cmd.append("--force-refresh-universe")
    if req.force_full_analysis:
        cmd.append("--force-full-analysis")

    extra_env = {}
    if req.api_key.strip():
        extra_env["DEEPSEEK_API_KEY"] = req.api_key.strip()
    if req.base_url.strip():
        extra_env["DEEPSEEK_BASE_URL"] = req.base_url.strip()
    for proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        extra_env[proxy_key] = None

    per_symbol_budget = int(req.request_timeout) * (6 * max(1, req.retries)) + 45
    total_budget = max(420, 180 + per_symbol_budget * max(1, req.top_n))
    _append_output(
        task_id,
        "[auto] 开始自动选股，扫描={0}，候选={1}，模式={2}，模拟执行={3}\n".format(
            req.scan_limit,
            req.top_n,
            req.mode.strip(),
            "是" if req.execute_sim else "否",
        ),
    )
    _append_output(
        task_id,
        "[auto] 超时预算约 {0} 秒，AI阶段单票预算 {1} 秒\n".format(total_budget, per_symbol_budget),
    )

    try:
        code = _stream_workspace_command(
            task_id,
            cmd,
            timeout=total_budget,
            extra_env=extra_env,
        )
    except subprocess.TimeoutExpired:
        with TASK_LOCK:
            task = TASKS[task_id]
            task.status = "failed"
            task.error = "自动选股流水线超时"
            task.finished_at = datetime.now().isoformat()
        return

    report_path = _latest_auto_candidates()
    sync_ok = False
    sync_message = ""
    if code == 0:
        sync_ok, sync_message = _sync_ai_stock_sim_runtime_watchlist()
        if sync_message:
            _append_output(task_id, "[auto] {0}\n".format(sync_message))
    with TASK_LOCK:
        task = TASKS[task_id]
        task.exit_code = code
        task.finished_at = datetime.now().isoformat()
        if code == 0:
            task.status = "done"
            task.report_url = _report_url(report_path)
        else:
            task.status = "failed"
            task.error = "自动选股流水线失败，请查看日志输出"


@app.get("/health")
def health(response: Response) -> Dict[str, str]:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0" />
  <meta http-equiv="Pragma" content="no-cache" />
  <meta http-equiv="Expires" content="0" />
  <title>股票分析（极简版）</title>
  <style>
    :root{--bg:#f5f7fb;--panel:#ffffff;--line:#dbe4f0;--text:#10233f;--muted:#607089;--brand:#2056d8;--brand-soft:#eaf1ff;--green:#0f9f6e;--amber:#b7791f}
    body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;max-width:760px;margin:0 auto;padding:12px;background:linear-gradient(180deg,#f4f7fb 0%,#eef3f9 100%);color:var(--text);font-size:17px;line-height:1.65}
    .card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:14px;box-shadow:0 10px 32px rgba(15,23,42,.06);width:100%;max-width:680px;margin:0 auto}
    input,select,button{width:100%;padding:11px 12px;font-size:17px;border:1px solid #cbd5e1;border-radius:10px;box-sizing:border-box}
    button{background:var(--brand);color:#fff;border:none;font-weight:600;cursor:pointer}
    button:disabled{opacity:.5;cursor:not-allowed}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .row3{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .stack{display:grid;gap:12px}
    pre{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px;overflow:auto;max-height:320px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font-size:14px;line-height:1.55;box-sizing:border-box;width:100%;max-width:100%}
    .ok{color:#16a34a;font-weight:700}
    .err{color:#dc2626;font-weight:700}
    .muted{color:var(--muted)}
    .toolbar{display:flex;gap:10px;flex-wrap:wrap}
    .toolbar button{width:auto;padding:10px 16px}
    .grid2{display:grid;grid-template-columns:1fr;gap:14px}
    .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
    .mini{background:#f6f9ff;border:1px solid #c9d8fb;border-radius:14px;padding:12px}
    .mini h4{margin:0 0 8px 0}
    .share-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
    .share-card{background:#fff8ef;border:1px solid #f7d8b2;border-radius:14px;padding:12px}
    .share-card h4{margin:0 0 6px 0}
    .share-card p{margin:6px 0;font-size:14px}
    .auto-card{background:#f3fcf7;border:1px solid #c8eedb;border-radius:14px;padding:12px}
    .auto-card h4{margin:0 0 6px 0}
    .auto-card p{margin:6px 0;font-size:14px}
    .hero{background:linear-gradient(135deg,#0f2343 0%,#2056d8 60%,#4b89ff 100%);color:#fff;border:none}
    .hero h1{margin:0 0 8px 0;font-size:30px;line-height:1.25}
    .hero p{margin:0;color:#dbe7ff;max-width:640px;line-height:1.75;font-size:16px}
    .hero-grid{display:grid;grid-template-columns:1fr;gap:12px;align-items:stretch}
    .step-grid{display:grid;grid-template-columns:1fr;gap:8px;margin-top:12px}
    .step-card{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);border-radius:14px;padding:12px;max-width:620px}
    .step-card strong{display:block;margin-bottom:6px}
    .hero-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
    .hero-actions a{display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border-radius:999px;font-weight:600;text-decoration:none}
    .hero-actions .primary{background:#fff;color:#12336a}
    .hero-actions .ghost{background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.2)}
    .flow-card{background:#ffffffcc;border:1px solid rgba(255,255,255,.24);border-radius:16px;padding:12px;color:#0f2343;max-width:620px}
    .flow-card h3{margin:0 0 10px 0}
    .flow-list{display:grid;gap:8px}
    .flow-item{background:#f4f7ff;border-radius:12px;padding:10px}
    .badge{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;background:var(--brand-soft);color:var(--brand);font-size:13px;font-weight:700}
    .section-title{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}
    .section-title h3,.section-title h4{margin:0}
    .hint{background:#f8fbff;border:1px dashed #b8caf1;border-radius:14px;padding:12px 14px;line-height:1.75;font-size:15px}
    .subtle{font-size:15px;color:var(--muted);line-height:1.7}
    details{border:1px solid var(--line);border-radius:16px;padding:14px;background:#fcfdff}
    details summary{cursor:pointer;font-weight:700;list-style:none}
    details summary::-webkit-details-marker{display:none}
    .pill-row{display:flex;gap:10px;flex-wrap:wrap}
    .pill{background:#f1f5fb;border:1px solid var(--line);border-radius:999px;padding:8px 12px;font-size:13px;color:#36506f}
    .result-strip{display:grid;grid-template-columns:1fr;gap:10px;margin-bottom:14px}
    .result-main{background:#f7fbff;border:1px solid #cfe0fb;border-radius:16px;padding:12px}
    .result-main h4,.result-side h4{margin:0 0 8px 0}
    .result-side{background:#fffdf6;border:1px solid #f3dfac;border-radius:16px;padding:12px}
    .action-note{background:#f6f9ff;border:1px dashed #b9caef;border-radius:14px;padding:12px 14px;line-height:1.8;font-size:15px}
    textarea{width:100%;min-height:112px;padding:10px 12px;font-size:16px;border:1px solid #cbd5e1;border-radius:10px;box-sizing:border-box;font-family:inherit}
    a{color:#2563eb;text-decoration:none}
    .compact{max-width:620px}
    .measure,.measure-wide,.fit-grid,.fit-box,.preview-box{max-width:100%}
    .content-col{max-width:640px}
    .row.measure,.row3.measure,.grid2.measure,.grid3.measure{max-width:100%}
    .toolbar.measure{max-width:100%}
    .preview-box{max-height:220px}
    .stack > details{width:100%;max-width:680px;margin:0 auto}
    @media (max-width: 980px){
      .hero-grid,.grid2,.grid3,.row,.row3,.share-grid,.step-grid,.result-strip{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
  <div class="stack">
    <div id="pageErrorBanner" class="err" style="display:none"></div>
    <div class="muted" style="margin:6px 0 0 0;font-size:13px">页面版本：__WEB_BUILD_TAG__</div>
    <div class="card hero">
      <div class="hero-grid">
        <div class="content-col">
          <span class="badge">推荐入口：先自动选股，再看计划，最后点分享页</span>
          <h1>TradingAgents-CN 盘后选股工作台</h1>
          <p>这套页面的目标不是把所有功能同时摊开，而是让用户按一条清晰路径走完：收盘后自动选股，AI 分析候选股，生成次日交易计划，最后在卡片里直接打开分享页查看。</p>
          <div class="step-grid content-col">
            <div class="step-card">
              <strong>步骤 1</strong>
              先填写 API Key，默认就能跑推荐流程。
            </div>
            <div class="step-card">
              <strong>步骤 2</strong>
              点“自动选股并生成计划”，系统会自己挑股票。
            </div>
            <div class="step-card">
              <strong>步骤 3</strong>
              完成后先看候选卡片，再看交易计划和模拟盘结果。
            </div>
            <div class="step-card">
              <strong>步骤 4</strong>
              最后直接点卡片里的“打开分享页”。
            </div>
          </div>
          <div class="hero-actions content-col">
            <a class="primary" href="#autoFlow">开始推荐流程</a>
            <a class="ghost" href="#tradeCenter">查看计划与复盘</a>
            <a class="ghost" href="#manualTools">手动分析工具</a>
          </div>
        </div>
        <div class="flow-card content-col">
          <h3>第一次使用就按这个来</h3>
          <div class="flow-list">
            <div class="flow-item"><strong>默认模式</strong><br>推荐使用 `quick + 自动计划 + 模拟执行`，第一次更容易看到完整结果。</div>
            <div class="flow-item"><strong>何时用 deep</strong><br>只在候选数量不多、你愿意多等几分钟时再切到 `deep`。</div>
            <div class="flow-item"><strong>手动工具</strong><br>单股和股票池批量分析放在下方“高级工具”里，不影响主流程。</div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="section-title">
        <h3>全局配置</h3>
        <span class="badge">只填一次，下面流程都会复用</span>
      </div>
      <div class="hint content-col">
        推荐做法：先在这里填好 `API Key` 和 `Base URL`，然后直接使用下方的“自动选股与生成计划”。如果你只是想单独分析某只股票，再打开页面底部的高级工具。
      </div>
      <div class="row content-col" style="margin-top:12px">
        <div>
          <label>API Key（必填）</label>
          <input id="apiKey" type="password" placeholder="sk-..." />
        </div>
        <div>
          <label>Base URL</label>
          <select id="baseUrl">
            <option value="https://api.deepseek.com" selected>DeepSeek 官方（推荐）</option>
            <option value="https://api.deepseek.com/v1">DeepSeek 兼容 /v1</option>
            <option value="https://newapi.baosiapi.com/v1">OpenAI 中转示例（newapi.baosiapi.com）</option>
          </select>
        </div>
      </div>
      <div class="pill-row" style="margin-top:12px">
        <span class="pill">适合个人：收盘后选股</span>
        <span class="pill">次日计划：人工执行</span>
        <span class="pill">系统职责：AI 分析 + 模拟盘验证</span>
      </div>
    </div>

    <div class="card" id="autoFlow">
      <div class="section-title">
        <h3>步骤 1：自动选股与生成计划</h3>
        <span class="badge">主入口</span>
      </div>
      <p class="subtle content-col">这是默认推荐流程。系统会先自动扫描股票池，再做规则筛选和 AI 分析，最后生成交易计划与模拟盘结果。</p>
      <div class="row3 content-col" style="margin-top:10px">
        <div>
          <label>扫描数量</label>
          <input id="autoScanLimit" type="number" value="300" />
        </div>
        <div>
          <label>AI 候选数</label>
          <input id="autoTopN" type="number" value="12" />
        </div>
        <div>
          <label>日线根数</label>
          <input id="autoBarLimit" type="number" value="120" />
        </div>
      </div>
      <div class="row3 content-col" style="margin-top:10px">
        <div>
          <label>分析模式</label>
          <select id="autoMode">
            <option value="quick" selected>quick（推荐，更适合日常）</option>
            <option value="deep">deep（更慢，更适合少量候选）</option>
          </select>
        </div>
        <div>
          <label>执行方式</label>
          <select id="autoRunMode">
            <option value="simulate" selected>自动计划 + 模拟执行</option>
            <option value="plan">只生成计划</option>
            <option value="select_only">只做自动选股</option>
          </select>
        </div>
        <div>
          <label>单只超时(秒)</label>
          <input id="autoTimeout" type="number" value="120" />
        </div>
      </div>
      <button id="runAutoPipeline" type="button" style="margin-top:12px">自动选股并生成计划</button>
      <p id="autoStatus"></p>
      <p id="autoLink"></p>
      <pre id="autoLog" class="preview-box"></pre>
      <div class="grid2 content-col" style="margin-top:16px">
        <div>
          <h4>最新自动选股报告</h4>
          <p id="autoMeta" class="muted"></p>
          <p id="autoReportLinks"></p>
          <pre id="autoPreview" class="preview-box"></pre>
        </div>
        <div class="mini">
          <h4>自动选股摘要</h4>
          <div id="autoSummary" class="muted">暂无自动选股摘要</div>
        </div>
      </div>
      <div style="margin-top:16px">
        <h4>步骤 2：候选卡片</h4>
        <p class="muted">这里是你最该看的区域。先看候选分数和增强维度，再直接打开分享页。</p>
        <div id="autoCards" class="share-grid"></div>
      </div>
    </div>

    <div class="card" id="tradeCenter">
      <div class="section-title">
        <h3>步骤 3：交易计划、模拟盘与复盘</h3>
        <span class="badge">执行结果</span>
      </div>
      <p class="muted content-col">当自动选股和 AI 分析跑完后，这里会自动刷新成结果页。大多数情况下你不需要手动点按钮，只需要看结论、看计划、看候选卡片，再决定是否人工下单。</p>
      <div class="result-strip">
        <div class="result-main">
          <h4>你现在最该看什么</h4>
          <div class="action-note">
            1. 先看“今日结论”，判断今天有没有可执行机会。<br>
            2. 如果有可执行信号，再看下面的交易计划细节。<br>
            3. 模拟盘和复盘主要是验证系统，不是让你再手动操作一遍。<br>
            4. 如果今天结论是“无需下单”，就不用纠结下面那些按钮。
          </div>
        </div>
        <div class="result-side">
          <h4>这些按钮什么时候才需要点</h4>
          <div class="subtle">
            只有在以下情况才需要手动使用：<br>
            - 你改了参数，想重新生成计划<br>
            - 你补跑一次模拟盘<br>
            - 页面结果没有自动刷新，需要手动同步
          </div>
        </div>
      </div>
      <div class="grid3">
        <div class="mini">
          <h4>交易计划是什么</h4>
          <div class="muted">把 AI 分析转成次日可执行清单，重点看买卖方向、建议数量、止损止盈和今日结论。</div>
        </div>
        <div class="mini">
          <h4>模拟执行是什么</h4>
          <div class="muted">不连券商实盘，只在本地账户里按规则撮合，用来验证 AI 信号和风控是否靠谱。</div>
        </div>
        <div class="mini">
          <h4>复盘报告怎么看</h4>
          <div class="muted">主要看总成交、胜率、回撤、累计收益率。如果还是 0，通常说明最近信号都是“观察”。</div>
        </div>
      </div>
      <div class="row3 content-col">
        <div>
          <label>计划日期</label>
          <input id="tradeDate" type="date" />
        </div>
        <div>
          <label>导入条数</label>
          <input id="planLimit" type="number" value="20" />
        </div>
        <div>
          <label>执行模式</label>
          <select id="simMode">
            <option value="plan">只重生成计划</option>
            <option value="simulate">重生成计划并补跑模拟盘</option>
          </select>
        </div>
      </div>
      <details style="margin-top:14px">
        <summary>高级操作：手动重跑计划 / 模拟盘 / 复盘</summary>
        <div class="subtle" style="margin-top:10px">如果自动流程已经跑完，通常不用再点这里。只有在你确认结果没刷新，或者想手动补跑一次时再使用。</div>
        <div class="toolbar" style="margin-top:12px">
          <button id="runPlan" type="button">重生成交易计划</button>
          <button id="runSim" type="button">重生成计划并补跑模拟盘</button>
          <button id="runReview" type="button">重生成复盘报告</button>
          <button id="refreshReports" type="button">只刷新当前结果</button>
        </div>
        <p id="opsStatus" class="muted"></p>
          <pre id="opsLog" class="preview-box"></pre>
      </details>
      <div class="grid2" style="margin-bottom:16px">
        <div class="mini">
          <h4>当前计划摘要</h4>
          <div id="planSummary" class="muted">暂无计划摘要</div>
        </div>
        <div class="mini">
          <h4>当前复盘摘要</h4>
          <div id="reviewSummary" class="muted">暂无复盘摘要</div>
        </div>
      </div>
      <div class="grid2">
        <div>
          <h4>最新交易计划</h4>
          <p id="planMeta" class="muted"></p>
          <p id="planLinks"></p>
          <pre id="planPreview" class="preview-box"></pre>
        </div>
        <div>
          <h4>最新复盘报告</h4>
          <p id="reviewMeta" class="muted"></p>
          <p id="reviewLinks"></p>
          <pre id="reviewPreview" class="preview-box"></pre>
        </div>
      </div>
      <div style="margin-top:16px">
        <h4>最近分析卡片</h4>
        <p class="muted">如果你走的是手动分析流程，最后就在这里点“打开分享页”。</p>
        <div id="shareCards" class="share-grid"></div>
      </div>
      <div style="margin-top:18px">
        <h4>步骤 4：实时 AI 决策中心（沿用上方候选池）</h4>
        <p class="muted">这块不是另一套独立系统，而是把上一步自动选股得到的候选池同步到 `ai_stock_sim`，让它持续盯盘、持续做 AI 决策、持续更新模拟账户。你可以把它理解成“交易计划的实时驾驶舱”。</p>
        <div class="result-strip" style="margin-top:10px">
          <div class="result-main">
            <h4>你只需要这样用</h4>
            <div class="action-note">
              1. 先跑上面的“自动选股并生成计划”<br>
              2. 再点“一键启动 AI 实时决策”，系统会沿用最新候选池<br>
              2. 启动后：看下面的账户、持仓、成交和日志<br>
              3. 想看更完整的大盘：点“打开实时控制台”
            </div>
          </div>
          <div class="result-side">
            <h4>这块和上面有什么关系</h4>
            <div class="subtle">
              上面的“交易计划、模拟盘与复盘”偏盘后结果；这里偏实时决策与持续监控。默认会优先用最新自动选股候选池，没有候选池时才退回默认观察池。
            </div>
          </div>
        </div>
        <div class="toolbar">
          <button id="simStartAll" type="button">一键启动 AI 实时决策</button>
          <button id="simOpenDashboard" type="button">打开实时控制台</button>
          <button id="simRefresh" type="button">刷新状态</button>
        </div>
        <p id="simStatus" class="muted"></p>
        <p id="simLinks"></p>
        <details style="margin-top:10px">
          <summary>高级操作：初始化 / 单独启停引擎与控制台</summary>
          <div class="toolbar" style="margin-top:12px">
            <button id="simBootstrap" type="button">仅初始化 ai_stock_sim</button>
            <button id="simStartEngine" type="button">仅启动实时引擎</button>
            <button id="simStopEngine" type="button">停止实时引擎</button>
            <button id="simStartDashboard" type="button">仅启动 Streamlit 控制台</button>
            <button id="simStopDashboard" type="button">停止 Streamlit 控制台</button>
          </div>
        </details>
        <div class="grid2" style="margin-top:14px">
          <div class="mini">
            <h4>账户摘要</h4>
            <div id="simAccountSummary" class="muted">暂无账户信息</div>
          </div>
          <div class="mini">
            <h4>运行状态</h4>
            <div id="simRuntimeSummary" class="muted">暂无运行状态</div>
          </div>
        </div>
        <div class="grid2" style="margin-top:14px">
          <div>
            <h4>当前持仓</h4>
            <pre id="simPositions" class="preview-box"></pre>
          </div>
          <div>
            <h4>最近成交</h4>
            <pre id="simOrders" class="preview-box"></pre>
          </div>
        </div>
        <div class="grid2" style="margin-top:14px">
          <div>
            <h4>系统日志</h4>
            <pre id="simSystemLogs" class="preview-box"></pre>
          </div>
          <div>
            <h4>引擎日志尾部</h4>
            <pre id="simEngineLog" class="preview-box"></pre>
          </div>
        </div>
      </div>
    </div>

    <details id="manualTools">
      <summary>高级工具：单只股票分析 / 股票池批量分析</summary>
      <div class="stack" style="margin-top:16px">
        <div class="card">
          <div class="section-title">
            <h4>手动工具 A：单只股票 AI 分析</h4>
            <span class="badge">适合临时点名分析</span>
          </div>
          <label>股票代码</label>
          <input id="symbol" placeholder="例如 000630 / 600028 / 518880" />
          <p style="margin:6px 0 0;color:#64748b;font-size:13px;">这里只填股票代码，不要输入命令。示例：<code>600028</code></p>
          <div class="row3" style="margin-top:10px">
            <div>
              <label>分析模式</label>
              <select id="mode">
                <option value="quick" selected>quick（推荐，快）</option>
                <option value="deep">deep（更深度，更慢）</option>
              </select>
            </div>
            <div>
              <label>模型</label>
              <select id="model">
                <option value="deepseek-chat">deepseek-chat</option>
                <option value="deepseek-reasoner">deepseek-reasoner</option>
              </select>
            </div>
            <div>
              <label>超时(秒)</label>
              <input id="timeout" type="number" value="60" />
            </div>
          </div>
          <button id="go" type="button" style="margin-top:12px">开始单股分析</button>
          <p id="status"></p>
          <p id="link"></p>
          <pre id="log" class="preview-box"></pre>
        </div>

        <div class="card">
          <div class="section-title">
            <h4>手动工具 B：股票池批量分析</h4>
            <span class="badge">适合自定义名单</span>
          </div>
          <p class="muted">每行一个代码。适合你已经有自选股名单时批量跑，不需要一只一只点。</p>
          <textarea id="watchlist" placeholder="600028&#10;510300&#10;159915&#10;000001"></textarea>
          <div class="row3" style="margin-top:10px">
            <div>
              <label>批量模式</label>
              <select id="watchlistMode">
                <option value="quick" selected>quick（推荐）</option>
                <option value="deep">deep（更慢）</option>
              </select>
            </div>
            <div>
              <label>单只超时(秒)</label>
              <input id="watchlistTimeout" type="number" value="120" />
            </div>
            <div>
              <label>重试次数</label>
              <input id="watchlistRetries" type="number" value="1" />
            </div>
          </div>
          <button id="runWatchlist" type="button" style="margin-top:12px">批量分析股票池</button>
          <p id="watchlistStatus"></p>
          <p id="watchlistLink"></p>
          <pre id="watchlistLog" class="preview-box"></pre>
        </div>
      </div>
    </details>
  </div>

  <script>
    const go = document.getElementById('go');
    const symbol = document.getElementById('symbol');
    const mode = document.getElementById('mode');
    const model = document.getElementById('model');
    const timeout = document.getElementById('timeout');
    const apiKey = document.getElementById('apiKey');
    const baseUrl = document.getElementById('baseUrl');
    const statusEl = document.getElementById('status');
    const linkEl = document.getElementById('link');
    const logEl = document.getElementById('log');
    const watchlist = document.getElementById('watchlist');
    const watchlistMode = document.getElementById('watchlistMode');
    const watchlistTimeout = document.getElementById('watchlistTimeout');
    const watchlistRetries = document.getElementById('watchlistRetries');
    const runWatchlist = document.getElementById('runWatchlist');
    const watchlistStatus = document.getElementById('watchlistStatus');
    const watchlistLink = document.getElementById('watchlistLink');
    const watchlistLog = document.getElementById('watchlistLog');
    const autoScanLimit = document.getElementById('autoScanLimit');
    const autoTopN = document.getElementById('autoTopN');
    const autoBarLimit = document.getElementById('autoBarLimit');
    const autoMode = document.getElementById('autoMode');
    const autoRunMode = document.getElementById('autoRunMode');
    const autoTimeout = document.getElementById('autoTimeout');
    const runAutoPipeline = document.getElementById('runAutoPipeline');
    const autoStatus = document.getElementById('autoStatus');
    const autoLink = document.getElementById('autoLink');
    const autoLog = document.getElementById('autoLog');
    const autoMeta = document.getElementById('autoMeta');
    const autoReportLinks = document.getElementById('autoReportLinks');
    const autoPreview = document.getElementById('autoPreview');
    const autoSummary = document.getElementById('autoSummary');
    const autoCards = document.getElementById('autoCards');
    const tradeDate = document.getElementById('tradeDate');
    const planLimit = document.getElementById('planLimit');
    const simMode = document.getElementById('simMode');
    const runPlan = document.getElementById('runPlan');
    const runSim = document.getElementById('runSim');
    const runReview = document.getElementById('runReview');
    const refreshReports = document.getElementById('refreshReports');
    const opsStatus = document.getElementById('opsStatus');
    const opsLog = document.getElementById('opsLog');
    const planMeta = document.getElementById('planMeta');
    const planLinks = document.getElementById('planLinks');
    const planPreview = document.getElementById('planPreview');
    const planSummary = document.getElementById('planSummary');
    const reviewMeta = document.getElementById('reviewMeta');
    const reviewLinks = document.getElementById('reviewLinks');
    const reviewPreview = document.getElementById('reviewPreview');
    const reviewSummary = document.getElementById('reviewSummary');
    const tradeCenter = document.getElementById('tradeCenter');
    const shareCards = document.getElementById('shareCards');
    const pageErrorBanner = document.getElementById('pageErrorBanner');
    const simStartAll = document.getElementById('simStartAll');
    const simOpenDashboard = document.getElementById('simOpenDashboard');
    const simBootstrap = document.getElementById('simBootstrap');
    const simStartEngine = document.getElementById('simStartEngine');
    const simStopEngine = document.getElementById('simStopEngine');
    const simStartDashboard = document.getElementById('simStartDashboard');
    const simStopDashboard = document.getElementById('simStopDashboard');
    const simRefresh = document.getElementById('simRefresh');
    const simStatus = document.getElementById('simStatus');
    const simLinks = document.getElementById('simLinks');
    const simAccountSummary = document.getElementById('simAccountSummary');
    const simRuntimeSummary = document.getElementById('simRuntimeSummary');
    const simPositions = document.getElementById('simPositions');
    const simOrders = document.getElementById('simOrders');
    const simSystemLogs = document.getElementById('simSystemLogs');
    const simEngineLog = document.getElementById('simEngineLog');

    window.addEventListener('error', (event) => {
      if(pageErrorBanner){
        pageErrorBanner.style.display = 'block';
        pageErrorBanner.textContent = '页面脚本异常：' + (event.message || 'unknown error');
      }
    });

    window.addEventListener('unhandledrejection', (event) => {
      if(pageErrorBanner){
        pageErrorBanner.style.display = 'block';
        pageErrorBanner.textContent = '页面请求异常：' + String(event.reason || 'unknown rejection');
      }
    });

    function formatErrorDetail(detail){
      if(!detail) return 'unknown error';
      if(typeof detail === 'string') return detail;
      if(Array.isArray(detail)){
        return detail.map(x => x.msg || JSON.stringify(x)).join('; ');
      }
      if(typeof detail === 'object'){
        return detail.msg || JSON.stringify(detail);
      }
      return String(detail);
    }

    async function fetchJsonSafe(url, options){
      const resp = await fetch(url, options);
      const raw = await resp.text();
      let data = {};
      if(raw){
        try{
          data = JSON.parse(raw);
        }catch(_err){
          data = {detail: raw};
        }
      }
      return {resp, data};
    }

    function normalizeSymbolInput(raw){
      return (raw || '').trim().toUpperCase();
    }

    function validateSymbolInput(sym){
      // 允许示例: 600028 / 000630 / 518880 / AAPL / 0700.HK / 600028.SS
      return /^[A-Z0-9.\-]{1,20}$/.test(sym);
    }

    // 浏览器本地保存（仅当前浏览器）
    apiKey.value = localStorage.getItem('ta_min_api_key') || '';
    mode.value = localStorage.getItem('ta_min_mode') || 'quick';
    const savedBaseUrl = localStorage.getItem('ta_min_base_url');
    if(savedBaseUrl){
      const exists = Array.from(baseUrl.options).some(opt => opt.value === savedBaseUrl);
      if(exists) baseUrl.value = savedBaseUrl;
    }
    apiKey.onchange = () => localStorage.setItem('ta_min_api_key', apiKey.value.trim());
    mode.onchange = () => {
      localStorage.setItem('ta_min_mode', mode.value);
      if(mode.value === 'deep'){
        if(Number(timeout.value || 0) < 120) timeout.value = '120';
      }else{
        if(Number(timeout.value || 0) > 120) timeout.value = '60';
      }
    };
    baseUrl.onchange = () => localStorage.setItem('ta_min_base_url', baseUrl.value);
    if(mode.value === 'quick' && Number(timeout.value || 0) > 120){
      timeout.value = '60';
    }
    tradeDate.value = new Date().toISOString().slice(0, 10);

    function elapsedText(startedAt){
      if(!startedAt) return '';
      const s = Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000));
      return `（已运行 ${s}s）`;
    }

    async function poll(taskId, kind){
      let done = false;
      while(!done){
        const r = await fetch('/api/task/' + taskId);
        const data = await r.json();
        const currentStatusEl = kind === 'watchlist' ? watchlistStatus : (kind === 'auto' ? autoStatus : statusEl);
        const currentLogEl = kind === 'watchlist' ? watchlistLog : (kind === 'auto' ? autoLog : logEl);
        const currentLinkEl = kind === 'watchlist' ? watchlistLink : (kind === 'auto' ? autoLink : linkEl);
        const currentButton = kind === 'watchlist' ? runWatchlist : (kind === 'auto' ? runAutoPipeline : go);
        currentStatusEl.textContent = '状态: ' + data.status + ' ' + elapsedText(data.started_at);
        currentLogEl.textContent = data.output || '';
        currentLogEl.scrollTop = currentLogEl.scrollHeight;
        if(data.status === 'done'){
          currentStatusEl.className = 'ok';
          if(kind === 'watchlist'){
            currentLinkEl.innerHTML = data.report_url
              ? '<a href="' + data.report_url + '" target="_blank">打开最新交易计划</a>'
              : '批量分析已完成，可继续生成交易计划';
            await loadReports();
            await autoEnterTradeCenter();
          }else if(kind === 'auto'){
            currentLinkEl.innerHTML = data.report_url
              ? '<a href="' + data.report_url + '" target="_blank">打开自动选股结果</a>'
              : '自动选股已完成';
            await loadReports();
            if(autoRunMode.value !== 'select_only'){
              tradeCenter.scrollIntoView({behavior:'smooth', block:'start'});
            }
          }else{
            const htmlUrl = data.share_url;
            const docxUrl = data.share_url ? data.share_url.replace('.html', '.docx') : '';
            currentLinkEl.innerHTML =
              '<a href="' + htmlUrl + '" target="_blank">打开分享页</a>' +
              ' | <a href="' + htmlUrl + '" download>下载HTML</a>' +
              (docxUrl ? ' | <a href="' + docxUrl + '" download>下载Word</a>' : '');
            await autoEnterTradeCenter();
          }
          done = true;
          currentButton.disabled = false;
        } else if(data.status === 'failed'){
          currentStatusEl.className = 'err';
          currentLinkEl.textContent = data.error || '失败';
          done = true;
          currentButton.disabled = false;
        } else {
          await new Promise(r => setTimeout(r, 3000));
        }
      }
    }

    function renderShareCards(cards){
      if(!cards || !cards.length){
        shareCards.innerHTML = '<div class="muted">暂无可展示的分享页。</div>';
        return;
      }
      shareCards.innerHTML = cards.map(card => {
        const reason = (card.reasoning || '').slice(0, 110);
        return (
          '<div class="share-card">' +
          '<h4>' + card.symbol + ' ' + (card.name || '') + ' · ' + card.action + '</h4>' +
          '<p>日期：' + card.analysis_date + '</p>' +
          '<p>置信度：' + Math.round((card.confidence || 0) * 100) + '%</p>' +
          '<p>' + (reason || '暂无摘要') + '</p>' +
          '<p><a href="' + card.share_url + '" target="_blank">打开分享页</a></p>' +
          '</div>'
        );
      }).join('');
    }

    function renderAutoCards(cards){
      if(!cards || !cards.length){
        autoCards.innerHTML = '<div class="muted">暂无自动选股卡片。</div>';
        return;
      }
      autoCards.innerHTML = cards.map(card => {
        const confidence = card.analysis_confidence != null
          ? Math.round((card.analysis_confidence || 0) * 100) + '%'
          : '暂无';
        const shareLink = card.share_url
          ? '<a href="' + card.share_url + '" target="_blank">打开分享页</a>'
          : '';
        const reportLink = card.report_url
          ? '<a href="' + card.report_url + '" target="_blank">查看自动选股报告</a>'
          : '';
        const links = [shareLink, reportLink].filter(Boolean).join(' | ');
        return (
          '<div class="auto-card">' +
          '<h4>' + card.symbol + ' ' + card.name + '</h4>' +
          '<p><span class="badge">' + (card.status_tag || '观察') + '</span></p>' +
          '<p>分数：' + Number(card.score || 0).toFixed(2) + ' ｜ ' + (card.stance || '待定') + '</p>' +
          '<p>行业：' + (card.industry_name || '待补') + '</p>' +
          '<p>5日主力净占比：' + Number(card.fund_flow_main_net_pct_5d || 0).toFixed(2) + '%</p>' +
          '<p>近3日公告：' + (card.notice_count_3d || 0) + ' 条 ｜ 近14日风险提示：' + (card.risk_notice_count_14d || 0) + ' 条</p>' +
          '<p>净利同比：' + Number(card.net_profit_yoy || 0).toFixed(2) + '% ｜ ROE：' + Number(card.roe || 0).toFixed(2) + '%</p>' +
          '<p>' + (card.status_reason || '') + '</p>' +
          '<p>最新 AI：' + (card.analysis_action || '暂无') + ' ｜ 置信度：' + confidence + '</p>' +
          '<p>' + (links || '等待后续 AI 分析完成') + '</p>' +
          '</div>'
        );
      }).join('');
    }

    function toPrettyLines(rows, keys){
      if(!rows || !rows.length) return '暂无';
      return rows.map(row => {
        return keys.map(key => String(row[key] ?? '')).join(' | ');
      }).join('\\n');
    }

    function annotateSymbolText(text, symbolNames){
      if(!text) return text || '';
      if(!symbolNames) return text;
      return String(text).replace(/\\b\\d{6}\\b/g, (symbol, offset, fullText) => {
        const name = symbolNames[symbol];
        if(!name || name === symbol){
          return symbol;
        }
        const lookahead = fullText.slice(offset, offset + symbol.length + name.length + 4);
        if(
          lookahead.includes(symbol + ' ' + name) ||
          lookahead.includes(symbol + '·' + name) ||
          lookahead.includes(symbol + '｜' + name)
        ){
          return symbol;
        }
        return symbol + ' ' + name;
      });
    }

    async function checkBackendHealth(){
      try{
        const resp = await fetch('/health?ts=' + Date.now(), {
          cache: 'no-store',
          headers: {'Cache-Control':'no-store'}
        });
        if(!resp.ok){
          throw new Error('HTTP ' + resp.status);
        }
        if(pageErrorBanner){
          pageErrorBanner.style.display = 'none';
          pageErrorBanner.textContent = '';
        }
      }catch(err){
        if(pageErrorBanner){
          pageErrorBanner.style.display = 'block';
          pageErrorBanner.textContent = '当前页面可能是浏览器缓存页，或 8600 服务未正常运行。请回到终端重新执行 bash start.sh web，然后按 Ctrl+Shift+R 强制刷新。错误：' + String(err);
        }
      }
    }

    async function loadAiStockSimStatus(){
      try{
        const {resp, data} = await fetchJsonSafe('/api/ai-stock-sim/status');
        if(!resp.ok){
          simStatus.textContent = '读取 ai_stock_sim 状态失败：' + formatErrorDetail(data.detail);
          return;
        }
        simStatus.textContent =
          (data.bootstrap_ready ? '环境已准备好' : '还没初始化环境') +
          ' ｜ ' +
          (data.engine_running ? '实时引擎运行中' : '实时引擎未启动') +
          ' ｜ ' +
          (data.dashboard_running ? '控制台可访问' : '控制台未就绪');
        const links = [];
        if(data.dashboard_url){
          links.push('<a href="' + data.dashboard_url + '" target="_blank">打开 Streamlit 控制台</a>');
        }
        if(data.latest_review_filename){
          links.push('最新复盘：' + data.latest_review_filename);
        }
        simLinks.innerHTML = links.length ? links.join(' | ') : '<span class="muted">暂无可打开链接</span>';
        const account = data.account || {};
        const watchlistLabel = data.watchlist_source === 'latest_auto_watchlist'
          ? '最新自动选股候选池'
          : '默认观察池';
        simAccountSummary.innerHTML =
          '监控来源：' + watchlistLabel +
          '<br>当前监控：' + ((data.watchlist_display || []).join('、') || '暂无') +
          '<br>' +
          '现金：' + Number(account.cash || 0).toFixed(2) +
          '<br>总权益：' + Number(account.equity || 0).toFixed(2) +
          '<br>持仓市值：' + Number(account.market_value || 0).toFixed(2) +
          '<br>已实现盈亏：' + Number(account.realized_pnl || 0).toFixed(2) +
          '<br>浮盈亏：' + Number(account.unrealized_pnl || 0).toFixed(2) +
          '<br>回撤：' + (Number(account.drawdown || 0) * 100).toFixed(2) + '%';
        simRuntimeSummary.innerHTML =
          '数据库：' + (data.db_exists ? '已创建' : '未创建') +
          '<br>控制台健康：' + (data.dashboard_healthy ? '正常' : '未通过') +
          '<br>引擎日志：' + ((data.engine_log_tail || '').length ? '有输出' : '暂无') +
          '<br>最近系统日志条数：' + ((data.logs || []).length || 0) +
          '<br>最近持仓条数：' + ((data.positions || []).length || 0) +
          '<br>最近成交条数：' + ((data.orders || []).length || 0);
        simPositions.textContent = toPrettyLines(data.positions || [], ['symbol','name','qty','avg_cost','last_price','market_value','unrealized_pnl','can_sell_qty']);
        simOrders.textContent = toPrettyLines(data.orders || [], ['ts','symbol','name','side','price','qty','status','fee','tax']);
        simSystemLogs.textContent = toPrettyLines(data.logs || [], ['ts','level','module','message']);
        simEngineLog.textContent = data.engine_log_tail || '暂无引擎日志';
      }catch(err){
        simStatus.textContent = '读取 ai_stock_sim 状态异常：' + String(err);
      }
    }

    async function runAiStockSimAction(kind){
      const actionMap = {
        bootstrap: '/api/ai-stock-sim/bootstrap',
        startEngine: '/api/ai-stock-sim/engine/start',
        stopEngine: '/api/ai-stock-sim/engine/stop',
        startDashboard: '/api/ai-stock-sim/dashboard/start',
        stopDashboard: '/api/ai-stock-sim/dashboard/stop',
      };
      simStatus.textContent = '处理中...';
      try{
        const resp = await fetch(actionMap[kind], {method:'POST'});
        const data = await resp.json();
        if(!resp.ok){
          simStatus.textContent = '执行失败：' + formatErrorDetail(data.detail);
          return;
        }
        simStatus.textContent = data.message || '执行完成';
        await loadAiStockSimStatus();
      }catch(err){
        simStatus.textContent = '执行异常：' + String(err);
      }
    }

    async function runAiStockSimQuickStart(){
      const buttons = [
        simStartAll, simOpenDashboard, simRefresh,
        simBootstrap, simStartEngine, simStopEngine, simStartDashboard, simStopDashboard
      ].filter(Boolean);
      buttons.forEach(btn => btn.disabled = true);
      simStatus.textContent = '正在准备环境并启动实时 AI 决策...';
      try{
        let result = await fetchJsonSafe('/api/ai-stock-sim/status');
        let resp = result.resp;
        let data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }
        result = await fetchJsonSafe('/api/ai-stock-sim/sync-watchlist', {method:'POST'});
        resp = result.resp;
        data = result.data;
        if(!resp.ok){
          simStatus.textContent = '候选池同步提示：' + formatErrorDetail(data.detail);
        }else{
          simStatus.textContent = data.message || '已同步最新候选池';
        }
        if(!data.bootstrap_ready){
          result = await fetchJsonSafe('/api/ai-stock-sim/bootstrap', {method:'POST'});
          resp = result.resp;
          data = result.data;
          if(!resp.ok){
            throw new Error(formatErrorDetail(data.detail));
          }
        }
        result = await fetchJsonSafe('/api/ai-stock-sim/engine/start', {method:'POST'});
        resp = result.resp;
        data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }
        result = await fetchJsonSafe('/api/ai-stock-sim/dashboard/start', {method:'POST'});
        resp = result.resp;
        data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }
        simStatus.textContent = '实时 AI 决策中心已启动。现在它会优先沿用最新自动候选池；需要更完整页面时，再点“打开实时控制台”。';
        await loadAiStockSimStatus();
      }catch(err){
        simStatus.textContent = '一键启动失败：' + String(err);
      }finally{
        buttons.forEach(btn => btn.disabled = false);
      }
    }

    go.onclick = async () => {
      const normalizedSymbol = normalizeSymbolInput(symbol.value);
      if(!normalizedSymbol){
        alert('请输入股票代码');
        return;
      }
      if(!validateSymbolInput(normalizedSymbol)){
        alert('股票代码格式错误。请只输入代码，例如 600028 或 AAPL');
        return;
      }
      if(!apiKey.value.trim()){
        alert('请填写 API Key');
        return;
      }
      go.disabled = true;
      statusEl.className = '';
      statusEl.textContent = '提交中...';
      linkEl.textContent = '';
      logEl.textContent = '';

      const resp = await fetch('/api/analyze', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          symbol: normalizedSymbol,
          mode: mode.value,
          model: model.value,
          request_timeout: Number(timeout.value || 120),
          retries: mode.value === 'deep' ? 2 : 1,
          api_key: apiKey.value.trim(),
          base_url: baseUrl.value
        })
      });
      const data = await resp.json();
      if(!resp.ok){
        statusEl.className = 'err';
        statusEl.textContent = '提交失败';
        linkEl.textContent = formatErrorDetail(data.detail);
        go.disabled = false;
        return;
      }
      statusEl.textContent = '任务已创建: ' + data.task_id;
      poll(data.task_id, 'single');
    };

    runWatchlist.onclick = async () => {
      const rawText = (watchlist.value || '').trim();
      if(!rawText){
        alert('请至少输入一只股票代码，每行一个');
        return;
      }
      runWatchlist.disabled = true;
      watchlistStatus.className = '';
      watchlistStatus.textContent = '提交中...';
      watchlistLink.textContent = '';
      watchlistLog.textContent = '';

      const resp = await fetch('/api/watchlist', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          symbols_text: rawText,
          mode: watchlistMode.value,
          request_timeout: Number(watchlistTimeout.value || 120),
          retries: Number(watchlistRetries.value || 1),
          api_key: apiKey.value.trim(),
          base_url: baseUrl.value
        })
      });
      const data = await resp.json();
      if(!resp.ok){
        watchlistStatus.className = 'err';
        watchlistStatus.textContent = '提交失败';
        watchlistLink.textContent = formatErrorDetail(data.detail);
        runWatchlist.disabled = false;
        return;
      }
      watchlistStatus.textContent = '任务已创建: ' + data.task_id;
      poll(data.task_id, 'watchlist');
    };

    async function handleAutoPipelineClick(){
      autoStatus.className = '';
      autoStatus.textContent = '按钮已点击，正在提交任务...';
      if(!apiKey.value.trim() && autoRunMode.value !== 'select_only'){
        alert('自动选股需要复用上面的 API Key 才能进入 AI 分析阶段');
        autoStatus.textContent = '未提交：缺少 API Key';
        return;
      }
      runAutoPipeline.disabled = true;
      autoStatus.className = '';
      autoStatus.textContent = '提交中...';
      autoLink.textContent = '';
      autoLog.textContent = '';

      const resp = await fetch('/api/auto-pipeline', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          scan_limit: Number(autoScanLimit.value || 300),
          top_n: Number(autoTopN.value || 12),
          bar_limit: Number(autoBarLimit.value || 120),
          mode: autoMode.value,
          request_timeout: Number(autoTimeout.value || 120),
          retries: Number(watchlistRetries.value || 1),
          direction_cache_days: 3,
          execute_sim: autoRunMode.value === 'simulate',
          skip_ai: autoRunMode.value === 'select_only',
          api_key: apiKey.value.trim(),
          base_url: baseUrl.value
        })
      });
      const data = await resp.json();
      if(!resp.ok){
        autoStatus.className = 'err';
        autoStatus.textContent = '提交失败';
        autoLink.textContent = formatErrorDetail(data.detail);
        runAutoPipeline.disabled = false;
        return;
      }
      autoStatus.textContent = '任务已创建: ' + data.task_id;
      poll(data.task_id, 'auto');
    }

    function renderFileLinks(targetEl, fileInfo){
      if(!fileInfo || !fileInfo.url){
        targetEl.innerHTML = '<span class="muted">暂无文件</span>';
        return;
      }
      targetEl.innerHTML =
        '<a href="' + fileInfo.url + '" target="_blank">打开</a>' +
        ' | <a href="' + fileInfo.url + '" download>下载</a>';
    }

    async function loadReports(){
      const resp = await fetch('/api/ai-trade/reports');
      const data = await resp.json();
      if(!resp.ok){
        opsStatus.textContent = '读取报告失败：' + formatErrorDetail(data.detail);
        return;
      }
      const symbolNames = data.symbol_names || {};
      planMeta.textContent = data.plan && data.plan.filename ? ('文件：' + data.plan.filename) : '暂无交易计划';
      planPreview.textContent = data.plan && data.plan.content ? annotateSymbolText(data.plan.content, symbolNames) : '暂无交易计划';
      renderFileLinks(planLinks, data.plan);
      if(data.plan && data.plan.summary){
        const actionable = Number(data.plan.summary.actionable_count || 0);
        const planHeadline = actionable > 0
          ? '今天有 ' + actionable + ' 条可执行信号，优先先看下方交易计划。'
          : '今天没有可执行交易，优先看“今日结论”，通常无需手动下单。';
        const noActionReason = data.plan.summary.no_action_reason
          ? ('<br>原因：' + data.plan.summary.no_action_reason)
          : '';
        planSummary.innerHTML =
          planHeadline +
          '<br>买入信号：' + data.plan.summary.buy_count +
          '，卖出信号：' + data.plan.summary.sell_count +
          '，观察信号：' + data.plan.summary.hold_count +
          '，可执行：' + data.plan.summary.actionable_count +
          '<br>今日结论：' + data.plan.summary.conclusion +
          (actionable > 0 ? '' : noActionReason);
      }else{
        planSummary.textContent = '暂无计划摘要';
      }

      reviewMeta.textContent = data.review && data.review.filename ? ('文件：' + data.review.filename) : '暂无复盘报告';
      reviewPreview.textContent = data.review && data.review.content ? annotateSymbolText(data.review.content, symbolNames) : '暂无复盘报告';
      renderFileLinks(reviewLinks, data.review);
      if(data.review && data.review.summary){
        const totalTrades = Number(data.review.summary.total_trades || 0);
        const reviewHeadline = totalTrades > 0
          ? '这次模拟盘有成交，可以结合胜率和回撤判断信号质量。'
          : '这次模拟盘没有成交，常见原因是今天没有可执行信号，或次日也未触发成交。';
        reviewSummary.innerHTML =
          reviewHeadline +
          '<br>总成交：' + data.review.summary.total_trades +
          '，胜率：' + data.review.summary.win_rate +
          '，最大回撤：' + data.review.summary.max_drawdown +
          '，累计收益率：' + data.review.summary.total_return +
          '<br>结论：' + data.review.summary.conclusion;
      }else{
        reviewSummary.textContent = '暂无复盘摘要';
      }
      autoMeta.textContent = data.auto && data.auto.filename ? ('文件：' + data.auto.filename) : '暂无自动选股报告';
      autoPreview.textContent = data.auto && data.auto.content ? annotateSymbolText(data.auto.content, symbolNames) : '暂无自动选股报告';
      renderFileLinks(autoReportLinks, data.auto);
      if(data.auto && data.auto.summary){
        autoSummary.innerHTML =
          data.auto.summary.one_line_summary +
          '<br>数据源状态：' + data.auto.summary.data_source_status +
          '<br>股票池来源：' + data.auto.summary.source +
          '，扫描：' + data.auto.summary.scan_count +
          '，预筛选通过：' + data.auto.summary.passed_count +
          '，增强处理：' + data.auto.summary.enhanced_count +
          '，最终候选：' + data.auto.summary.selected_count;
      }else{
        autoSummary.textContent = '暂无自动选股摘要';
      }
      renderAutoCards((data.auto && data.auto.cards) || []);
      renderShareCards(data.share_cards || []);
    }

    async function runOps(kind, executeSim){
      runPlan.disabled = true;
      runSim.disabled = true;
      runReview.disabled = true;
      refreshReports.disabled = true;
      opsStatus.textContent = '处理中...';
      opsLog.textContent = '';
      try{
        let resp;
        if(kind === 'review'){
          resp = await fetch('/api/ai-trade/review', {method:'POST'});
        }else{
          resp = await fetch('/api/ai-trade/plan', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({
              limit: Number(planLimit.value || 20),
              trade_date: tradeDate.value || '',
              execute_sim: executeSim
            })
          });
        }
        const data = await resp.json();
        if(!resp.ok){
          opsStatus.textContent = '执行失败';
          opsLog.textContent = formatErrorDetail(data.detail);
        }else{
          opsStatus.textContent = data.message || '执行完成';
          opsLog.textContent = data.output || '';
          await loadReports();
        }
      }catch(err){
        opsStatus.textContent = '执行异常';
        opsLog.textContent = String(err);
      }finally{
        runPlan.disabled = false;
        runSim.disabled = false;
        runReview.disabled = false;
        refreshReports.disabled = false;
      }
    }

    async function autoEnterTradeCenter(){
      opsStatus.textContent = '分析已完成，正在自动生成交易计划与复盘...';
      await runOps('plan', simMode.value === 'simulate');
      await runOps('review', false);
      tradeCenter.scrollIntoView({behavior:'smooth', block:'start'});
    }

    window.handleAutoPipelineClick = handleAutoPipelineClick;
    runAutoPipeline.onclick = handleAutoPipelineClick;
    runPlan.onclick = () => runOps('plan', false);
    runSim.onclick = () => runOps('plan', true);
    runReview.onclick = () => runOps('review', false);
    refreshReports.onclick = () => loadReports();
    if(simStartAll) simStartAll.onclick = () => runAiStockSimQuickStart();
    if(simOpenDashboard) simOpenDashboard.onclick = () => window.open('http://127.0.0.1:8610', '_blank');
    if(simBootstrap) simBootstrap.onclick = () => runAiStockSimAction('bootstrap');
    if(simStartEngine) simStartEngine.onclick = () => runAiStockSimAction('startEngine');
    if(simStopEngine) simStopEngine.onclick = () => runAiStockSimAction('stopEngine');
    if(simStartDashboard) simStartDashboard.onclick = () => runAiStockSimAction('startDashboard');
    if(simStopDashboard) simStopDashboard.onclick = () => runAiStockSimAction('stopDashboard');
    if(simRefresh) simRefresh.onclick = () => loadAiStockSimStatus();
    checkBackendHealth();
    loadReports();
    loadAiStockSimStatus();
  </script>
</body>
</html>""".replace("__WEB_BUILD_TAG__", WEB_BUILD_TAG)
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> Dict[str, str]:
    symbol = req.symbol.strip().upper()
    mode = req.mode.strip().lower() or "quick"
    if mode not in {"quick", "deep"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 quick 或 deep")
    if not symbol:
        raise HTTPException(status_code=400, detail="股票代码不能为空")
    if not re.fullmatch(r"[A-Z0-9.\-]{1,20}", symbol):
        raise HTTPException(
            status_code=400,
            detail="股票代码格式错误。请只输入代码，例如 600028 / 000630 / 518880 / AAPL / 0700.HK",
        )
    task_id = uuid.uuid4().hex[:12]
    req.mode = mode
    state = TaskState(task_id=task_id, symbol=symbol, mode=mode, model=req.model, task_type="single")
    with TASK_LOCK:
        TASKS[task_id] = state
    thread = threading.Thread(target=_run_task, args=(task_id, req), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.post("/api/watchlist")
def watchlist(req: WatchlistRequest) -> Dict[str, str]:
    mode = req.mode.strip().lower() or "quick"
    if mode not in {"quick", "deep"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 quick 或 deep")
    if not req.api_key.strip() and not os.environ.get("DEEPSEEK_API_KEY"):
        raise HTTPException(status_code=400, detail="请先在上方填写 API Key，再运行股票池批量分析")
    lines = [line.strip().upper() for line in req.symbols_text.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="股票池不能为空")
    invalid = [line for line in lines if not re.fullmatch(r"[A-Z0-9.\-]{1,20}", line)]
    if invalid:
        raise HTTPException(status_code=400, detail="这些股票代码格式不正确：{0}".format(", ".join(invalid[:10])))
    task_id = uuid.uuid4().hex[:12]
    state = TaskState(
        task_id=task_id,
        symbol=",".join(lines[:8]),
        mode=mode,
        model="watchlist",
        task_type="watchlist",
    )
    with TASK_LOCK:
        TASKS[task_id] = state
    req.mode = mode
    thread = threading.Thread(target=_run_watchlist_task, args=(task_id, req), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.post("/api/auto-pipeline")
def auto_pipeline(req: AutoPipelineRequest) -> Dict[str, str]:
    mode = req.mode.strip().lower() or "quick"
    if mode not in {"quick", "deep"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 quick 或 deep")
    if not req.skip_ai and not req.api_key.strip() and not os.environ.get("DEEPSEEK_API_KEY"):
        raise HTTPException(status_code=400, detail="请先在上方填写 API Key，再运行自动选股流水线")
    task_id = uuid.uuid4().hex[:12]
    state = TaskState(
        task_id=task_id,
        symbol="AUTO",
        mode=mode,
        model="auto-pipeline",
        task_type="auto",
    )
    with TASK_LOCK:
        TASKS[task_id] = state
    req.mode = mode
    thread = threading.Thread(target=_run_auto_pipeline_task, args=(task_id, req), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
def get_task(task_id: str) -> Dict[str, object]:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return asdict(task)


class PlanRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    trade_date: str = Field(default="")
    execute_sim: bool = Field(default=False)


@app.get("/api/ai-trade/reports")
def get_ai_trade_reports() -> Dict[str, object]:
    plan_path = _latest_daily_plan()
    plan_json_path = _latest_daily_plan_json()
    review_path = _latest_review()
    auto_path = _latest_auto_candidates()
    auto_json_path = _latest_auto_candidates_json()
    plan_content = _read_text(plan_path)
    plan_payload = _read_json(plan_json_path)
    review_content = _read_text(review_path)
    auto_content = _read_text(auto_path)
    auto_payload = _read_json(auto_json_path)
    return {
        "plan": {
            "filename": plan_path.name if plan_path else None,
            "url": _report_url(plan_path),
            "content": plan_content,
            "summary": plan_payload.get("summary") or _extract_plan_summary(plan_content),
            "actionable_items": plan_payload.get("actionable_items") or [],
        },
        "review": {
            "filename": review_path.name if review_path else None,
            "url": _report_url(review_path),
            "content": review_content,
            "summary": _extract_review_summary(review_content),
        },
        "auto": {
            "filename": auto_path.name if auto_path else None,
            "url": _report_url(auto_path),
            "content": auto_content,
            "summary": _extract_auto_summary(auto_payload),
            "warnings": auto_payload.get("warnings") or [],
            "cards": _latest_auto_cards(),
        },
        "db_exists": AI_TRADE_DB_PATH.exists(),
        "share_cards": _latest_share_cards(),
        "symbol_names": _symbol_name_map(),
    }


@app.get("/api/ai-stock-sim/status")
def get_ai_stock_sim_status() -> Dict[str, object]:
    return _ai_stock_sim_status_payload()


@app.post("/api/ai-stock-sim/bootstrap")
def bootstrap_ai_stock_sim() -> Dict[str, object]:
    args = ["bash", str(AI_STOCK_SIM_HOME / "scripts" / "bootstrap.sh")]
    try:
        code, output = _run_workspace_command(args, timeout=1800)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="ai_stock_sim 初始化超时")
    if code != 0:
        raise HTTPException(status_code=500, detail=output or "ai_stock_sim 初始化失败")
    return {
        "message": "ai_stock_sim 初始化完成",
        "output": output,
        "status": _ai_stock_sim_status_payload(),
    }


@app.post("/api/ai-stock-sim/sync-watchlist")
def sync_ai_stock_sim_watchlist() -> Dict[str, object]:
    ok, message = _sync_ai_stock_sim_runtime_watchlist()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message, "status": _ai_stock_sim_status_payload()}


@app.post("/api/ai-stock-sim/engine/start")
def start_ai_stock_sim_engine() -> Dict[str, object]:
    _cleanup_processes(r"python -m app\.main|ai_stock_sim/scripts/run_engine\.sh")
    ok, message = _start_background_service(
        ["bash", str(AI_STOCK_SIM_HOME / "scripts" / "run_engine.sh")],
        AI_STOCK_SIM_ENGINE_PID,
        AI_STOCK_SIM_ENGINE_LOG,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return {"message": message, "status": _ai_stock_sim_status_payload()}


@app.post("/api/ai-stock-sim/engine/stop")
def stop_ai_stock_sim_engine() -> Dict[str, object]:
    message = _stop_background_service(AI_STOCK_SIM_ENGINE_PID)
    _cleanup_processes(r"python -m app\.main|ai_stock_sim/scripts/run_engine\.sh")
    return {"message": message, "status": _ai_stock_sim_status_payload()}


@app.post("/api/ai-stock-sim/dashboard/start")
def start_ai_stock_sim_dashboard() -> Dict[str, object]:
    _cleanup_processes(r"streamlit run .*dashboard/dashboard_app\.py|ai_stock_sim/scripts/run_dashboard\.sh")
    ok, message = _start_background_service(
        ["bash", str(AI_STOCK_SIM_HOME / "scripts" / "run_dashboard.sh")],
        AI_STOCK_SIM_DASHBOARD_PID,
        AI_STOCK_SIM_DASHBOARD_LOG,
        health_url=AI_STOCK_SIM_DASHBOARD_HEALTH_URL,
        health_timeout_seconds=20.0,
        truncate_log=True,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return {"message": message, "status": _ai_stock_sim_status_payload()}


@app.post("/api/ai-stock-sim/dashboard/stop")
def stop_ai_stock_sim_dashboard() -> Dict[str, object]:
    message = _stop_background_service(AI_STOCK_SIM_DASHBOARD_PID)
    _cleanup_processes(r"streamlit run .*dashboard/dashboard_app\.py|ai_stock_sim/scripts/run_dashboard\.sh")
    return {"message": message, "status": _ai_stock_sim_status_payload()}


@app.post("/api/ai-trade/plan")
def run_ai_trade_plan(req: PlanRequest) -> Dict[str, object]:
    args = [
        _workspace_python(),
        "-m",
        "ai_trade_system.scripts.run_daily_plan",
        "--limit",
        str(req.limit),
    ]
    if req.trade_date.strip():
        args.extend(["--trade-date", req.trade_date.strip()])
    if req.execute_sim:
        args.append("--execute-sim")

    try:
        code, output = _run_workspace_command(args, timeout=300)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="生成交易计划超时")

    if code != 0:
        raise HTTPException(status_code=500, detail=output or "生成交易计划失败")

    plan_path = _latest_daily_plan()
    return {
        "message": "交易计划已生成" if not req.execute_sim else "交易计划和模拟执行已完成",
        "output": output,
        "plan_url": _report_url(plan_path),
    }


@app.post("/api/ai-trade/review")
def run_ai_trade_review() -> Dict[str, object]:
    args = [
        _workspace_python(),
        "-m",
        "ai_trade_system.scripts.run_review",
    ]
    try:
        code, output = _run_workspace_command(args, timeout=180)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="生成复盘报告超时")

    if code != 0:
        raise HTTPException(status_code=500, detail=output or "生成复盘报告失败")

    review_path = _latest_review()
    return {
        "message": "复盘报告已生成",
        "output": output,
        "review_url": _report_url(review_path),
    }


if __name__ == "__main__":
    host = os.getenv("MINIMAL_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("MINIMAL_WEB_PORT", "8600"))
    uvicorn.run(app, host=host, port=port, reload=False)
