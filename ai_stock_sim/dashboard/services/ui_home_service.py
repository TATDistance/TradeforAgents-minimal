from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import requests

from ai_stock_sim.app.db import connect_db, fetch_rows_by_sql
from ai_stock_sim.app.settings import Settings, load_settings

from .ui_action_service import build_action_cards, summarize_action_cards
from .ui_summary_service import build_ai_strategy_status, build_home_summary, build_system_status


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(PROJECT_ROOT)
ENGINE_PID_PATH = SETTINGS.data_dir / "engine.pid"
DASHBOARD_PID_PATH = SETTINGS.data_dir / "dashboard.pid"
LIVE_STATE_PATH = SETTINGS.live_state_path
ENGINE_LOG_PATH = SETTINGS.logs_dir / "engine.log"
DASHBOARD_HEALTH_URL = "http://127.0.0.1:8610/_stcore/health"
SYMBOL_NAME_CACHE: Dict[str, str] = {}
EASTMONEY_NAME_RETRY_ATTEMPTS = 3
EASTMONEY_NAME_RETRY_BACKOFF_SECONDS = 0.25


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _dashboard_healthy() -> bool:
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(DASHBOARD_HEALTH_URL, timeout=2.0)
        return response.ok
    except Exception:
        return False


def _load_live_state() -> Dict[str, object]:
    if not LIVE_STATE_PATH.exists():
        return {}
    try:
        return json.loads(LIVE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_tail(path: Path, limit: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[-limit:]
    except Exception:
        return ""


def _load_snapshot_symbol_names(settings: Settings) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    market_cache_dir = settings.cache_dir / "market"
    for cache_path in sorted(market_cache_dir.glob("snapshot_combined_*.json"), reverse=True):
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in payload.get("rows") or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            name = str(row.get("name") or "").strip()
            if symbol and name and symbol not in mapping:
                mapping[symbol] = name
        if mapping:
            break
    return mapping


def _fetch_eastmoney_symbol_names(symbols: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    for symbol in symbols:
        code = str(symbol).strip()
        if len(code) != 6 or not code.isdigit():
            continue
        cached = SYMBOL_NAME_CACHE.get(code)
        if cached:
            mapping[code] = cached
            continue
        market = "1" if code.startswith(("5", "6", "9")) else "0"
        for attempt in range(1, EASTMONEY_NAME_RETRY_ATTEMPTS + 1):
            try:
                response = session.get(
                    "https://push2.eastmoney.com/api/qt/stock/get",
                    params={
                        "secid": f"{market}.{code}",
                        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                        "invt": 2,
                        "fltt": 2,
                        "fields": "f57,f58",
                    },
                    timeout=2.5,
                )
                response.raise_for_status()
                name = str((response.json().get("data") or {}).get("f58") or "").strip()
                if name:
                    SYMBOL_NAME_CACHE[code] = name
                    mapping[code] = name
                break
            except Exception:
                if attempt < EASTMONEY_NAME_RETRY_ATTEMPTS:
                    time.sleep(EASTMONEY_NAME_RETRY_BACKOFF_SECONDS * attempt)
    return mapping


def _symbol_name_map(settings: Settings) -> Dict[str, str]:
    mapping = _load_snapshot_symbol_names(settings)
    watch_symbols: List[str] = []
    live_state = _load_live_state()
    for row in live_state.get("final_actions") or []:
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            watch_symbols.append(symbol)
    for row in live_state.get("risk_results") or []:
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            watch_symbols.append(symbol)
    missing = sorted({symbol for symbol in watch_symbols if symbol not in mapping})
    if missing:
        mapping.update(_fetch_eastmoney_symbol_names(missing))
    return mapping


def _query_rows(sql: str, params: Tuple[object, ...] = ()) -> List[Dict[str, object]]:
    conn = connect_db(SETTINGS)
    try:
        rows = fetch_rows_by_sql(conn, sql, params)
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _has_local_api_key(settings: Settings) -> bool:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return True
    env_path = settings.project_root.parent / ".env"
    if not env_path.exists():
        return False
    try:
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if raw.startswith("DEEPSEEK_API_KEY=") and raw.split("=", 1)[1].strip():
                return True
    except Exception:
        return False
    return False


def _has_recent_research_cache(settings: Settings, live_state: Dict[str, object]) -> bool:
    if not settings.decision_engine.use_decision_json_as_research_cache:
        return False
    symbols: List[str] = []
    for row in live_state.get("final_actions") or []:
        symbol = str(row.get("symbol") or "").strip()
        if symbol and symbol != "*":
            symbols.append(symbol)
    for row in live_state.get("risk_results") or []:
        symbol = str(row.get("symbol") or "").strip()
        if symbol and symbol != "*":
            symbols.append(symbol)
    if not symbols:
        return False
    trade_date = str(live_state.get("trade_date") or date.today().isoformat())
    for symbol in dict.fromkeys(symbols):
        path = settings.tradeforagents_results_dir / symbol / trade_date / "decision.json"
        if path.exists():
            return True
    return False


def _build_ai_runtime(settings: Settings, live_state: Dict[str, object]) -> Dict[str, str]:
    local_api = _has_local_api_key(settings)
    has_cache = _has_recent_research_cache(settings, live_state)
    if local_api and has_cache:
        return {
            "ai_status": "可用",
            "ai_source": "本地 .env API Key + decision.json 研究缓存",
        }
    if local_api:
        return {
            "ai_status": "可用",
            "ai_source": "本地 .env API Key",
        }
    if has_cache:
        return {
            "ai_status": "研究缓存",
            "ai_source": "仅使用 decision.json 研究缓存，不是实时 API 调用",
        }
    if settings.enable_ai:
        return {
            "ai_status": "未配置",
            "ai_source": "未检测到 API Key，当前应视为规则引擎/缓存降级模式",
        }
    return {
        "ai_status": "关闭",
        "ai_source": "AI 已在配置中关闭，当前仅使用规则引擎",
    }


def _closed_dates(settings: Settings) -> set[str]:
    path = settings.trading_calendar_file
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {str(item) for item in payload.get("closed_dates") or [] if str(item)}


def _is_trading_day(day: date, settings: Settings) -> bool:
    if not settings.trading_calendar.enabled:
        return day.weekday() < 5
    if day.weekday() >= 5:
        return False
    return day.isoformat() not in _closed_dates(settings)


def _next_trading_day(day: date, settings: Settings) -> date:
    cursor = day + timedelta(days=1)
    while not _is_trading_day(cursor, settings):
        cursor += timedelta(days=1)
    return cursor


def _previous_trading_day(day: date, settings: Settings) -> date:
    cursor = day - timedelta(days=1)
    while not _is_trading_day(cursor, settings):
        cursor -= timedelta(days=1)
    return cursor


def _parse_time(raw: object) -> time:
    if isinstance(raw, int):
        hour = raw // 3600
        minute = (raw % 3600) // 60
        second = raw % 60
        return time(hour=hour, minute=minute, second=second)
    return time.fromisoformat(str(raw))


def get_current_phase() -> Dict[str, object]:
    now = datetime.now()
    trade_day = now.date()
    next_day = _next_trading_day(trade_day, SETTINGS).isoformat()
    previous_day = _previous_trading_day(trade_day, SETTINGS).isoformat()
    if not _is_trading_day(trade_day, SETTINGS):
        phase_name = "NON_TRADING_DAY"
        reason = "当前日期不是 A 股交易日"
        is_trading_day = False
    else:
        current_time = now.time()
        config = SETTINGS.market_phase
        open_call_start = _parse_time(config.open_call_start)
        am_continuous_start = _parse_time(config.am_continuous_start)
        am_continuous_end = _parse_time(config.am_continuous_end)
        midday_end = _parse_time(config.midday_end)
        pm_continuous_end = _parse_time(config.pm_continuous_end)
        closing_call_end = _parse_time(config.closing_call_end)
        is_trading_day = True
        if current_time < open_call_start:
            phase_name = "PRE_OPEN"
            reason = "盘前准备阶段"
        elif current_time < am_continuous_start:
            phase_name = "OPEN_CALL_AUCTION"
            reason = "开盘集合竞价阶段"
        elif current_time < am_continuous_end:
            phase_name = "CONTINUOUS_AUCTION_AM"
            reason = "上午连续竞价阶段"
        elif current_time < midday_end:
            phase_name = "MIDDAY_BREAK"
            reason = "午间休市阶段"
        elif current_time < pm_continuous_end:
            phase_name = "CONTINUOUS_AUCTION_PM"
            reason = "下午连续竞价阶段"
        elif current_time < closing_call_end:
            phase_name = "CLOSING_AUCTION"
            reason = "收盘集合竞价阶段"
        else:
            phase_name = "POST_CLOSE"
            reason = "收盘后分析阶段"
    labels = {
        "NON_TRADING_DAY": "非交易日",
        "PRE_OPEN": "盘前准备",
        "OPEN_CALL_AUCTION": "开盘集合竞价",
        "CONTINUOUS_AUCTION_AM": "上午连续竞价",
        "MIDDAY_BREAK": "午间休市",
        "CONTINUOUS_AUCTION_PM": "下午连续竞价",
        "CLOSING_AUCTION": "收盘集合竞价",
        "POST_CLOSE": "收盘后",
    }
    return {
        "is_trading_day": is_trading_day,
        "phase": phase_name,
        "phase_label": labels.get(phase_name, phase_name),
        "trade_date": trade_day.isoformat(),
        "next_trading_day": next_day,
        "previous_trading_day": previous_day,
        "reason": reason,
    }


def get_execution_gate() -> Dict[str, object]:
    phase = get_current_phase()
    phase_name = str(phase.get("phase") or "")
    can_execute_fill = phase_name in {"CONTINUOUS_AUCTION_AM", "CONTINUOUS_AUCTION_PM"}
    if SETTINGS.execution_gate.block_all_fill_outside_continuous_auction and phase_name not in {
        "CONTINUOUS_AUCTION_AM",
        "CONTINUOUS_AUCTION_PM",
    }:
        can_execute_fill = False
    can_open_position = can_execute_fill and phase_name in {"CONTINUOUS_AUCTION_AM", "CONTINUOUS_AUCTION_PM"}
    if SETTINGS.execution_gate.block_new_buy_in_closing_call and phase_name == "CLOSING_AUCTION":
        can_open_position = False
    can_reduce_position = can_execute_fill and phase_name in {"CONTINUOUS_AUCTION_AM", "CONTINUOUS_AUCTION_PM"}
    can_generate_report = phase_name == "POST_CLOSE" and SETTINGS.execution_gate.allow_post_close_analysis
    return {
        "can_update_market": phase_name != "NON_TRADING_DAY",
        "can_generate_signal": phase_name != "NON_TRADING_DAY",
        "can_run_ai_decision": phase_name != "NON_TRADING_DAY",
        "can_plan_actions": phase_name != "NON_TRADING_DAY",
        "can_open_position": can_open_position,
        "can_reduce_position": can_reduce_position,
        "can_execute_fill": can_execute_fill,
        "can_generate_report": can_generate_report,
        "can_mark_to_market": True,
        "intent_only_mode": phase_name not in {"NON_TRADING_DAY", "CONTINUOUS_AUCTION_AM", "CONTINUOUS_AUCTION_PM"} and phase_name != "",
        "reason": phase.get("reason") or "",
        "phase": phase_name,
        "is_trading_day": bool(phase.get("is_trading_day")),
    }


def get_latest_ai_decisions() -> List[Dict[str, object]]:
    live_state = _load_live_state()
    names = _symbol_name_map(SETTINGS)
    engine = live_state.get("ai_decision_engine") if isinstance(live_state, dict) else {}
    if isinstance(engine, dict) and engine:
        rows = []
        for symbol, payload in engine.items():
            item = dict(payload or {})
            rows.append(
                {
                    "symbol": symbol,
                    "name": names.get(symbol, symbol),
                    "action": str(item.get("action") or "HOLD"),
                    "confidence": float(item.get("confidence") or 0.0),
                    "risk_mode": str(item.get("risk_mode") or ""),
                    "position_pct": float(item.get("position_pct") or 0.0),
                    "reduce_pct": float(item.get("reduce_pct") or 0.0),
                    "reason": str(item.get("reason") or ""),
                    "warnings": list(item.get("warnings") or []),
                    "final_score": float(item.get("final_score") or 0.0),
                }
            )
        rows.sort(key=lambda row: (-row["confidence"], -row["final_score"], row["symbol"]))
        return rows
    reviewer = live_state.get("ai_reviewer") if isinstance(live_state, dict) else []
    rows = []
    for item in reviewer or []:
        symbol = str(item.get("symbol") or "")
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, symbol),
                "action": str(item.get("ai_action") or "HOLD"),
                "confidence": float(item.get("confidence") or 0.0),
                "risk_mode": "NORMAL",
                "position_pct": 0.0,
                "reduce_pct": 0.0,
                "reason": str(item.get("reason") or ""),
                "warnings": [],
                "final_score": 0.0,
            }
        )
    rows.sort(key=lambda row: (-row["confidence"], row["symbol"]))
    return rows


