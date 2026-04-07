from __future__ import annotations

import json
import os
import sqlite3
import sys
import time as time_module
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import requests

try:
    from ai_stock_sim.app.db import (
        connect_db,
        fetch_rows_by_sql,
        initialize_simulation_account_dbs,
        seed_simulation_accounts,
    )
    from ai_stock_sim.app.settings import (
        Settings,
        get_primary_simulation_account,
        load_settings,
        resolve_max_single_position_pct,
        resolve_simulation_accounts,
    )
    from ai_stock_sim.app.strategy_evaluation_service import StrategyEvaluationService
    from ai_stock_sim.app.watchlist_service import get_active_watchlist
    from ai_stock_sim.app.watchlist_sync_service import load_runtime_watchlist
except ModuleNotFoundError:  # pragma: no cover - test/runtime import compatibility
    from app.db import connect_db, fetch_rows_by_sql, initialize_simulation_account_dbs, seed_simulation_accounts
    from app.settings import Settings, get_primary_simulation_account, load_settings, resolve_max_single_position_pct, resolve_simulation_accounts
    from app.strategy_evaluation_service import StrategyEvaluationService
    from app.watchlist_service import get_active_watchlist
    from app.watchlist_sync_service import load_runtime_watchlist

from .ui_action_service import build_action_cards, summarize_action_cards
from .ui_chart_service import get_equity_curve_data, get_intraday_chart_data, get_kline_chart_data
from .ui_summary_service import (
    build_ai_strategy_status,
    build_home_summary,
    build_no_buy_reasons,
    build_system_status,
)
from .ui_timeline_service import get_recent_action_timeline


PROJECT_ROOT = Path(os.getenv("AI_STOCK_SIM_HOME", str(Path(__file__).resolve().parents[2]))).resolve()
SETTINGS = load_settings(PROJECT_ROOT)
ENGINE_PID_PATH = SETTINGS.data_dir / "engine.pid"
DASHBOARD_PID_PATH = SETTINGS.data_dir / "dashboard.pid"
ENGINE_LOG_PATH = SETTINGS.logs_dir / "engine.log"
DASHBOARD_HEALTH_URL = "http://127.0.0.1:8610/_stcore/health"
SYMBOL_NAME_CACHE: Dict[str, str] = {}
EASTMONEY_NAME_RETRY_ATTEMPTS = 3
EASTMONEY_NAME_RETRY_BACKOFF_SECONDS = 0.25
SIMULATION_ACCOUNTS = resolve_simulation_accounts(SETTINGS)
PRIMARY_ACCOUNT = get_primary_simulation_account(SETTINGS)


def _ensure_home_runtime_ready() -> None:
    try:
        initialize_simulation_account_dbs(SETTINGS)
        seed_simulation_accounts(SETTINGS)
    except Exception:
        pass


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


def _available_accounts() -> List[Dict[str, object]]:
    return [
        {
            "account_id": account.account_id,
            "name": account.name,
            "initial_cash": float(account.initial_cash),
            "is_primary": bool(account.is_primary),
        }
        for account in SIMULATION_ACCOUNTS
    ]


def _resolve_account_id(account_id: str | None = None) -> str:
    normalized = str(account_id or "").strip()
    valid_ids = {account.account_id for account in SIMULATION_ACCOUNTS}
    if normalized and normalized in valid_ids:
        return normalized
    return PRIMARY_ACCOUNT.account_id


def _account_live_state_path(account_id: str | None = None) -> Path:
    resolved_account_id = _resolve_account_id(account_id)
    return SETTINGS.resolved_account_live_state_path(resolved_account_id)


def _load_live_state(account_id: str | None = None) -> Dict[str, object]:
    live_state_path = _account_live_state_path(account_id)
    if not live_state_path.exists():
        return {}
    try:
        return json.loads(live_state_path.read_text(encoding="utf-8"))
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
    for cache_path in sorted(market_cache_dir.glob("quote_obj_*.json"), reverse=True):
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        symbol = str(payload.get("symbol") or "").strip()
        name = str(payload.get("name") or "").strip()
        if symbol and name and symbol not in mapping and name != symbol:
            mapping[symbol] = name
    for report_dir in _candidate_report_dirs(settings):
        for candidate_path in sorted(report_dir.glob("auto_candidates_*.json"), reverse=True)[:3]:
            try:
                payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for row in payload.get("selected") or []:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").strip()
                name = str(row.get("name") or "").strip()
                if symbol and name and symbol not in mapping and name != symbol:
                    mapping[symbol] = name
    return mapping


def _fetch_eastmoney_symbol_names(symbols: List[str]) -> Dict[str, str]:
    if getattr(sys, "frozen", False) and os.name == "nt":
        return {}
    mapping: Dict[str, str] = {}
    session = requests.Session()
    proxy_override = os.environ.get("TRADEFORAGENTS_BYPASS_REMOTE_PROXY", "").strip().lower()
    if proxy_override in {"1", "true", "yes", "on"}:
        session.trust_env = False
    elif proxy_override in {"0", "false", "no", "off"}:
        session.trust_env = True
    else:
        session.trust_env = os.name == "nt"
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
            except OSError:
                # Frozen Windows builds may not have a usable certifi bundle path.
                break
            except requests.RequestException:
                if attempt < EASTMONEY_NAME_RETRY_ATTEMPTS:
                    time_module.sleep(EASTMONEY_NAME_RETRY_BACKOFF_SECONDS * attempt)
            except Exception:
                if attempt < EASTMONEY_NAME_RETRY_ATTEMPTS:
                    time_module.sleep(EASTMONEY_NAME_RETRY_BACKOFF_SECONDS * attempt)
    return mapping


def _symbol_name_map(settings: Settings, account_id: str | None = None) -> Dict[str, str]:
    mapping = _load_snapshot_symbol_names(settings)
    watch_symbols: List[str] = []
    live_state = _load_live_state(account_id)
    for row in live_state.get("final_actions") or []:
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            watch_symbols.append(symbol)
    for row in live_state.get("risk_results") or []:
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            watch_symbols.append(symbol)
    runtime_watchlist = load_runtime_watchlist(settings)
    for symbol in runtime_watchlist.get("symbols") or []:
        code = str(symbol).strip()
        if code:
            watch_symbols.append(code)
    active_watchlist = get_active_watchlist(settings)
    for symbol in active_watchlist.get("symbols") or []:
        code = str(symbol).strip()
        if code:
            watch_symbols.append(code)
    conn = connect_db(settings, account_id=account_id)
    try:
        for row in fetch_rows_by_sql(conn, "SELECT symbol FROM positions ORDER BY id DESC LIMIT 64"):
            code = str(dict(row).get("symbol") or "").strip()
            if code:
                watch_symbols.append(code)
        for row in fetch_rows_by_sql(conn, "SELECT symbol FROM orders ORDER BY id DESC LIMIT 128"):
            code = str(dict(row).get("symbol") or "").strip()
            if code:
                watch_symbols.append(code)
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    missing = sorted({symbol for symbol in watch_symbols if symbol not in mapping})
    if missing:
        mapping.update(_fetch_eastmoney_symbol_names(missing))
    return mapping


def _query_rows(sql: str, params: Tuple[object, ...] = (), account_id: str | None = None) -> List[Dict[str, object]]:
    conn = connect_db(SETTINGS, account_id=account_id)
    try:
        rows = fetch_rows_by_sql(conn, sql, params)
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _candidate_report_dirs(settings: Settings) -> List[Path]:
    dirs: List[Path] = []
    embedded = settings.project_root.parent / "ai_trade_system" / "reports"
    legacy = settings.project_root.parent.parent / "ai_trade_system" / "reports"
    for path in (embedded, legacy):
        if path.exists() and path not in dirs:
            dirs.append(path)
    return dirs


def _latest_ai_stock_sim_report(subdir: str, pattern: str) -> Path | None:
    report_dir = SETTINGS.data_dir / "reports" / subdir
    if not report_dir.exists():
        return None
    candidates = sorted(report_dir.glob(pattern), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return candidates[0] if candidates else None


def _sim_report_url(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    try:
        relative = path.relative_to(SETTINGS.data_dir / "reports")
    except ValueError:
        return None
    return "/ai_stock_sim_reports/" + str(relative).replace("\\", "/")


def _latest_report_links() -> Dict[str, Dict[str, str | None]]:
    daily_md = _latest_ai_stock_sim_report("daily", "daily_*.md")
    weekly_md = _latest_ai_stock_sim_report("weekly", "weekly_*.md")
    monthly_md = _latest_ai_stock_sim_report("monthly", "monthly_*.md")
    items = [
        ("daily", "今日日报", daily_md),
        ("weekly", "本周周报", weekly_md),
        ("monthly", "本月月报", monthly_md),
    ]
    payload: Dict[str, Dict[str, str | None]] = {}
    for key, label, path in items:
        payload[key] = {
            "label": label,
            "name": path.name if path else None,
            "url": _sim_report_url(path),
        }
    return payload


def _latest_report_json(settings: Settings, pattern: str) -> Dict[str, object]:
    candidates: List[Path] = []
    for report_dir in _candidate_report_dirs(settings):
        candidates.extend(report_dir.glob(pattern))
    if not candidates:
        return {}
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_observe_candidates(
    settings: Settings,
    live_state: Dict[str, object],
    phase: Dict[str, object],
    execution: Dict[str, object],
    strategy_status: Dict[str, str],
) -> List[Dict[str, object]]:
    auto_payload = _latest_report_json(settings, "auto_candidates_*.json")
    selected = auto_payload.get("selected") or []
    if not isinstance(selected, list):
        return []

    feature_fusions = live_state.get("feature_fusions") or {}
    ai_engine = live_state.get("ai_decision_engine") or {}
    risk_mode = str(strategy_status.get("risk_mode") or "")
    portfolio_feedback = live_state.get("portfolio_feedback") if isinstance(live_state, dict) else {}
    equity = float((portfolio_feedback or {}).get("equity") or 0.0)
    cash = float((portfolio_feedback or {}).get("cash") or 0.0)
    today_open_ratio = float((portfolio_feedback or {}).get("today_open_ratio") or 0.0)
    buy_threshold = float(settings.scoring.min_execution_score_to_buy)
    rows: List[Dict[str, object]] = []
    for item in selected[:6]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        fusion = feature_fusions.get(symbol) if isinstance(feature_fusions, dict) else {}
        decision = ai_engine.get(symbol) if isinstance(ai_engine, dict) else {}
        setup_score = float((decision or {}).get("setup_score") or (fusion or {}).get("setup_score") or (fusion or {}).get("final_score") or 0.0)
        execution_score = float((decision or {}).get("execution_score") or (decision or {}).get("final_score") or (fusion or {}).get("execution_score") or (fusion or {}).get("final_score") or 0.0)
        ai_score = float((decision or {}).get("ai_score") or 0.0)
        current_action = str((decision or {}).get("action") or (fusion or {}).get("final_action") or "HOLD")
        reasons: List[str] = []
        if not bool(phase.get("is_trading_day")):
            reasons.append("今天不是交易日")
        elif not bool(execution.get("can_open_position")):
            reasons.append("当前阶段不允许新开仓")
        if risk_mode in {"DEFENSIVE", "RISK_OFF"}:
            reasons.append("当前风险模式偏防守")
        if setup_score < settings.scoring.min_setup_score_to_watch:
            reasons.append("setup_score {0:.2f} 仍低于观察阈值 {1:.2f}".format(setup_score, settings.scoring.min_setup_score_to_watch))
        if execution_score < buy_threshold:
            reasons.append("execution_score {0:.2f} 未达到买入阈值 {1:.2f}".format(execution_score, buy_threshold))
        latest_price = float(((((live_state.get("decision_contexts") or {}).get(symbol) or {}).get("snapshot") or {}).get("latest_price") or 0.0))
        if equity > 0 and latest_price > 0:
            one_lot_cost = latest_price * 100
            max_single_position_pct = resolve_max_single_position_pct(settings, equity)
            ignore_daily_cap = 0.0 < equity <= float(settings.capital_profile.small_account_equity_threshold)
            current_value = 0.0
            positions_detail = (portfolio_feedback or {}).get("positions_detail") or []
            for pos in positions_detail:
                if isinstance(pos, dict) and str(pos.get("symbol") or "") == symbol:
                    current_value = float(pos.get("market_value") or 0.0)
                    break
            single_cap = max(0.0, equity * max_single_position_pct - current_value)
            daily_cap = max(0.0, equity * settings.max_daily_open_position_pct - today_open_ratio * equity)
            if one_lot_cost > single_cap + 1e-6:
                reasons.append(
                    "买一手约需 {0:.1f} 万元，已超过当前单票可用仓位上限 {1:.1f} 万元，卖出其他持仓也无法解决".format(
                        one_lot_cost / 10000.0,
                        max(single_cap, 0.0) / 10000.0,
                    )
                )
            elif (not ignore_daily_cap) and one_lot_cost > daily_cap + 1e-6:
                reasons.append(
                    "买一手约需 {0:.1f} 万元，已超过当前单日可用开仓额度 {1:.1f} 万元".format(
                        one_lot_cost / 10000.0,
                        max(daily_cap, 0.0) / 10000.0,
                    )
                )
            elif one_lot_cost > cash + 1e-6:
                reasons.append(
                    "买一手约需 {0:.1f} 万元，当前可用现金仅 {1:.1f} 万元；若想参与，需要先卖出部分已有持仓腾挪现金".format(
                        one_lot_cost / 10000.0,
                        max(cash, 0.0) / 10000.0,
                    )
                )
        warnings = (decision or {}).get("warnings") or []
        if isinstance(warnings, list):
            for warning in warnings[:2]:
                text = str(warning).strip()
                if text:
                    reasons.append(text)
        if current_action not in {"BUY", "PREPARE_BUY"}:
            reasons.append("AI 当前动作仍是 {0}".format(current_action))
        rows.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or symbol),
                "stance": str(item.get("stance") or "观察"),
                "score": float(item.get("score") or 0.0),
                "setup_score": setup_score,
                "execution_score": execution_score,
                "ai_score": ai_score,
                "current_action": current_action,
                "snapshot_pct_change": _normalize_pct_change(((((live_state.get("decision_contexts") or {}).get(symbol) or {}).get("snapshot") or {}).get("pct_change") or 0.0)),
                "reasons": reasons[:4] or ["当前仍以观察为主，尚未转为买入。"],
            }
        )
    return rows