def get_account_snapshot() -> Dict[str, object]:
    rows = _query_rows("SELECT * FROM account_snapshots ORDER BY id DESC LIMIT 1")
    row = rows[0] if rows else {}
    equity = float(row.get("equity") or 0.0)
    cash = float(row.get("cash") or 0.0)
    market_value = float(row.get("market_value") or 0.0)
    return {
        "cash": cash,
        "equity": equity,
        "market_value": market_value,
        "cash_ratio": (cash / equity) if equity > 0 else 0.0,
        "position_ratio": (market_value / equity) if equity > 0 else 0.0,
        "realized_pnl": float(row.get("realized_pnl") or 0.0),
        "unrealized_pnl": float(row.get("unrealized_pnl") or 0.0),
        "drawdown": float(row.get("drawdown") or 0.0),
        "ts": row.get("ts"),
    }


def get_action_summary() -> Dict[str, int]:
    live_state = _load_live_state()
    cards = build_action_cards(
        live_state.get("final_actions") or [],
        live_state.get("risk_results") or [],
        _symbol_name_map(SETTINGS),
    )
    return summarize_action_cards(cards)


def _latest_error() -> Tuple[str | None, str | None]:
    rows = _query_rows(
        "SELECT ts, message FROM system_logs WHERE level = 'ERROR' ORDER BY id DESC LIMIT 1"
    )
    if not rows:
        return None, None
    row = rows[0]
    return str(row.get("message") or ""), str(row.get("ts") or "")


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _system_status() -> Dict[str, object]:
    engine_pid = _read_pid(ENGINE_PID_PATH)
    engine_running = _pid_alive(engine_pid)
    live_state = _load_live_state()
    account = get_account_snapshot()
    last_error, last_error_ts = _latest_error()
    last_updated = str(live_state.get("ts") or account.get("ts") or "")
    status = build_system_status(
        engine_running=engine_running,
        last_updated_at=last_updated or None,
        last_error=last_error,
        last_error_ts=last_error_ts,
        refresh_interval_seconds=SETTINGS.refresh_interval_seconds,
    )
    last_updated_dt = _parse_iso_ts(last_updated or None)
    last_error_dt = _parse_iso_ts(last_error_ts)
    should_hide_error = False
    if status.get("state") != "error":
        should_hide_error = True
    if last_updated_dt and last_error_dt and last_error_dt <= last_updated_dt:
        should_hide_error = True
    if last_error_dt and (datetime.now() - last_error_dt).total_seconds() > 1800:
        should_hide_error = True
    if should_hide_error:
        last_error = None
        last_error_ts = None
        status["last_error"] = None
        status["last_error_ts"] = None
    status.update(
        {
            "engine_running": engine_running,
            "engine_pid": engine_pid,
            "dashboard_running": _pid_alive(_read_pid(DASHBOARD_PID_PATH)),
            "dashboard_healthy": _dashboard_healthy(),
            "dashboard_url": "http://127.0.0.1:8610/",
            "engine_log_tail": _read_tail(ENGINE_LOG_PATH, limit=2500),
        }
    )
    return status