def _latest_quote_payload(settings: Settings, symbol: str) -> Dict[str, object]:
    quote_path = settings.cache_dir / "market" / f"quote_obj_{symbol}.json"
    if not quote_path.exists():
        return {}
    try:
        return json.loads(quote_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_watchlist(settings: Settings) -> Dict[str, object]:
    runtime_watchlist = load_runtime_watchlist(settings)
    if runtime_watchlist.get("symbols"):
        return runtime_watchlist
    return get_active_watchlist(settings)


def _build_watchlist_entries(
    settings: Settings,
    live_state: Dict[str, object],
    symbol_names: Dict[str, str],
    ai_decisions: List[Dict[str, object]],
    account_id: str | None = None,
) -> Dict[str, object]:
    watchlist = _resolve_watchlist(settings)
    live_watchlist = live_state.get("runtime_watchlist") if isinstance(live_state, dict) else {}
    evolution = dict((live_watchlist or {}).get("watchlist_evolution") or watchlist.get("watchlist_evolution") or {})
    events = list((live_watchlist or {}).get("watchlist_events") or watchlist.get("watchlist_events") or live_state.get("watchlist_events") or [])
    last_scan_at = str((live_watchlist or {}).get("last_scan_at") or live_state.get("watchlist_scan", {}).get("scan_time") or watchlist.get("last_scan_at") or "")
    decision_map = {str(item.get("symbol") or ""): item for item in ai_decisions}
    positions = _query_rows(
        "SELECT symbol, qty, avg_cost, last_price, market_value, unrealized_pnl, can_sell_qty FROM positions ORDER BY symbol",
        account_id=account_id,
    )
    position_map = {str(item.get("symbol") or ""): item for item in positions}
    decision_contexts = live_state.get("decision_contexts") if isinstance(live_state, dict) else {}
    entries: List[Dict[str, object]] = []
    for symbol in watchlist.get("symbols") or []:
        symbol = str(symbol).strip()
        if not symbol:
            continue
        if symbol.isdigit() and len(symbol) != 6:
            continue
        decision = decision_map.get(symbol, {})
        context = (decision_contexts or {}).get(symbol) if isinstance(decision_contexts, dict) else {}
        snapshot = dict(context.get("snapshot") or {}) if isinstance(context, dict) else {}
        if not snapshot:
            snapshot = _latest_quote_payload(settings, symbol)
        latest_price = float(snapshot.get("latest_price") or snapshot.get("close") or 0.0)
        pct_change = _normalize_pct_change(snapshot.get("pct_change") or 0.0)
        position = position_map.get(symbol, {})
        entries.append(
            {
                "symbol": symbol,
                "name": symbol_names.get(symbol, symbol),
                "latest_price": latest_price,
                "pct_change": pct_change,
                "action": str(decision.get("action") or "HOLD"),
                "setup_score": float(decision.get("setup_score") or 0.0),
                "execution_score": float(decision.get("execution_score") or 0.0),
                "has_position": bool(position),
                "position_qty": int(position.get("qty") or 0),
            }
        )
    holdings = [
        {
            "symbol": str(item.get("symbol") or ""),
            "name": symbol_names.get(str(item.get("symbol") or ""), str(item.get("symbol") or "")),
            "qty": int(item.get("qty") or 0),
            "last_price": float(item.get("last_price") or 0.0),
            "market_value": float(item.get("market_value") or 0.0),
            "unrealized_pnl": float(item.get("unrealized_pnl") or 0.0),
            "can_sell_qty": int(item.get("can_sell_qty") or 0),
        }
        for item in positions
    ]
    decorated_events: List[Dict[str, object]] = []
    for item in events[:10]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        decorated = dict(item)
        decorated["symbol"] = symbol
        decorated["name"] = symbol_names.get(symbol, symbol)
        decorated_events.append(decorated)

    return {
        "source": str(watchlist.get("source") or "default_fallback"),
        "generated_at": str(watchlist.get("generated_at") or ""),
        "valid_until": str(watchlist.get("valid_until") or ""),
        "trading_day": str(watchlist.get("trading_day") or ""),
        "stale": bool(watchlist.get("stale")),
        "last_scan_at": last_scan_at,
        "evolution": evolution,
        "events": decorated_events,
        "entries": entries[:16],
        "holdings": holdings[:12],
    }


def _watch_section_key(entry: Dict[str, object], settings: Settings) -> str:
    action = str(entry.get("action") or "").upper()
    execution_score = float(entry.get("execution_score") or 0.0)
    setup_score = float(entry.get("setup_score") or 0.0)
    has_position = bool(entry.get("has_position"))
    if has_position or action in {"BUY", "SELL", "REDUCE"} or execution_score >= settings.scoring.min_execution_score_to_buy * 0.8:
        return "core"
    if setup_score >= settings.scoring.min_setup_score_to_watch or action in {"WATCH_NEXT_DAY", "HOLD", "PREPARE_BUY", "HOLD_FOR_TOMORROW"}:
        return "observe"
    return "low"


def _watch_section_priority(entry: Dict[str, object]) -> tuple[float, float, float, str]:
    return (
        1.0 if bool(entry.get("has_position")) else 0.0,
        float(entry.get("execution_score") or 0.0),
        float(entry.get("setup_score") or 0.0),
        str(entry.get("symbol") or ""),
    )


def _build_watchlist_sections(watchlist: Dict[str, object], settings: Settings) -> List[Dict[str, object]]:
    section_meta = {
        "core": ("🔥 核心关注", "优先关注当前持仓、执行分最高或刚刚触发动作的股票。"),
        "observe": ("👀 观察中", "股票本身值得继续盯，但当前更适合等待更好的执行时机。"),
        "low": ("❌ 低优先级", "当前强度不足，先放在更低优先级的观察层。"),
    }
    buckets = {"core": [], "observe": [], "low": []}
    for entry in watchlist.get("entries") or []:
        buckets[_watch_section_key(entry, settings)].append(entry)
    sections: List[Dict[str, object]] = []
    for key in ("core", "observe", "low"):
        items = sorted(buckets[key], key=_watch_section_priority, reverse=True)
        if not items:
            continue
        title, desc = section_meta[key]
        sections.append(
            {
                "key": key,
                "title": title,
                "description": desc,
                "items": items,
            }
        )
    return sections


def _build_trade_explanations(
    names: Dict[str, str],
    ai_decisions: List[Dict[str, object]],
    watchlist: Dict[str, object],
    account_id: str | None = None,
) -> Dict[str, object]:
    order_rows = _query_rows(
        """
        SELECT ts, symbol, side, price, qty, status, note
        FROM orders
        WHERE intent_only = 0
          AND status IN ('FILLED', 'PARTIAL_FILLED')
        ORDER BY id DESC
        LIMIT 30
        """,
        account_id=account_id,
    )
    buys: List[Dict[str, object]] = []
    sells: List[Dict[str, object]] = []
    for row in order_rows:
        symbol = str(row.get("symbol") or "").strip()
        side = str(row.get("side") or "").strip().upper()
        item = {
            "ts": str(row.get("ts") or ""),
            "symbol": symbol,
            "name": names.get(symbol, symbol),
            "action": side,
            "price": float(row.get("price") or 0.0),
            "qty": int(row.get("qty") or 0),
            "reason": str(row.get("note") or "").strip() or "本轮满足执行条件并完成模拟成交。",
        }
        if side == "BUY" and len(buys) < 3:
            buys.append(item)
        elif side in {"SELL", "REDUCE"} and len(sells) < 3:
            sells.append(item)
        if len(buys) >= 3 and len(sells) >= 3:
            break

    hold_reasons: List[Dict[str, object]] = []
    holding_map = {str(item.get("symbol") or ""): item for item in watchlist.get("holdings") or []}
    for row in ai_decisions:
        symbol = str(row.get("symbol") or "").strip()
        if symbol not in holding_map:
            continue
        if str(row.get("action") or "").upper() != "HOLD":
            continue
        hold_reasons.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, symbol),
                "action": "HOLD",
                "reason": str(row.get("reason") or "").strip() or "当前持仓仍与市场状态匹配，暂不减仓或卖出。",
                "execution_score": float(row.get("execution_score") or 0.0),
                "setup_score": float(row.get("setup_score") or 0.0),
            }
        )
    hold_reasons.sort(key=lambda item: float(item.get("execution_score") or 0.0), reverse=True)

    return {
        "recent_buys": buys,
        "recent_sells": sells,
        "hold_reasons": hold_reasons[:3],
    }


def _select_chart_symbol(
    watchlist: Dict[str, object],
    timeline: List[Dict[str, object]],
    ai_decisions: List[Dict[str, object]],
) -> str:
    holdings = watchlist.get("holdings") or []
    if holdings:
        return str(holdings[0].get("symbol") or "")
    ranked = sorted(
        ai_decisions,
        key=lambda item: float(item.get("execution_score") or 0.0),
        reverse=True,
    )
    if ranked:
        return str(ranked[0].get("symbol") or "")
    if timeline:
        return str(timeline[0].get("symbol") or "")
    entries = watchlist.get("entries") or []
    for entry in entries:
        if float(entry.get("latest_price") or 0.0) > 0:
            return str(entry.get("symbol") or "")
    if entries:
        return str(entries[0].get("symbol") or "")
    return ""


def _build_core_symbol(
    watchlist: Dict[str, object],
    ai_decisions: List[Dict[str, object]],
    timeline: List[Dict[str, object]],
) -> Dict[str, object]:
    decision_map = {str(item.get("symbol") or ""): item for item in ai_decisions}
    entry_map = {str(item.get("symbol") or ""): item for item in watchlist.get("entries") or []}
    holding_map = {str(item.get("symbol") or ""): item for item in watchlist.get("holdings") or []}
    chosen_symbol = _select_chart_symbol(watchlist, timeline, ai_decisions)
    if not chosen_symbol:
        return {}
    entry = dict(entry_map.get(chosen_symbol) or {})
    if not entry:
        entry = {
            "symbol": chosen_symbol,
            "name": str((holding_map.get(chosen_symbol) or {}).get("name") or chosen_symbol),
            "latest_price": float((holding_map.get(chosen_symbol) or {}).get("last_price") or 0.0),
            "pct_change": 0.0,
            "has_position": bool(holding_map.get(chosen_symbol)),
            "position_qty": int((holding_map.get(chosen_symbol) or {}).get("qty") or 0),
        }
    decision = dict(decision_map.get(chosen_symbol) or {})
    reason = str(decision.get("reason") or "")
    if not reason:
        warnings = decision.get("warnings") or []
        if isinstance(warnings, list) and warnings:
            reason = str(warnings[0] or "")
    if not reason:
        reason = "当前仍在等待更明确的盘中动作信号。"
    entry.update(
        {
            "symbol": chosen_symbol,
            "action": str(decision.get("action") or entry.get("action") or "HOLD"),
            "setup_score": float(decision.get("setup_score") or entry.get("setup_score") or 0.0),
            "execution_score": float(decision.get("execution_score") or entry.get("execution_score") or 0.0),
            "reason": reason,
            "confidence": float(decision.get("confidence") or 0.0),
        }
    )
    return entry