def get_home_view() -> Dict[str, object]:
    live_state = _load_live_state()
    phase = get_current_phase()
    execution = get_execution_gate()
    names = _symbol_name_map(SETTINGS)
    actions = build_action_cards(live_state.get("final_actions") or [], live_state.get("risk_results") or [], names)
    account = get_account_snapshot()
    ai_decisions = get_latest_ai_decisions()
    manager = live_state.get("ai_portfolio_manager") if isinstance(live_state, dict) else {}
    ai_runtime = _build_ai_runtime(SETTINGS, live_state)
    strategy_status = build_ai_strategy_status(
        actions,
        ai_decisions,
        manager if isinstance(manager, dict) else {},
        ai_runtime,
    )
    stats = get_action_summary()
    system_status = _system_status()
    summary = build_home_summary(
        system_status=system_status,
        phase=phase,
        actions=actions,
        strategy_status=strategy_status,
    )
    return {
        "summary": summary,
        "system_status": system_status,
        "phase": phase,
        "execution": execution,
        "strategy_status": strategy_status,
        "ai_runtime": ai_runtime,
        "actions": actions,
        "account": account,
        "stats": stats,
    }


def get_debug_view() -> Dict[str, object]:
    status = _system_status()
    logs = _query_rows("SELECT ts, level, module, message FROM system_logs ORDER BY id DESC LIMIT 12")
    return {
        "system_status": status,
        "logs": logs,
        "dashboard_url": status.get("dashboard_url"),
    }