def _build_top_opportunity_candidates(ai_decisions: List[Dict[str, object]], settings: Settings) -> List[Dict[str, object]]:
    threshold = float(settings.scoring.min_execution_score_to_buy)
    rows: List[Dict[str, object]] = []
    for item in ai_decisions:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        execution_score = float(item.get("execution_score") or 0.0)
        rows.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or symbol),
                "execution_score": execution_score,
                "gap_to_buy": max(0.0, threshold - execution_score),
                "action": str(item.get("action") or "HOLD"),
            }
        )
    rows.sort(key=lambda row: (row["gap_to_buy"], -row["execution_score"], row["symbol"]))
    return rows[:3]


def _has_local_api_key(settings: Settings) -> bool:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return True
    env_path = Path(os.getenv("TRADEFORAGENTS_ENV_FILE", str(settings.project_root.parent / ".env"))).resolve()
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
    realtime_modes: List[str] = []
    if local_api and settings.ai.realtime_action_review_enabled:
        realtime_modes.append("买卖前 AI 终审")
    if local_api and settings.ai.realtime_position_review_enabled:
        realtime_modes.append("持仓 AI 复核")
    realtime_suffix = f" + {' / '.join(realtime_modes)}" if realtime_modes else ""
    if local_api and has_cache:
        return {
            "ai_status": "可用",
            "ai_source": "本地 .env API Key + decision.json 研究缓存" + realtime_suffix,
        }
    if local_api:
        return {
            "ai_status": "可用",
            "ai_source": "本地 .env API Key" + realtime_suffix,
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


def get_current_phase(account_id: str | None = None) -> Dict[str, object]:
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


def get_execution_gate(account_id: str | None = None) -> Dict[str, object]:
    phase = get_current_phase(account_id=account_id)
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


def get_latest_ai_decisions(account_id: str | None = None) -> List[Dict[str, object]]:
    live_state = _load_live_state(account_id)
    names = _symbol_name_map(SETTINGS, account_id=account_id)
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
                "feature_score": float(item.get("feature_score") or 0.0),
                "ai_score": float(item.get("ai_score") or 0.0),
                "setup_score": float(item.get("setup_score") or item.get("final_score") or 0.0),
                "execution_score": float(item.get("execution_score") or item.get("final_score") or 0.0),
                "market_risk_penalty": float(item.get("market_risk_penalty") or 0.0),
                "portfolio_risk_penalty": float(item.get("portfolio_risk_penalty") or 0.0),
                "phase_penalty": float(item.get("phase_penalty") or 0.0),
                "gate_penalty": float(item.get("gate_penalty") or 0.0),
            }
        )
        rows.sort(key=lambda row: (-row["confidence"], -row["final_score"], row["symbol"]))
        return rows
    runtime_states = live_state.get("runtime_states") if isinstance(live_state, dict) else {}
    if isinstance(runtime_states, dict) and runtime_states:
        rows = []
        for symbol, payload in runtime_states.items():
            item = dict(payload or {})
            rows.append(
                {
                    "symbol": symbol,
                    "name": names.get(symbol, symbol),
                    "action": str(item.get("last_ai_action") or "HOLD"),
                    "confidence": 0.0,
                    "risk_mode": "NORMAL",
                    "position_pct": 0.0,
                    "reduce_pct": 0.0,
                    "reason": "来自最近一次运行时状态缓存",
                    "warnings": [],
                    "final_score": float(item.get("last_execution_score") or 0.0),
                    "feature_score": float(item.get("last_feature_score") or 0.0),
                    "ai_score": float(item.get("last_ai_score") or 0.0),
                    "setup_score": float(item.get("last_setup_score") or 0.0),
                    "execution_score": float(item.get("last_execution_score") or 0.0),
                    "market_risk_penalty": 0.0,
                    "portfolio_risk_penalty": 0.0,
                    "phase_penalty": 0.0,
                    "gate_penalty": 0.0,
                }
            )
        rows.sort(key=lambda row: (-abs(float(row["execution_score"])), row["symbol"]))
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
                "feature_score": 0.0,
                "ai_score": 0.0,
                "setup_score": 0.0,
                "execution_score": 0.0,
                "market_risk_penalty": 0.0,
                "portfolio_risk_penalty": 0.0,
                "phase_penalty": 0.0,
                "gate_penalty": 0.0,
            }
        )
    rows.sort(key=lambda row: (-row["confidence"], row["symbol"]))
    return rows


def get_account_snapshot(account_id: str | None = None) -> Dict[str, object]:
    resolved_account_id = _resolve_account_id(account_id)
    current_account = next(
        (account for account in SIMULATION_ACCOUNTS if account.account_id == resolved_account_id),
        PRIMARY_ACCOUNT,
    )
    rows = _query_rows("SELECT * FROM account_snapshots ORDER BY id DESC LIMIT 1", account_id=resolved_account_id)
    row = rows[0] if rows else {}
    equity = float(row.get("equity") or 0.0)
    cash = float(row.get("cash") or 0.0)
    market_value = float(row.get("market_value") or 0.0)
    initial_cash = float(current_account.initial_cash)
    realized_pnl = float(row.get("realized_pnl") or 0.0)
    unrealized_pnl = float(row.get("unrealized_pnl") or 0.0)
    total_pnl = equity - initial_cash
    return {
        "account_id": current_account.account_id,
        "account_name": current_account.name,
        "is_primary": bool(current_account.is_primary),
        "initial_cash": initial_cash,
        "cash": cash,
        "equity": equity,
        "market_value": market_value,
        "cash_ratio": (cash / equity) if equity > 0 else 0.0,
        "position_ratio": (market_value / equity) if equity > 0 else 0.0,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "total_return": (total_pnl / initial_cash) if initial_cash > 0 else 0.0,
        "drawdown": float(row.get("drawdown") or 0.0),
        "ts": row.get("ts"),
    }


def _build_realized_breakdown(
    symbol_names: Dict[str, str],
    account_id: str | None = None,
    expected_total: float | None = None,
) -> Dict[str, object]:
    rows = _query_rows(
        """
        SELECT ts, symbol, side, price, qty, fee, tax, slippage, status
        FROM orders
        WHERE intent_only = 0
          AND status IN ('FILLED', 'PARTIAL_FILLED')
        ORDER BY ts ASC, id ASC
        """,
        account_id=account_id,
    )
    positions: Dict[str, Dict[str, float]] = {}
    summaries: Dict[str, Dict[str, object]] = {}
    computed_total = 0.0
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        side = str(row.get("side") or "").upper()
        qty = int(row.get("qty") or 0)
        if not symbol or qty <= 0:
            continue
        price = float(row.get("price") or 0.0)
        fee = float(row.get("fee") or 0.0)
        tax = float(row.get("tax") or 0.0)
        positions.setdefault(symbol, {"qty": 0.0, "avg_cost": 0.0})
        position = positions[symbol]
        if side == "BUY":
            old_qty = float(position.get("qty") or 0.0)
            new_qty = old_qty + qty
            avg_cost = price
            if new_qty > 0:
                avg_cost = ((float(position.get("avg_cost") or 0.0) * old_qty) + price * qty) / new_qty
            position["qty"] = new_qty
            position["avg_cost"] = avg_cost
            continue
        if side != "SELL":
            continue
        held_qty = int(float(position.get("qty") or 0.0))
        if held_qty <= 0:
            continue
        matched_qty = min(qty, held_qty)
        avg_cost = float(position.get("avg_cost") or 0.0)
        realized_pnl = (price - avg_cost) * matched_qty - fee - tax
        position["qty"] = max(0.0, held_qty - matched_qty)
        if position["qty"] <= 0:
            position["avg_cost"] = 0.0
        if matched_qty <= 0:
            continue
        summary = summaries.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": symbol_names.get(symbol, symbol),
                "realized_pnl": 0.0,
                "matched_qty": 0,
                "sell_count": 0,
                "last_sell_ts": "",
            },
        )
        summary["realized_pnl"] = float(summary.get("realized_pnl") or 0.0) + realized_pnl
        summary["matched_qty"] = int(summary.get("matched_qty") or 0) + matched_qty
        summary["sell_count"] = int(summary.get("sell_count") or 0) + 1
        summary["last_sell_ts"] = str(row.get("ts") or summary.get("last_sell_ts") or "")
        computed_total += realized_pnl
    position_rows = _query_rows(
        "SELECT symbol, qty, avg_cost, updated_at FROM positions ORDER BY symbol",
        account_id=account_id,
    )
    position_map = {str(item.get("symbol") or ""): item for item in position_rows}
    items: List[Dict[str, object]] = []
    for symbol, summary in summaries.items():
        current_position = position_map.get(symbol, {})
        current_qty = int(current_position.get("qty") or 0)
        item = dict(summary)
        item["current_qty"] = current_qty
        item["still_holding"] = current_qty > 0
        item["avg_cost"] = float(current_position.get("avg_cost") or 0.0)
        items.append(item)
    losses = sorted(
        [item for item in items if float(item.get("realized_pnl") or 0.0) < 0],
        key=lambda item: float(item.get("realized_pnl") or 0.0),
    )
    profits = sorted(
        [item for item in items if float(item.get("realized_pnl") or 0.0) > 0],
        key=lambda item: float(item.get("realized_pnl") or 0.0),
        reverse=True,
    )
    return {
        "items": sorted(items, key=lambda item: abs(float(item.get("realized_pnl") or 0.0)), reverse=True),
        "losses": losses[:5],
        "profits": profits[:5],
        "computed_total": computed_total,
        "expected_total": float(expected_total or 0.0),
        "reconciliation_gap": float(expected_total or 0.0) - computed_total,
        "closed_symbol_count": len(items),
    }


def _build_realtime_ai_review_summary(
    live_state: Dict[str, object],
    symbol_names: Dict[str, str],
) -> Dict[str, object]:
    rows = live_state.get("realtime_ai_reviews") or []
    if not isinstance(rows, list):
        rows = []
    items: List[Dict[str, object]] = []
    action_review_count = 0
    holding_review_count = 0
    changed_count = 0
    pending_count = 0
    done_count = 0
    degraded_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        candidate_type = str(row.get("candidate_type") or "action")
        if candidate_type == "holding":
            holding_review_count += 1
        else:
            action_review_count += 1
        applied = bool(row.get("applied"))
        if applied:
            changed_count += 1
        review_status = str(row.get("review_status") or "PENDING").upper()
        if review_status == "DONE":
            done_count += 1
        elif review_status == "DEGRADED":
            degraded_count += 1
        else:
            pending_count += 1
        draft_action = str(row.get("draft_action") or row.get("proposed_action") or "HOLD")
        reviewed_action = str(row.get("reviewed_action") or row.get("final_action") or draft_action)
        reason = str(row.get("reason") or "").strip()
        fallback_reason = str(row.get("fallback_reason") or "").strip()
        items.append(
            {
                "symbol": symbol,
                "name": symbol_names.get(symbol, symbol),
                "candidate_type": candidate_type,
                "candidate_label": "持仓复核" if candidate_type == "holding" else "交易前终审",
                "draft_action": draft_action,
                "proposed_action": draft_action,
                "review_status": review_status,
                "reviewed_action": reviewed_action,
                "final_action": reviewed_action,
                "confidence": float(row.get("confidence") or 0.0),
                "reason": reason or fallback_reason or "本轮实时 AI 复核未返回额外说明。",
                "fallback_reason": fallback_reason,
                "error_code": str(row.get("error_code") or ""),
                "latency_ms": int(row.get("latency_ms") or 0),
                "applied": applied,
            }
        )
    return {
        "enabled": bool(SETTINGS.ai.realtime_action_review_enabled or SETTINGS.ai.realtime_position_review_enabled),
        "action_review_enabled": bool(SETTINGS.ai.realtime_action_review_enabled),
        "position_review_enabled": bool(SETTINGS.ai.realtime_position_review_enabled),
        "review_count": len(items),
        "changed_count": changed_count,
        "pending_count": pending_count,
        "done_count": done_count,
        "degraded_count": degraded_count,
        "action_review_count": action_review_count,
        "holding_review_count": holding_review_count,
        "items": items[:6],
    }


def get_action_summary(account_id: str | None = None) -> Dict[str, int]:
    live_state = _load_live_state(account_id)
    cards = build_action_cards(
        live_state.get("final_actions") or [],
        live_state.get("risk_results") or [],
        _symbol_name_map(SETTINGS, account_id=account_id),
    )
    current = summarize_action_cards(cards)
    today = _today_action_summary(account_id=account_id)
    return {
        "intent_count": max(int(current.get("intent_count") or 0), int(today.get("intent_count") or 0)),
        "executed_count": max(int(current.get("executed_count") or 0), int(today.get("executed_count") or 0)),
        "blocked_count": max(int(current.get("blocked_count") or 0), int(today.get("blocked_count") or 0)),
    }


def _today_action_summary(account_id: str | None = None) -> Dict[str, int]:
    today = datetime.now().date().isoformat()
    rows = _query_rows(
        """
        SELECT status, intent_only
        FROM orders
        WHERE date(ts) = ?
        """,
        (today,),
        account_id=account_id,
    )
    intent_count = 0
    executed_count = 0
    blocked_count = 0
    for row in rows:
        status = str(row.get("status") or "").upper()
        intent_only = bool(row.get("intent_only"))
        if intent_only or status == "INTENT_ONLY":
            intent_count += 1
        elif status in {"FILLED", "PARTIAL_FILLED"}:
            executed_count += 1
        elif status == "REJECTED":
            blocked_count += 1
    return {
        "intent_count": intent_count,
        "executed_count": executed_count,
        "blocked_count": blocked_count,
    }


def _hydrate_strategy_performance(summary: Dict[str, object], account_id: str | None = None) -> Dict[str, object]:
    if any(int((item or {}).get("trades") or 0) > 0 for item in summary.values() if isinstance(item, dict)):
        return summary
    conn = connect_db(SETTINGS, account_id=account_id)
    try:
        refreshed = StrategyEvaluationService(SETTINGS).evaluate_strategy_performance(conn, window_days=3)
    except Exception:
        refreshed = summary
    finally:
        conn.close()
    ranked = sorted(
        refreshed.items(),
        key=lambda kv: (
            -int((kv[1] or {}).get("trades") or 0),
            -float((kv[1] or {}).get("win_rate") or 0.0),
            -float((kv[1] or {}).get("score_total") or 0.0),
            kv[0],
        ),
    )
    return {name: item for name, item in ranked}


def _fallback_adaptive_adjustments(
    adaptive_weights: Dict[str, object],
    strategy_performance: Dict[str, object],
    style_profile: Dict[str, object],
    account_id: str | None = None,
) -> List[Dict[str, object]]:
    history_rows = _query_rows(
        """
        SELECT key_name, old_value, new_value, reason, ts
        FROM adaptive_weight_history
        ORDER BY ts DESC, id DESC
        LIMIT 3
        """,
        account_id=account_id,
    )
    if history_rows:
        return [
            {
                "key": str(row.get("key_name") or "调整"),
                "old_value": float(row.get("old_value") or 0.0),
                "new_value": float(row.get("new_value") or 0.0),
                "reason": str(row.get("reason") or "已按近期表现做平滑调整。"),
            }
            for row in history_rows
        ]
    performance_items = list(strategy_performance.values())
    total_trades = sum(int(item.get("trades") or 0) for item in performance_items if isinstance(item, dict))
    ai_multiplier = float(adaptive_weights.get("ai_score_multiplier") or 1.0)
    risk_multiplier = float(adaptive_weights.get("risk_penalty_multiplier") or 1.0)
    style_label = str(style_profile.get("style") or "balanced")
    if total_trades <= 0:
        return [
            {
                "key": "当前权重",
                "old_value": ai_multiplier,
                "new_value": ai_multiplier,
                "reason": "最近可用于学习的成交样本仍不足，系统暂时保持当前自适应权重不变。",
            }
        ]
    return [
        {
            "key": "AI 加分倍率",
            "old_value": ai_multiplier,
            "new_value": ai_multiplier,
            "reason": f"当前学习层已启用，最近风格为 {style_label}，暂未触发新的权重调整。",
        },
        {
            "key": "风险惩罚倍率",
            "old_value": risk_multiplier,
            "new_value": risk_multiplier,
            "reason": "近期表现未触发新的平滑调权，系统继续沿用当前风险惩罚倍率。",
        },
    ]


def _latest_error(account_id: str | None = None) -> Tuple[str | None, str | None]:
    rows = _query_rows(
        "SELECT ts, message FROM system_logs WHERE level = 'ERROR' ORDER BY id DESC LIMIT 1",
        account_id=account_id,
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


def _normalize_pct_change(value: object) -> float:
    raw = float(value or 0.0)
    return raw / 100.0 if abs(raw) > 1.0 else raw


def _heartbeat_running(last_updated_at: str | None, refresh_interval_seconds: int) -> bool:
    updated_dt = _parse_iso_ts(last_updated_at)
    if not updated_dt:
        return False
    stale_seconds = max(30, int(refresh_interval_seconds) * 3)
    return (datetime.now() - updated_dt).total_seconds() <= stale_seconds


def _system_status(account_id: str | None = None) -> Dict[str, object]:
    engine_pid = _read_pid(ENGINE_PID_PATH)
    live_state = _load_live_state(account_id)
    account = get_account_snapshot(account_id=account_id)
    last_error, last_error_ts = _latest_error(account_id=account_id)
    last_updated = str(live_state.get("ts") or account.get("ts") or "")
    engine_running = _pid_alive(engine_pid) or _heartbeat_running(last_updated or None, SETTINGS.refresh_interval_seconds)
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


def get_home_view(account_id: str | None = None) -> Dict[str, object]:
    _ensure_home_runtime_ready()
    resolved_account_id = _resolve_account_id(account_id)
    live_state = _load_live_state(resolved_account_id)
    phase = get_current_phase(account_id=resolved_account_id)
    execution = get_execution_gate(account_id=resolved_account_id)
    names = _symbol_name_map(SETTINGS, account_id=resolved_account_id)
    actions = build_action_cards(live_state.get("final_actions") or [], live_state.get("risk_results") or [], names)
    account = get_account_snapshot(account_id=resolved_account_id)
    ai_decisions = get_latest_ai_decisions(account_id=resolved_account_id)
    manager = live_state.get("ai_portfolio_manager") if isinstance(live_state, dict) else {}
    ai_runtime = _build_ai_runtime(SETTINGS, live_state)
    strategy_status = build_ai_strategy_status(
        actions,
        ai_decisions,
        manager if isinstance(manager, dict) else {},
        ai_runtime,
    )
    stats = get_action_summary(account_id=resolved_account_id)
    system_status = _system_status(account_id=resolved_account_id)
    summary = build_home_summary(
        system_status=system_status,
        phase=phase,
        actions=actions,
        strategy_status=strategy_status,
    )
    observe_candidates = _build_observe_candidates(
        SETTINGS,
        live_state,
        phase,
        execution,
        strategy_status,
    )
    no_buy_reasons = build_no_buy_reasons(
        system_status=system_status,
        phase=phase,
        execution=execution,
        actions=actions,
        strategy_status=strategy_status,
    )
    executable_buy_count = sum(
        1 for row in actions if bool(row.get("executable_now")) and str(row.get("action") or "") == "BUY"
    )
    executable_reduce_count = sum(
        1
        for row in actions
        if bool(row.get("executable_now")) and str(row.get("action") or "") in {"SELL", "REDUCE"}
    )
    timeline = get_recent_action_timeline(settings=SETTINGS, account_id=resolved_account_id)
    for row in timeline:
        symbol = str(row.get("symbol") or "")
        row["name"] = names.get(symbol, symbol)
    watchlist = _build_watchlist_entries(SETTINGS, live_state, names, ai_decisions, account_id=resolved_account_id)
    watchlist_sections = _build_watchlist_sections(watchlist, SETTINGS)
    trade_explanations = _build_trade_explanations(names, ai_decisions, watchlist, account_id=resolved_account_id)
    realtime_ai_reviews = _build_realtime_ai_review_summary(live_state, names)
    realized_breakdown = _build_realized_breakdown(
        names,
        account_id=resolved_account_id,
        expected_total=float(account.get("realized_pnl") or 0.0),
    )
    style_profile = dict(live_state.get("style_profile") or {})
    strategy_performance = _hydrate_strategy_performance(
        dict(live_state.get("strategy_performance") or {}),
        account_id=resolved_account_id,
    )
    adaptive_weights = dict(live_state.get("adaptive_weights") or {})
    adaptive_adjustments = list(adaptive_weights.get("adjustments") or [])
    if not adaptive_adjustments:
        adaptive_adjustments = _fallback_adaptive_adjustments(
            adaptive_weights,
            strategy_performance,
            style_profile,
            account_id=resolved_account_id,
        )
    chart_symbol = _select_chart_symbol(watchlist, timeline, ai_decisions)
    core_symbol = _build_core_symbol(watchlist, ai_decisions, timeline)
    score_breakdowns = sorted(
        [row for row in ai_decisions if row.get("symbol")],
        key=lambda item: abs(SETTINGS.scoring.min_execution_score_to_buy - float(item.get("execution_score") or 0.0)),
    )[:3]
    charts = {
        "selected_symbol": chart_symbol,
        "intraday": get_intraday_chart_data(chart_symbol, SETTINGS) if chart_symbol else {"symbol": "", "points": []},
        "kline": get_kline_chart_data(chart_symbol, SETTINGS) if chart_symbol else {"symbol": "", "rows": []},
        "equity": get_equity_curve_data(SETTINGS, account_id=resolved_account_id),
    }
    return {
        "accounts": _available_accounts(),
        "current_account_id": resolved_account_id,
        "current_account_name": str(account.get("account_name") or resolved_account_id),
        "summary": summary,
        "system_status": system_status,
        "engine_mode": str(live_state.get("engine_mode") or SETTINGS.runtime.engine_mode),
        "phase": phase,
        "execution": execution,
        "strategy_status": strategy_status,
        "ai_runtime": ai_runtime,
        "actions": actions,
        "observe_candidates": observe_candidates,
        "no_buy_reasons": no_buy_reasons,
        "account": account,
        "stats": stats,
        "watchlist": watchlist,
        "watchlist_sections": watchlist_sections,
        "trade_explanations": trade_explanations,
        "realtime_ai_reviews": realtime_ai_reviews,
        "realized_breakdown": realized_breakdown,
        "style_profile": style_profile,
        "strategy_performance": strategy_performance,
        "adaptive_weights": adaptive_weights,
        "adaptive_adjustments": adaptive_adjustments[:3],
        "report_links": _latest_report_links(),
        "core_symbol": core_symbol,
        "timeline": timeline,
        "charts": charts,
        "opportunities": {
            "buy_count": executable_buy_count,
            "reduce_count": executable_reduce_count,
            "top_limitations": no_buy_reasons[:3],
            "top_candidates": _build_top_opportunity_candidates(ai_decisions, SETTINGS),
        },
        "score_breakdowns": score_breakdowns,
    }


def get_debug_view(account_id: str | None = None) -> Dict[str, object]:
    _ensure_home_runtime_ready()
    resolved_account_id = _resolve_account_id(account_id)
    status = _system_status(account_id=resolved_account_id)
    logs = _query_rows(
        "SELECT ts, level, module, message FROM system_logs ORDER BY id DESC LIMIT 12",
        account_id=resolved_account_id,
    )
    return {
        "accounts": _available_accounts(),
        "current_account_id": resolved_account_id,
        "system_status": status,
        "logs": logs,
        "dashboard_url": status.get("dashboard_url"),
    }
