from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

import pandas as pd
import requests
import streamlit as st
import yaml

from app.db import connect_db, fetch_recent_equity_curve, fetch_recent_rows
from app.evaluation_service import EvaluationService
from app.manual_execution_service import ManualExecutionService
from app.settings import get_primary_simulation_account, load_settings, resolve_simulation_accounts
from app.watchlist_service import get_active_watchlist
from app.watchlist_sync_service import load_runtime_watchlist


st.set_page_config(page_title="AI Stock Sim 调试面板", layout="wide")
settings = load_settings(Path(__file__).resolve().parents[1])
SIMULATION_ACCOUNTS = resolve_simulation_accounts(settings)
PRIMARY_ACCOUNT = get_primary_simulation_account(settings)
evaluation_service = EvaluationService(settings)
manual_execution_service = ManualExecutionService(settings)
SYMBOL_NAME_CACHE: Dict[str, str] = {}
EASTMONEY_NAME_RETRY_ATTEMPTS = 3
EASTMONEY_NAME_RETRY_BACKOFF_SECONDS = 0.25


COLOR_MAP = {
    "profit": "#0f9d58",
    "loss": "#db4437",
    "warn": "#f29900",
    "reject": "#9aa0a6",
    "ai": "#2563eb",
}

MODE_LABELS = {
    "legacy_review_mode": "旧模式：策略主导 + AI 审批",
    "ai_decision_engine_mode": "新模式：AI 决策引擎",
    "compare_mode": "对照模式：新旧同时输出",
}

FLOWCHART_TEXT = """\
旧模式：
实时行情
 -> 股票池筛选
 -> 六套策略输出候选信号
 -> AI 审核员复核
 -> 风控
 -> 模拟成交
 -> 更新账户

新模式：
实时行情
 -> 股票池筛选
 -> 六套策略输出特征与分数
 -> 决策上下文构建
 -> AI 决策引擎
 -> 风控
 -> 模拟成交
 -> 更新账户

对照模式：
同一轮行情
 -> 旧模式产出动作
 -> 新模式产出动作
 -> 记录差异
 -> 控制台展示对照结果
"""


@st.cache_data(ttl=5)
def load_table(table: str, limit: int = 50, account_id: str | None = None) -> pd.DataFrame:
    conn = connect_db(settings, account_id=account_id)
    try:
        rows = fetch_recent_rows(conn, table, limit=limit)
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


@st.cache_data(ttl=5)
def load_equity_curve(account_id: str | None = None) -> pd.DataFrame:
    conn = connect_db(settings, account_id=account_id)
    try:
        rows = fetch_recent_equity_curve(conn, limit=200)
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


@st.cache_data(ttl=5)
def load_live_state(account_id: str | None = None) -> Dict[str, object]:
    path = settings.resolved_account_live_state_path(account_id) if account_id else settings.live_state_path
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@st.cache_data(ttl=5)
def load_accounts_overview() -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for account in SIMULATION_ACCOUNTS:
        conn = connect_db(settings, account_id=account.account_id)
        try:
            account_rows = fetch_recent_rows(conn, "account_snapshots", limit=1)
            latest_row = dict(account_rows[0]) if account_rows else {}
            positions_df = pd.DataFrame([dict(row) for row in fetch_recent_rows(conn, "positions", limit=100)])
        except sqlite3.Error:
            latest_row = {}
            positions_df = pd.DataFrame()
        finally:
            conn.close()
        rows.append(
            {
                "account_id": account.account_id,
                "账户": account.name,
                "是否主账户": "是" if account.account_id == PRIMARY_ACCOUNT.account_id else "否",
                "初始资金": float(account.initial_cash),
                "总权益": float(latest_row.get("equity") or 0.0),
                "现金": float(latest_row.get("cash") or 0.0),
                "持仓市值": float(latest_row.get("market_value") or 0.0),
                "回撤": float(latest_row.get("drawdown") or 0.0),
                "持仓数": int(len(positions_df)),
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=10)
def load_symbol_name_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    market_cache_dir = settings.cache_dir / "market"
    for cache_path in sorted(market_cache_dir.glob("snapshot_combined_*.json"), reverse=True):
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("rows") or []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").strip()
                name = str(row.get("name") or "").strip()
                if symbol and name and symbol not in mapping:
                    mapping[symbol] = name
        if mapping:
            break
    return mapping


@st.cache_data(ttl=30)
def fetch_eastmoney_symbol_names(symbols: tuple[str, ...]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip()
        if len(symbol) != 6 or not symbol.isdigit():
            continue
        cached_name = SYMBOL_NAME_CACHE.get(symbol)
        if cached_name:
            mapping[symbol] = cached_name
            continue
        market = "1" if symbol.startswith(("5", "6", "9")) else "0"
        for attempt in range(1, EASTMONEY_NAME_RETRY_ATTEMPTS + 1):
            try:
                response = session.get(
                    "https://push2.eastmoney.com/api/qt/stock/get",
                    params={
                        "secid": f"{market}.{symbol}",
                        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                        "invt": 2,
                        "fltt": 2,
                        "fields": "f57,f58",
                    },
                    timeout=2.5,
                )
                response.raise_for_status()
                data = (response.json().get("data") or {})
                name = str(data.get("f58") or "").strip()
                if name:
                    SYMBOL_NAME_CACHE[symbol] = name
                    mapping[symbol] = name
                break
            except Exception:
                if attempt < EASTMONEY_NAME_RETRY_ATTEMPTS:
                    time.sleep(EASTMONEY_NAME_RETRY_BACKOFF_SECONDS * attempt)
    return mapping


def attach_symbol_name(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "symbol" not in df.columns or "name" in df.columns:
        return df
    mapping = load_symbol_name_map()
    enriched = df.copy()
    symbols = enriched["symbol"].astype(str)
    missing = tuple(sorted({symbol for symbol in symbols if len(symbol) == 6 and symbol not in mapping}))
    if missing:
        mapping = {**mapping, **fetch_eastmoney_symbol_names(missing)}
    insert_at = int(enriched.columns.get_loc("symbol")) + 1
    enriched.insert(insert_at, "name", symbols.map(lambda symbol: mapping.get(symbol, symbol)))
    return enriched


@st.cache_data(ttl=10)
def load_watchlist_payload() -> Dict[str, object]:
    payload = load_runtime_watchlist(settings)
    if payload.get("symbols"):
        return payload
    return get_active_watchlist(settings)


def color_text(text: str, color_key: str) -> str:
    return f"<span style='color:{COLOR_MAP[color_key]};font-weight:600'>{text}</span>"


def render_value(label: str, value: float, percent: bool = False) -> None:
    color_key = "profit" if value > 0 else "loss" if value < 0 else "reject"
    display = f"{value:.2%}" if percent else f"{value:.4f}"
    st.markdown(f"**{label}**：{color_text(display, color_key)}", unsafe_allow_html=True)


def render_status_badge(label: str, color_key: str) -> None:
    st.markdown(f"<span style='background:{COLOR_MAP[color_key]};color:white;padding:4px 10px;border-radius:999px;font-size:0.85rem'>{label}</span>", unsafe_allow_html=True)


def _latest_by_strategy(df: pd.DataFrame, period_type: str, prefix: str = "") -> pd.DataFrame:
    if df.empty:
        return df
    working = df.copy()
    if "ts" in working.columns:
        working["_ts"] = pd.to_datetime(working["ts"], errors="coerce")
    else:
        working["_ts"] = pd.Timestamp.utcnow()
    filtered = working[working["period_type"].astype(str) == period_type]
    if prefix:
        filtered = filtered[filtered["strategy_name"].astype(str).str.startswith(prefix)]
    else:
        filtered = filtered[~filtered["strategy_name"].astype(str).str.startswith("exit::")]
        filtered = filtered[filtered["strategy_name"].astype(str) != "portfolio_actual"]
    if filtered.empty:
        return filtered
    latest = (
        filtered.sort_values("_ts", ascending=False)
        .drop_duplicates(subset=["strategy_name"], keep="first")
        .drop(columns=["_ts"])
    )
    return latest.sort_values("score_total", ascending=False)


def _display_strategy_name(raw: str) -> str:
    if raw.startswith("exit::"):
        return raw.replace("exit::", "卖出-", 1)
    return raw


def _parse_metadata_json(raw: object) -> Dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _comparison_basis_label(basis: object) -> str:
    mapping = {
        "actual_closed_trades": "模拟成交闭环",
        "signal_forward_return_proxy": "信号 5 日代理收益",
    }
    return mapping.get(str(basis or ""), "未标注")


def _sample_note(trade_count: object) -> str:
    count = int(trade_count or 0)
    if count <= 0:
        return "样本缺口"
    if count < 3:
        return "样本偏少"
    return "样本正常"


def _display_grade(row: Mapping[str, object]) -> str:
    grade = str(row.get("grade") or "-")
    return f"{grade}（{_sample_note(row.get('total_trades'))}）"


def load_post_close_execution_flag() -> bool:
    settings_path = settings.project_root / "config" / "settings.yaml"
    try:
        payload = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return bool(settings.market_session.allow_post_close_paper_execution)
    market_session = payload.get("market_session") or {}
    return bool(market_session.get("allow_post_close_paper_execution", settings.market_session.allow_post_close_paper_execution))


def save_post_close_execution_flag(enabled: bool) -> None:
    settings_path = settings.project_root / "config" / "settings.yaml"
    payload = {}
    if settings_path.exists():
        payload = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    market_session = payload.get("market_session") or {}
    market_session["allow_post_close_paper_execution"] = bool(enabled)
    payload["market_session"] = market_session
    settings_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_decision_mode() -> str:
    settings_path = settings.project_root / "config" / "settings.yaml"
    try:
        payload = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return str(settings.decision_engine.mode)
    decision_engine = payload.get("decision_engine") or {}
    return str(decision_engine.get("mode") or settings.decision_engine.mode)


def save_decision_mode(mode_name: str) -> None:
    settings_path = settings.project_root / "config" / "settings.yaml"
    payload = {}
    if settings_path.exists():
        payload = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    decision_engine = payload.get("decision_engine") or {}
    decision_engine["mode"] = mode_name
    payload["decision_engine"] = decision_engine
    settings_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


if "auto_refresh" not in st.session_state:
    st.session_state["auto_refresh"] = False
if "allow_post_close_execution" not in st.session_state:
    st.session_state["allow_post_close_execution"] = load_post_close_execution_flag()
if "decision_engine_mode" not in st.session_state:
    st.session_state["decision_engine_mode"] = load_decision_mode()
if "selected_account_id" not in st.session_state:
    st.session_state["selected_account_id"] = PRIMARY_ACCOUNT.account_id

st.title("AI 股票模拟交易调试面板")
st.caption("这里保留特征、上下文、风控、日志和模式对照；默认产品入口请回到 8600 的 AI 首页。")

toolbar_left, toolbar_mid, toolbar_right, toolbar_account = st.columns([2.4, 1.1, 1.1, 1.8])
with toolbar_left:
    selected_account = next((item for item in SIMULATION_ACCOUNTS if item.account_id == st.session_state["selected_account_id"]), PRIMARY_ACCOUNT)
    st.write(f"当前账户库：`{settings.resolved_account_db_path(selected_account.account_id) if settings.simulation_accounts else settings.db_path}`")
with toolbar_mid:
    st.session_state["auto_refresh"] = st.toggle("局部自动刷新", value=st.session_state["auto_refresh"])
with toolbar_right:
    if st.button("立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with toolbar_account:
    selected_account_id = st.selectbox(
        "模拟账户",
        [item.account_id for item in SIMULATION_ACCOUNTS],
        index=next((idx for idx, item in enumerate(SIMULATION_ACCOUNTS) if item.account_id == st.session_state["selected_account_id"]), 0),
        format_func=lambda account_id: next((item.name for item in SIMULATION_ACCOUNTS if item.account_id == account_id), account_id),
    )
    st.session_state["selected_account_id"] = selected_account_id

with st.container(border=True):
    st.markdown("**模拟时段设置**")
    setting_cols = st.columns([1.4, 1.0, 1.2])
    with setting_cols[0]:
        st.toggle(
            "允许盘后生成次日准备动作",
            key="allow_post_close_execution",
            help="打开后，收盘后会保留 PREPARE_BUY / PREPARE_REDUCE 这类次日准备动作；关闭时更偏保守，只保留复盘与观察建议。",
        )
    with setting_cols[1]:
        current_label = "盘后次日准备：开启" if st.session_state["allow_post_close_execution"] else "盘后仅复盘（推荐）"
        render_status_badge(current_label, "ai" if st.session_state["allow_post_close_execution"] else "warn")
    with setting_cols[2]:
        if st.button("保存盘后模式", use_container_width=True):
            save_post_close_execution_flag(bool(st.session_state["allow_post_close_execution"]))
            st.success("设置已保存。重启 8600 中的实时引擎后生效。")
    st.caption("这个设置会写回 config/settings.yaml。它只影响盘后是否保留次日准备意图，不会在盘后新增真实模拟成交。")

with st.container(border=True):
    st.markdown("**决策模式设置**")
    mode_cols = st.columns([1.3, 1.0, 1.1])
    with mode_cols[0]:
        options = list(MODE_LABELS.keys())
        current_index = options.index(st.session_state["decision_engine_mode"]) if st.session_state["decision_engine_mode"] in options else 1
        selected_mode = st.selectbox(
            "当前决策模式",
            options,
            index=current_index,
            format_func=lambda item: MODE_LABELS.get(item, item),
        )
        st.session_state["decision_engine_mode"] = selected_mode
    with mode_cols[1]:
        render_status_badge(MODE_LABELS.get(st.session_state["decision_engine_mode"], st.session_state["decision_engine_mode"]), "ai")
    with mode_cols[2]:
        if st.button("保存决策模式", use_container_width=True):
            save_decision_mode(st.session_state["decision_engine_mode"])
            st.success("决策模式已保存。重启实时引擎后生效。")
    st.caption("第四阶段开始，AI 决策引擎与旧模式可以并行存在。推荐日常先看“新模式”，想做差异研究时再切到“对照模式”。")

run_every = f"{settings.dashboard.auto_refresh_seconds}s" if st.session_state["auto_refresh"] else None


@st.fragment(run_every=run_every)
def render_dashboard() -> None:
    selected_account_id = str(st.session_state.get("selected_account_id") or PRIMARY_ACCOUNT.account_id)
    selected_account = next((item for item in SIMULATION_ACCOUNTS if item.account_id == selected_account_id), PRIMARY_ACCOUNT)
    signals_df = attach_symbol_name(load_table("signals", limit=50, account_id=selected_account_id))
    ai_df = attach_symbol_name(load_table("ai_decisions", limit=50, account_id=selected_account_id))
    final_signals_df = attach_symbol_name(load_table("final_signals", limit=50, account_id=selected_account_id))
    positions_df = attach_symbol_name(load_table("positions", limit=30, account_id=selected_account_id))
    orders_df = attach_symbol_name(load_table("orders", limit=80, account_id=selected_account_id))
    logs_df = attach_symbol_name(load_table("system_logs", limit=200, account_id=selected_account_id))
    equity_df = load_equity_curve(account_id=selected_account_id)
    account_df = load_table("account_snapshots", limit=1, account_id=selected_account_id)
    evaluations_df = load_table("strategy_evaluations", limit=300, account_id=selected_account_id)
    comparisons_df = load_table("mode_comparisons", limit=20, account_id=selected_account_id)
    manual_df = attach_symbol_name(load_table("manual_execution_logs", limit=50, account_id=selected_account_id))
    attribution_df = attach_symbol_name(load_table("decision_snapshots", limit=300, account_id=selected_account_id))
    realtime_review_df = attach_symbol_name(load_table("realtime_ai_review_events", limit=300, account_id=selected_account_id))
    adaptive_history_df = load_table("adaptive_weight_history", limit=300, account_id=selected_account_id)
    style_history_df = load_table("style_profile_history", limit=120, account_id=selected_account_id)
    live_state = load_live_state(account_id=selected_account_id)
    accounts_overview_df = load_accounts_overview()

    st.caption(f"当前查看账户：{selected_account.name}（{selected_account.account_id}） | 上次数据刷新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if evaluations_df.empty:
        conn = connect_db(settings, account_id=selected_account_id)
        try:
            evaluation_service.persist_evaluations(conn, reference_date=datetime.now().date().isoformat())
            conn.commit()
        finally:
            conn.close()
        st.cache_data.clear()
        evaluations_df = load_table("strategy_evaluations", limit=80, account_id=selected_account_id)
        comparisons_df = load_table("mode_comparisons", limit=20, account_id=selected_account_id)

    current_mode = str((live_state or {}).get("decision_mode") or settings.decision_engine.mode)
    current_engine_mode = str((live_state or {}).get("engine_mode") or settings.runtime.engine_mode)
    mode_label = MODE_LABELS.get(current_mode, current_mode)
    phase_name = str((live_state or {}).get("phase", "-"))
    trading_calendar = live_state.get("trading_calendar") if isinstance(live_state, dict) else {}
    execution_gate = live_state.get("execution_gate") if isinstance(live_state, dict) else {}
    watchlist_payload = load_watchlist_payload()
    weights = live_state.get("strategy_weights") if isinstance(live_state, dict) else {}
    context_map = live_state.get("decision_contexts") if isinstance(live_state, dict) else {}
    feature_map = live_state.get("feature_fusions") if isinstance(live_state, dict) else {}
    reviewer = live_state.get("ai_reviewer") if isinstance(live_state, dict) else []
    reviewer_df = attach_symbol_name(pd.DataFrame(reviewer)) if reviewer else pd.DataFrame()
    engine_payload = live_state.get("ai_decision_engine") if isinstance(live_state, dict) else {}
    manager = live_state.get("ai_portfolio_manager") if isinstance(live_state, dict) else {}
    final_actions = live_state.get("final_actions") if isinstance(live_state, dict) else []
    risks = live_state.get("risk_results") if isinstance(live_state, dict) else []
    actions_df = attach_symbol_name(pd.DataFrame(final_actions)) if final_actions else pd.DataFrame()
    risk_df = attach_symbol_name(pd.DataFrame(risks)) if risks else pd.DataFrame()
    performance_summary = dict((live_state or {}).get("strategy_performance") or {})
    adaptive_state = dict((live_state or {}).get("adaptive_weights") or {})
    regime = live_state.get("market_regime") if isinstance(live_state, dict) else {}
    style_profile = live_state.get("style_profile") if isinstance(live_state, dict) else {}
    live_compare = live_state.get("decision_compare") if isinstance(live_state, dict) else {}
    post_close_intents = orders_df[orders_df["phase"].astype(str) == "POST_CLOSE"] if not orders_df.empty and "phase" in orders_df.columns else pd.DataFrame()
    if not orders_df.empty and "intent_only" in orders_df.columns:
        actual_orders = orders_df[
            (orders_df["intent_only"] == 0)
            & (orders_df["status"].astype(str).isin(["FILLED", "PARTIAL_FILLED"]) if "status" in orders_df.columns else True)
        ]
        intent_orders = orders_df[(orders_df["intent_only"] == 1) | (orders_df["status"].astype(str) == "INTENT_ONLY" if "status" in orders_df.columns else False)]
    elif not orders_df.empty and "status" in orders_df.columns:
        actual_orders = orders_df[orders_df["status"].astype(str).str.contains("FILLED", na=False)]
        intent_orders = orders_df[orders_df["status"].astype(str) == "INTENT_ONLY"]
    else:
        actual_orders = pd.DataFrame()
        intent_orders = pd.DataFrame()

    bad_decisions = pd.DataFrame((live_state or {}).get("bad_decisions") or [])
    if bad_decisions.empty and not attribution_df.empty and "result_return" in attribution_df.columns:
        bad_decisions = attribution_df[attribution_df["result_return"].fillna(0) < 0].copy()
        if "result_return" in bad_decisions.columns:
            bad_decisions = bad_decisions.sort_values("result_return", ascending=True).head(10)

    comparison_display_df = comparisons_df.copy()
    if not comparison_display_df.empty:
        comparison_display_df["metadata"] = comparison_display_df["metadata_json"].map(_parse_metadata_json)
        comparison_display_df["样本来源"] = comparison_display_df["metadata"].map(lambda item: _comparison_basis_label(item.get("basis")))
        comparison_display_df["样本数"] = comparison_display_df["metadata"].map(lambda item: int(item.get("trades") or 0))
        comparison_display_df["显示模式"] = comparison_display_df["mode_name"].map(
            {
                "legacy_review_mode": "旧模式：策略主导 + AI 审批",
                "ai_decision_engine_mode": "新模式：AI 决策引擎",
                "strategy_only": "纯策略",
                "strategy_plus_ai": "策略+AI",
                "strategy_plus_risk": "策略+风控",
                "strategy_plus_ai_plus_risk": "策略+AI+风控",
            }
        ).fillna(comparison_display_df["mode_name"])

    with st.container(border=True):
        st.markdown("**当前运行模式**")
        summary_cols = st.columns(6)
        summary_cols[0].metric("决策模式", mode_label)
        summary_cols[1].metric("引擎模式", current_engine_mode)
        summary_cols[2].metric("当前阶段", phase_name)
        summary_cols[3].metric("AI 决策标的数", len((live_state or {}).get("ai_decision_engine") or {}))
        summary_cols[4].metric("计划动作数", len((live_state or {}).get("final_actions") or []))
        summary_cols[5].metric("可成交", "是" if bool((execution_gate or {}).get("can_execute_fill")) else "否")
        if isinstance(trading_calendar, dict) and trading_calendar:
            st.caption(
                f"交易日：{'是' if bool(trading_calendar.get('is_trading_day')) else '否'} | "
                f"下一交易日：{trading_calendar.get('next_trading_day') or '-'} | "
                f"最近交易日：{trading_calendar.get('previous_trading_day') or '-'}"
            )
        with st.expander("查看当前版本 AI 单次轮询流程图"):
            st.code(FLOWCHART_TEXT, language="text")

    visible_tab_titles = ["当前模式与总览"]
    if isinstance(trading_calendar, dict) and trading_calendar:
        visible_tab_titles.append("交易日历状态")
    if phase_name != "-" or (isinstance(execution_gate, dict) and execution_gate):
        visible_tab_titles.append("当前交易阶段")
    if isinstance(execution_gate, dict) and execution_gate:
        visible_tab_titles.append("当前执行权限")
    if not actions_df.empty or not orders_df.empty:
        visible_tab_titles.append("动作意图 vs 实际成交")
    if phase_name == "POST_CLOSE" or not post_close_intents.empty or bool((execution_gate or {}).get("can_generate_report")):
        visible_tab_titles.append("盘后模式")
    if isinstance(regime, dict) and regime:
        visible_tab_titles.append("市场状态机")
    if isinstance(weights, dict) and weights:
        visible_tab_titles.append("策略权重")
    if (isinstance(context_map, dict) and context_map) or (isinstance(feature_map, dict) and feature_map):
        visible_tab_titles.append("AI 决策输入")
    if current_mode in {"legacy_review_mode", "compare_mode"} or not reviewer_df.empty:
        visible_tab_titles.append("AI 审核员")
    if current_mode in {"ai_decision_engine_mode", "compare_mode"} or (isinstance(engine_payload, dict) and engine_payload) or (isinstance(manager, dict) and manager):
        visible_tab_titles.append("AI 决策中心")
    if not realtime_review_df.empty or bool((live_state or {}).get("realtime_ai_reviews")):
        visible_tab_titles.append("实时终审对照")
    if not actions_df.empty or not risk_df.empty:
        visible_tab_titles.append("执行结果")
    visible_tab_titles.extend(["账户与持仓", "策略评估"])
    if performance_summary or not evaluations_df.empty:
        visible_tab_titles.append("策略表现分析")
    if not attribution_df.empty:
        visible_tab_titles.append("决策归因分析")
    if adaptive_state or not adaptive_history_df.empty:
        visible_tab_titles.append("权重变化历史")
    if regime or style_profile or not style_history_df.empty:
        visible_tab_titles.append("市场状态与风格")
    if not bad_decisions.empty:
        visible_tab_titles.append("错误决策分析")
    if not evaluations_df.empty:
        visible_tab_titles.append("周期统计")
    if (isinstance(live_compare, dict) and live_compare.get("rows")) or not comparisons_df.empty or current_mode == "compare_mode":
        visible_tab_titles.append("模式对照")
    if not orders_df.empty or not manual_df.empty:
        visible_tab_titles.append("成交流水")
    visible_tab_titles.extend(["日志筛选", "人工回填"])
    tab_map = {title: tab for title, tab in zip(visible_tab_titles, st.tabs(visible_tab_titles))}

    with tab_map["当前模式与总览"]:
        st.subheader("当前模式与市场总览")
        st.write(f"当前实时主链运行在：**{mode_label}**")
        if watchlist_payload:
            st.markdown("**当前监控池生命周期**")
            watch_cols = st.columns(4)
            watch_cols[0].metric("来源", str(watchlist_payload.get("source") or "-"))
            watch_cols[1].metric("交易日", str(watchlist_payload.get("trading_day") or "-"))
            watch_cols[2].metric("生成时间", str(watchlist_payload.get("generated_at") or "-"))
            watch_cols[3].metric("过期状态", "是" if bool(watchlist_payload.get("stale")) else "否")
            evolution = dict(watchlist_payload.get("watchlist_evolution") or watchlist_payload.get("evolution") or {})
            scan_result = dict((live_state or {}).get("watchlist_scan") or {})
            if scan_result or evolution:
                event_cols = st.columns(4)
                event_cols[0].metric("最近扫描", str(scan_result.get("scan_time") or evolution.get("updated_at") or "-"))
                event_cols[1].metric("新增股票", len(evolution.get("added") or []))
                event_cols[2].metric("移除股票", len(evolution.get("removed") or []))
                event_cols[3].metric("监控池规模", len(watchlist_payload.get("symbols") or []))
            symbols = [str(item) for item in watchlist_payload.get("symbols") or []]
            if symbols:
                st.caption("当前监控池：" + "、".join(symbols[:16]))
            watch_events = (live_state or {}).get("watchlist_events") or []
            if watch_events:
                st.markdown("**监控池最近变化**")
                event_rows = attach_symbol_name(pd.DataFrame(watch_events))
                cols = [col for col in ["ts", "symbol", "name", "action", "reason", "trade_date"] if col in event_rows.columns]
                st.dataframe(event_rows[cols], use_container_width=True, hide_index=True)
        overview_cols = [col for col in ["ts", "symbol", "name", "strategy_name", "action", "score", "signal_price"] if col in signals_df.columns]
        st.dataframe(signals_df[overview_cols] if not signals_df.empty else signals_df, use_container_width=True, hide_index=True)
        if not final_signals_df.empty:
            st.markdown("**最终候选信号**")
            cols = [col for col in ["ts", "symbol", "name", "action", "confidence", "strategy_name", "mode_name"] if col in final_signals_df.columns]
            st.dataframe(final_signals_df[cols], use_container_width=True, hide_index=True)
        live_engine = live_state.get("ai_decision_engine") if isinstance(live_state, dict) else {}
        if isinstance(live_engine, dict) and live_engine:
            quick_df = attach_symbol_name(pd.DataFrame([{"symbol": key, **value} for key, value in live_engine.items()]))
            st.markdown("**AI 决策引擎本轮摘要**")
            cols = [col for col in ["symbol", "name", "action", "confidence", "setup_score", "execution_score", "ai_score", "risk_mode", "reason"] if col in quick_df.columns]
            st.dataframe(quick_df[cols], use_container_width=True, hide_index=True)
        trigger_rows = pd.DataFrame(live_state.get("trigger_decisions") or []) if isinstance(live_state, dict) else pd.DataFrame()
        if not trigger_rows.empty:
            st.markdown("**事件触发摘要**")
            st.dataframe(trigger_rows, use_container_width=True, hide_index=True)

    if "交易日历状态" in tab_map:
        with tab_map["交易日历状态"]:
            st.subheader("交易日历状态")
            if isinstance(trading_calendar, dict) and trading_calendar:
                cols = st.columns(3)
                cols[0].metric("今天是否交易日", "是" if bool(trading_calendar.get("is_trading_day")) else "否")
                cols[1].metric("下一交易日", str(trading_calendar.get("next_trading_day") or "-"))
                cols[2].metric("最近交易日", str(trading_calendar.get("previous_trading_day") or "-"))
            else:
                st.info("暂无交易日历状态。")

    if "当前交易阶段" in tab_map:
        with tab_map["当前交易阶段"]:
            st.subheader("当前交易阶段")
            phase_color = "profit" if "CONTINUOUS_AUCTION" in phase_name else "warn" if phase_name in {"PRE_OPEN", "OPEN_CALL_AUCTION", "MIDDAY_BREAK"} else "reject"
            render_status_badge(phase_name, phase_color)
            if isinstance(execution_gate, dict) and execution_gate:
                st.write(str(execution_gate.get("reason") or ""))
            else:
                st.info("暂无阶段状态。")

    if "当前执行权限" in tab_map:
        with tab_map["当前执行权限"]:
            st.subheader("当前执行权限")
            if isinstance(execution_gate, dict) and execution_gate:
                gate_df = pd.DataFrame(
                    [
                        {"权限": "更新行情", "是否允许": bool(execution_gate.get("can_update_market"))},
                        {"权限": "生成信号", "是否允许": bool(execution_gate.get("can_generate_signal"))},
                        {"权限": "运行 AI 决策", "是否允许": bool(execution_gate.get("can_run_ai_decision"))},
                        {"权限": "新开仓", "是否允许": bool(execution_gate.get("can_open_position"))},
                        {"权限": "减仓/卖出", "是否允许": bool(execution_gate.get("can_reduce_position"))},
                        {"权限": "真实模拟成交", "是否允许": bool(execution_gate.get("can_execute_fill"))},
                        {"权限": "盘后报表", "是否允许": bool(execution_gate.get("can_generate_report"))},
                    ]
                )
                st.dataframe(gate_df, use_container_width=True, hide_index=True)
            else:
                st.info("暂无执行权限数据。")

    if "动作意图 vs 实际成交" in tab_map:
        with tab_map["动作意图 vs 实际成交"]:
            st.subheader("动作意图 vs 实际成交")
            if not actions_df.empty:
                intent_df = actions_df[actions_df["intent_only"].astype(bool)] if "intent_only" in actions_df.columns else pd.DataFrame()
                exec_df = actions_df[actions_df["executable_now"].astype(bool)] if "executable_now" in actions_df.columns else pd.DataFrame()
                st.markdown("**本轮动作意图**")
                if not intent_df.empty:
                    cols = [col for col in ["symbol", "name", "action", "planned_qty", "planned_price", "phase", "reason"] if col in intent_df.columns]
                    st.dataframe(intent_df[cols], use_container_width=True, hide_index=True)
                else:
                    st.info("本轮暂无仅意图动作。")
                st.markdown("**本轮可执行动作**")
                if not exec_df.empty:
                    cols = [col for col in ["symbol", "name", "action", "planned_qty", "planned_price", "phase", "reason"] if col in exec_df.columns]
                    st.dataframe(exec_df[cols], use_container_width=True, hide_index=True)
                else:
                    st.info("本轮暂无可立即执行动作。")
            st.markdown("**订单表中的真实成交**")
            if not actual_orders.empty:
                cols = [col for col in ["ts", "symbol", "name", "side", "price", "qty", "status", "phase"] if col in actual_orders.columns]
                st.dataframe(actual_orders[cols], use_container_width=True, hide_index=True)
            else:
                st.info("暂无真实成交。")
            st.markdown("**订单表中的动作意图**")
            if not intent_orders.empty:
                cols = [col for col in ["ts", "symbol", "name", "side", "price", "qty", "status", "phase", "note"] if col in intent_orders.columns]
                st.dataframe(intent_orders[cols], use_container_width=True, hide_index=True)
            else:
                st.info("暂无动作意图记录。")

    if "盘后模式" in tab_map:
        with tab_map["盘后模式"]:
            st.subheader("盘后模式")
            post_close_cols = st.columns(4)
            post_close_cols[0].metric("当前阶段", phase_name)
            post_close_cols[1].metric("盘后策略", "保留次日准备" if st.session_state["allow_post_close_execution"] else "仅复盘分析")
            post_close_cols[2].metric("可生成报告", "是" if bool((execution_gate or {}).get("can_generate_report")) else "否")
            post_close_cols[3].metric("下一交易日", str((trading_calendar or {}).get("next_trading_day") or "-"))
            if phase_name == "POST_CLOSE":
                st.info("当前处于收盘后分析阶段。系统会继续复盘、更新监控池，并按设置决定是否保留次日准备动作；盘后不会写入真实模拟成交。")
            else:
                st.caption("当前不在盘后阶段，这里展示的是盘后开关和最近一次盘后准备结果。")

            st.markdown("**明日观察与准备动作**")
            if not post_close_intents.empty:
                cols = [col for col in ["ts", "symbol", "name", "side", "qty", "note"] if col in post_close_intents.columns]
                st.dataframe(post_close_intents[cols], use_container_width=True, hide_index=True)
            else:
                st.caption("最近一次盘后没有生成 PREPARE_* 动作。通常表示当前设置为仅复盘，或系统认为机会还不够明确。")

            if not risk_df.empty and "phase_blocked" in risk_df.columns:
                blocked_df = attach_symbol_name(risk_df[risk_df["phase_blocked"].astype(bool)].copy())
                st.markdown("**今日因阶段权限被拦截的动作**")
                if not blocked_df.empty:
                    cols = [col for col in ["symbol", "name", "action", "phase", "reason"] if col in blocked_df.columns]
                    st.dataframe(blocked_df[cols], use_container_width=True, hide_index=True)
                else:
                    st.caption("今日没有因阶段切换而被拦截的动作。")

            if watchlist_payload and (watchlist_payload.get("watchlist_evolution") or live_state.get("watchlist_events")):
                st.markdown("**盘后关注池变化**")
                watch_events = attach_symbol_name(pd.DataFrame((live_state or {}).get("watchlist_events") or []))
                if not watch_events.empty:
                    cols = [col for col in ["ts", "symbol", "name", "action", "reason"] if col in watch_events.columns]
                    st.dataframe(watch_events[cols].head(12), use_container_width=True, hide_index=True)

    if "市场状态机" in tab_map:
        with tab_map["市场状态机"]:
            st.subheader("市场状态机")
            if isinstance(regime, dict) and regime:
                metric_cols = st.columns(4)
                metric_cols[0].metric("当前 Regime", str(regime.get("regime", "-")))
                metric_cols[1].metric("置信度", f"{float(regime.get('confidence', 0.0) or 0.0):.2%}")
                metric_cols[2].metric("风险偏好", str(regime.get("risk_bias", "-")))
                metric_cols[3].metric("市场广度", f"{float(regime.get('breadth', 0.0) or 0.0):.2%}")
                st.write(str(regime.get("reason", "")))
            else:
                st.info("暂无市场状态缓存。")

    if "策略权重" in tab_map:
        with tab_map["策略权重"]:
            st.subheader("策略权重")
            if isinstance(weights, dict) and weights:
                weights_df = pd.DataFrame([{"strategy": key, "weight": value} for key, value in weights.items()]).sort_values("weight", ascending=False)
                st.bar_chart(weights_df.set_index("strategy"), use_container_width=True)
                st.dataframe(weights_df, use_container_width=True, hide_index=True)
            else:
                st.info("暂无策略权重数据。")

    if "AI 决策输入" in tab_map:
        with tab_map["AI 决策输入"]:
            st.subheader("AI 决策输入摘要")
            if isinstance(context_map, dict) and context_map:
                rows = []
                for symbol, payload in context_map.items():
                    if not isinstance(payload, dict):
                        continue
                    snapshot = dict(payload.get("snapshot") or {})
                    portfolio_state = dict(payload.get("portfolio_state") or {})
                    position_state = dict(payload.get("position_state") or {})
                    regime_snapshot = dict(payload.get("market_regime") or {})
                    fusion = dict((feature_map or {}).get(symbol) or {})
                    rows.append(
                        {
                            "symbol": symbol,
                            "latest_price": snapshot.get("latest_price"),
                            "pct_change": snapshot.get("pct_change"),
                            "amount": snapshot.get("amount"),
                            "cash_pct": portfolio_state.get("cash_pct"),
                            "drawdown": portfolio_state.get("drawdown"),
                            "has_position": position_state.get("has_position"),
                            "hold_days": position_state.get("hold_days"),
                            "market_regime": regime_snapshot.get("regime"),
                            "feature_score": fusion.get("feature_score"),
                            "final_score": fusion.get("final_score"),
                        }
                    )
                context_df = attach_symbol_name(pd.DataFrame(rows))
                cols = [col for col in ["symbol", "name", "latest_price", "pct_change", "amount", "cash_pct", "drawdown", "has_position", "hold_days", "market_regime", "feature_score", "final_score"] if col in context_df.columns]
                st.dataframe(context_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("本轮暂无 AI 决策输入摘要。")

    if "AI 审核员" in tab_map:
        with tab_map["AI 审核员"]:
            st.subheader("AI 审核员")
            st.caption("这个面板只在旧模式链路或确实存在审核结果时显示；新模式默认直接看 AI 决策中心。")
            if not reviewer_df.empty:
                cols = [col for col in ["symbol", "name", "ai_action", "approved", "confidence", "risk_score", "reason", "context_summary"] if col in reviewer_df.columns]
                st.dataframe(reviewer_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("当前没有需要展示的 AI 审核结果。")

    if "AI 决策中心" in tab_map:
        with tab_map["AI 决策中心"]:
            st.subheader("AI 决策中心")
            if isinstance(engine_payload, dict) and engine_payload:
                engine_df = attach_symbol_name(pd.DataFrame([{"symbol": symbol, **value} for symbol, value in engine_payload.items()]))
                metric_cols = st.columns(4)
                metric_cols[0].metric("新模式标的数", len(engine_df))
                metric_cols[1].metric("BUY 建议数", int((engine_df["action"].astype(str) == "BUY").sum()) if "action" in engine_df.columns else 0)
                metric_cols[2].metric("SELL/REDUCE 数", int(engine_df["action"].astype(str).isin(["SELL", "REDUCE"]).sum()) if "action" in engine_df.columns else 0)
                metric_cols[3].metric("风险模式", str(engine_df["risk_mode"].mode().iloc[0]) if "risk_mode" in engine_df.columns and not engine_df["risk_mode"].empty else "-")
                cols = [col for col in ["symbol", "name", "action", "position_pct", "reduce_pct", "confidence", "risk_mode", "final_score", "reason"] if col in engine_df.columns]
                st.dataframe(engine_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("当前模式下暂无 AI 决策引擎输出。")

            st.markdown("**组合管理器参考视图**")
            if isinstance(manager, dict) and manager:
                header_cols = st.columns(3)
                header_cols[0].metric("当前风险模式", str(manager.get("risk_mode", "-")))
                header_cols[1].metric("建议动作数", len(manager.get("actions") or []))
                header_cols[2].metric("当前阶段", phase_name)
                st.write(str(manager.get("portfolio_view", "")))
                manager_actions_df = attach_symbol_name(pd.DataFrame(manager.get("actions") or []))
                if not manager_actions_df.empty:
                    cols = [col for col in ["symbol", "name", "action", "position_pct", "reduce_pct", "priority", "reason"] if col in manager_actions_df.columns]
                    st.dataframe(manager_actions_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("暂无组合管理建议。")

    if "实时终审对照" in tab_map:
        with tab_map["实时终审对照"]:
            st.subheader("实时终审前后对照表")
            if realtime_review_df.empty:
                st.info("暂无实时终审记录。")
            else:
                review_display_df = realtime_review_df.copy()
                role_map = {
                    "VETO": "否决型",
                    "SOFTEN": "缓和型",
                    "TRIGGER": "触发型",
                    "NO_CHANGE": "未改写",
                    "ADJUST": "其他改写",
                }
                review_display_df["作用类型"] = review_display_df["review_role"].astype(str).map(role_map).fillna(review_display_df["review_role"])
                review_display_df["收盘效果"] = review_display_df["outcome_close_label"].fillna("待评估")
                metric_cols = st.columns(6)
                metric_cols[0].metric("终审总数", len(review_display_df))
                metric_cols[1].metric("已改写", int(review_display_df["applied"].fillna(0).astype(int).sum()) if "applied" in review_display_df.columns else 0)
                metric_cols[2].metric("否决型", int((review_display_df["review_role"].astype(str) == "VETO").sum()) if "review_role" in review_display_df.columns else 0)
                metric_cols[3].metric("缓和型", int((review_display_df["review_role"].astype(str) == "SOFTEN").sum()) if "review_role" in review_display_df.columns else 0)
                metric_cols[4].metric("触发型", int((review_display_df["review_role"].astype(str) == "TRIGGER").sum()) if "review_role" in review_display_df.columns else 0)
                metric_cols[5].metric(
                    "平均收盘收益改善",
                    f"{float(review_display_df['benefit_close'].fillna(0.0).mean() if 'benefit_close' in review_display_df.columns else 0.0):.2%}",
                )
                cols = [
                    col
                    for col in [
                        "ts",
                        "symbol",
                        "name",
                        "candidate_type",
                        "作用类型",
                        "proposed_action",
                        "reviewed_action",
                        "final_action",
                        "review_status",
                        "confidence",
                        "reason",
                        "latency_ms",
                        "outcome_1h_return",
                        "outcome_close_return",
                        "outcome_next_close_return",
                        "收盘效果",
                    ]
                    if col in review_display_df.columns
                ]
                st.dataframe(review_display_df[cols], use_container_width=True, hide_index=True)

    if "执行结果" in tab_map:
        with tab_map["执行结果"]:
            st.subheader("执行结果")
            if not actions_df.empty:
                cols = [col for col in ["symbol", "name", "action", "planned_qty", "planned_price", "priority", "mode_name", "reason"] if col in actions_df.columns]
                st.dataframe(actions_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("本轮暂无最终动作计划。")
            if not risk_df.empty:
                st.markdown("**风控结果**")
                cols = [col for col in ["symbol", "name", "action", "mode_name", "final_action", "allowed", "adjusted_qty", "risk_state", "reason"] if col in risk_df.columns]
                st.dataframe(risk_df[cols], use_container_width=True, hide_index=True)

    with tab_map["账户与持仓"]:
        st.subheader("账户与持仓")
        if not accounts_overview_df.empty:
            st.markdown("**多账户对比**")
            compare_df = accounts_overview_df.copy()
            compare_df["收益率"] = compare_df.apply(
                lambda row: 0.0 if float(row["初始资金"] or 0.0) <= 0 else (float(row["总权益"] or 0.0) - float(row["初始资金"] or 0.0)) / float(row["初始资金"]),
                axis=1,
            )
            st.dataframe(compare_df, use_container_width=True, hide_index=True)
        feedback = live_state.get("portfolio_feedback") if isinstance(live_state, dict) else {}
        if isinstance(feedback, dict) and feedback:
            summary_cols = st.columns(4)
            summary_cols[0].metric("当前风险模式", str(feedback.get("risk_mode", "-")))
            summary_cols[1].metric("总仓位", f"{float(feedback.get('total_position_pct', 0.0) or 0.0):.2%}")
            summary_cols[2].metric("现金占比", f"{float(feedback.get('cash_pct', 0.0) or 0.0):.2%}")
            summary_cols[3].metric("当日开仓占比", f"{float(feedback.get('today_open_ratio', 0.0) or 0.0):.2%}")
        if not account_df.empty:
            row = account_df.iloc[0]
            metric_cols = st.columns(5)
            metric_cols[0].metric("现金", f"{float(row['cash']):,.2f}")
            metric_cols[1].metric("总权益", f"{float(row['equity']):,.2f}")
            metric_cols[2].metric("持仓市值", f"{float(row['market_value']):,.2f}")
            metric_cols[3].metric("已实现盈亏", f"{float(row['realized_pnl']):,.2f}")
            metric_cols[4].metric("浮盈亏", f"{float(row['unrealized_pnl']):,.2f}")
            render_value("当前回撤", float(row["drawdown"]), percent=True)
        st.markdown("**当前持仓**")
        st.dataframe(positions_df, use_container_width=True, hide_index=True)
        st.markdown("**权益曲线**")
        if not equity_df.empty:
            equity_chart_df = equity_df.copy()
            equity_chart_df["ts_dt"] = pd.to_datetime(equity_chart_df["ts"], errors="coerce")
            equity_chart_df = equity_chart_df.dropna(subset=["ts_dt"]).sort_values("ts_dt")
            if not equity_chart_df.empty:
                st.line_chart(equity_chart_df.set_index("ts_dt")[["equity"]], use_container_width=True)
                if "drawdown" in equity_chart_df.columns:
                    st.caption("回撤单独展示，避免和总权益共轴后把权益线压扁。")
                    st.area_chart(equity_chart_df.set_index("ts_dt")[["drawdown"]], use_container_width=True)
            else:
                st.info("权益曲线时间轴为空，暂时无法绘制。")
        else:
            st.info("暂无权益曲线数据。")

    with tab_map["策略评估"]:
        st.subheader("策略评估面板")
        if evaluations_df.empty:
            st.info("暂无策略评估记录。")
        else:
            latest_daily = evaluations_df[evaluations_df["period_type"] == "daily"].head(1)
            row = latest_daily.iloc[0] if not latest_daily.empty else evaluations_df.iloc[0]
            metadata = _parse_metadata_json(row.get("metadata_json"))
            runtime_metrics = metadata.get("runtime_event_metrics") if isinstance(metadata.get("runtime_event_metrics"), dict) else {}
            trade_count = int(row.get("total_trades") or metadata.get("trade_count") or 0)

            score_cols = st.columns(4)
            score_cols[0].metric("当前策略", str(row["strategy_name"]))
            score_cols[1].metric("总分", f"{float(row['score_total']):.2f}")
            score_cols[2].metric("评级", _display_grade(row))
            score_cols[3].metric("状态", "样本待补足" if trade_count <= 0 else str(row["status"]))

            if trade_count <= 0:
                st.warning("当前很多策略的 D 级更多反映评估样本不足，而不是策略本身很差。短期没有真实人工回填时，可以先按下方模拟口径继续判断。")
            elif trade_count < 3:
                st.info("当前评估样本还比较少，建议把等级和最近模拟成交、模式对照一起看。")

            detail_cols = st.columns(5)
            detail_cols[0].metric("总收益率", f"{float(row['total_return']):.2%}")
            detail_cols[1].metric("最大回撤", f"{float(row['max_drawdown']):.2%}")
            detail_cols[2].metric("胜率", f"{float(row['win_rate']):.2%}")
            detail_cols[3].metric("盈亏比", f"{float(row['pnl_ratio']):.2f}")
            detail_cols[4].metric("利润因子", f"{float(row['profit_factor']):.2f}")
            render_value("每笔期望收益", float(row["expectancy"]))

            basis_cols = st.columns(4)
            basis_cols[0].metric("归因成交样本", f"{trade_count} 笔")
            basis_cols[1].metric("模拟成交闭环", len(actual_orders))
            basis_cols[2].metric("人工回填", len(manual_df))
            basis_cols[3].metric("阶段拦截", int(runtime_metrics.get("blocked_trigger_count") or 0))

            eval_display_df = evaluations_df.copy()
            eval_display_df["评级显示"] = eval_display_df.apply(_display_grade, axis=1)
            eval_display_df["样本说明"] = eval_display_df["total_trades"].map(_sample_note)
            st.dataframe(
                eval_display_df[
                    ["period_type", "strategy_name", "score_total", "评级显示", "样本说明", "status", "total_return", "max_drawdown", "win_rate", "total_trades"]
                ],
                use_container_width=True,
                hide_index=True,
            )

            if not comparison_display_df.empty:
                st.markdown("**模拟口径对照（不依赖人工回填）**")
                st.caption("优先使用模拟成交闭环；若某模式当前暂无闭环成交，再退回信号 5 日代理收益做方向性判断。")
                best_mode = comparison_display_df.sort_values(["样本数", "score_total"], ascending=[False, False]).head(1)
                if not best_mode.empty:
                    best_row = best_mode.iloc[0]
                    st.info(f"当前更值得优先观察：{best_row['显示模式']}，样本来源为 {best_row['样本来源']}，样本数 {int(best_row['样本数'])}。")
                st.dataframe(
                    comparison_display_df[
                        ["显示模式", "样本来源", "样本数", "score_total", "total_return", "max_drawdown", "win_rate", "profit_factor"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

            st.markdown("**入场策略横向比较**")
            strategy_compare = _latest_by_strategy(evaluations_df, period_type="daily")
            if not strategy_compare.empty:
                strategy_compare = strategy_compare.copy()
                strategy_compare["显示名称"] = strategy_compare["strategy_name"].astype(str).map(_display_strategy_name)
                strategy_compare["评级显示"] = strategy_compare.apply(_display_grade, axis=1)
                strategy_compare["样本说明"] = strategy_compare["total_trades"].map(_sample_note)
                bar_df = strategy_compare.set_index("显示名称")[["score_total", "win_rate", "profit_factor", "expectancy"]]
                st.bar_chart(bar_df, use_container_width=True)
                st.dataframe(
                    strategy_compare[
                        ["显示名称", "score_total", "评级显示", "样本说明", "total_return", "max_drawdown", "win_rate", "pnl_ratio", "profit_factor", "expectancy", "total_trades"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("暂无入场策略评估记录。")

            st.markdown("**卖出策略评分**")
            exit_compare = _latest_by_strategy(evaluations_df, period_type="daily", prefix="exit::")
            if not exit_compare.empty:
                exit_compare = exit_compare.copy()
                exit_compare["显示名称"] = exit_compare["strategy_name"].astype(str).map(_display_strategy_name)
                exit_compare["评级显示"] = exit_compare.apply(_display_grade, axis=1)
                exit_compare["样本说明"] = exit_compare["total_trades"].map(_sample_note)
                exit_bar_df = exit_compare.set_index("显示名称")[["score_total", "win_rate", "profit_factor", "expectancy"]]
                st.bar_chart(exit_bar_df, use_container_width=True)
                st.dataframe(
                    exit_compare[
                        ["显示名称", "score_total", "评级显示", "样本说明", "total_return", "max_drawdown", "win_rate", "pnl_ratio", "profit_factor", "expectancy", "total_trades"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("暂无卖出策略评分记录。当前会优先从模拟成交和模式对照继续判断，不强依赖人工回填。")

    if "策略表现分析" in tab_map:
        with tab_map["策略表现分析"]:
            st.subheader("策略表现分析")
            if performance_summary:
                perf_df = pd.DataFrame([{"strategy_name": name, **payload} for name, payload in performance_summary.items()])
                st.dataframe(perf_df, use_container_width=True, hide_index=True)
            else:
                st.info("暂无策略表现汇总。")
            if not evaluations_df.empty:
                latest_daily = evaluations_df[evaluations_df["period_type"] == "daily"].copy()
                latest_daily = latest_daily[~latest_daily["strategy_name"].astype(str).str.startswith("exit::")]
                latest_daily = latest_daily[latest_daily["strategy_name"].astype(str) != "portfolio_actual"]
                if not latest_daily.empty:
                    latest_daily["ts_dt"] = pd.to_datetime(latest_daily["ts"], errors="coerce")
                    latest_daily = latest_daily.sort_values("ts_dt", ascending=False).drop_duplicates("strategy_name")
                    st.bar_chart(latest_daily.set_index("strategy_name")[["win_rate", "total_return", "score_total"]], use_container_width=True)

    if "决策归因分析" in tab_map:
        with tab_map["决策归因分析"]:
            st.subheader("决策归因分析")
            if attribution_df.empty:
                st.info("暂无决策归因快照。")
            else:
                attribution_cols = [
                    col
                    for col in [
                        "ts",
                        "symbol",
                        "name",
                        "action",
                        "setup_score",
                        "execution_score",
                        "ai_score",
                        "result_return",
                        "market_regime",
                        "style_profile",
                        "reason",
                    ]
                    if col in attribution_df.columns
                ]
                st.dataframe(attribution_df[attribution_cols], use_container_width=True, hide_index=True)

    if "权重变化历史" in tab_map:
        with tab_map["权重变化历史"]:
            st.subheader("权重变化历史")
            if adaptive_state:
                st.markdown("**当前自适应权重**")
                cols = st.columns(2)
                cols[0].metric("AI 加分倍率", f"{float(adaptive_state.get('ai_score_multiplier') or 1.0):.2f}")
                cols[1].metric("风险惩罚倍率", f"{float(adaptive_state.get('risk_penalty_multiplier') or 1.0):.2f}")
                adaptive_weights_df = pd.DataFrame([{"strategy_name": key, "weight": value} for key, value in (adaptive_state.get("strategy_weights") or {}).items()])
                if not adaptive_weights_df.empty:
                    st.dataframe(adaptive_weights_df, use_container_width=True, hide_index=True)
                review_feedback = dict(adaptive_state.get("ai_review_feedback") or {})
                if review_feedback:
                    st.markdown("**AI 终审反馈**")
                    feedback_cols = st.columns(4)
                    feedback_cols[0].metric("已评估终审", int(review_feedback.get("evaluated_count") or 0))
                    feedback_cols[1].metric("收盘正向", int(review_feedback.get("positive_close_count") or 0))
                    feedback_cols[2].metric("平均收盘改善", f"{float(review_feedback.get('avg_benefit_close') or 0.0):.2%}")
                    feedback_cols[3].metric("高价值场景", str(review_feedback.get("top_regime") or "-"))
                    role_stats = pd.DataFrame(
                        [
                            {
                                "作用类型": str((item or {}).get("label") or key),
                                "样本数": int((item or {}).get("count") or 0),
                                "收盘改善": float((item or {}).get("avg_benefit_close") or 0.0),
                                "次日改善": float((item or {}).get("avg_benefit_next_close") or 0.0),
                                "正向占比": float((item or {}).get("positive_rate") or 0.0),
                                "说明": str((item or {}).get("message") or ""),
                            }
                            for key, item in (review_feedback.get("role_stats") or {}).items()
                        ]
                    )
                    if not role_stats.empty:
                        st.dataframe(role_stats, use_container_width=True, hide_index=True)
                    suggestions = pd.DataFrame(list(review_feedback.get("suggestions") or []))
                    if not suggestions.empty:
                        st.markdown("**策略反馈建议**")
                        st.dataframe(suggestions, use_container_width=True, hide_index=True)
            if not adaptive_history_df.empty:
                history_df = adaptive_history_df.copy()
                st.dataframe(history_df, use_container_width=True, hide_index=True)
                pivot = history_df[history_df["category"] == "strategy_weight"].copy()
                if not pivot.empty:
                    pivot["ts_dt"] = pd.to_datetime(pivot["ts"], errors="coerce")
                    pivot = pivot.sort_values("ts_dt")
                    line_df = pivot.pivot_table(index="ts_dt", columns="key_name", values="new_value", aggfunc="last")
                    if not line_df.empty:
                        st.line_chart(line_df, use_container_width=True)
            else:
                st.info("暂无权重历史。")

    if "市场状态与风格" in tab_map:
        with tab_map["市场状态与风格"]:
            st.subheader("市场状态与风格")
            status_cols = st.columns(4)
            status_cols[0].metric("当前市场状态", str((regime or {}).get("regime") or "-"))
            status_cols[1].metric("风险偏好", str((regime or {}).get("risk_bias") or "-"))
            status_cols[2].metric("AI 交易风格", str((style_profile or {}).get("style") or "-"))
            status_cols[3].metric("持有偏好", str((style_profile or {}).get("holding_preference") or "-"))
            if style_profile:
                st.caption(str((style_profile or {}).get("reason") or ""))
            if not style_history_df.empty:
                st.dataframe(style_history_df, use_container_width=True, hide_index=True)

    if "错误决策分析" in tab_map:
        with tab_map["错误决策分析"]:
            st.subheader("错误决策分析")
            if bad_decisions.empty:
                st.info("暂无可分析的亏损决策。")
            else:
                st.dataframe(bad_decisions, use_container_width=True, hide_index=True)

    if "周期统计" in tab_map:
        with tab_map["周期统计"]:
            st.subheader("周期统计面板")
            period_options = {
                "今日": "daily",
                "本周": "weekly",
                "本月": "monthly",
                f"最近 {settings.evaluation.rolling_trade_windows[0]} 笔": f"rolling_trade_{settings.evaluation.rolling_trade_windows[0]}",
                f"最近 {settings.evaluation.rolling_day_windows[0]} 日": f"rolling_day_{settings.evaluation.rolling_day_windows[0]}",
            }
            selected_label = st.selectbox("查看周期", list(period_options.keys()), key="period_label")
            filtered = evaluations_df[evaluations_df["period_type"] == period_options[selected_label]] if not evaluations_df.empty else evaluations_df
            if filtered.empty:
                st.info("当前周期暂无统计记录。")
            else:
                st.dataframe(filtered, use_container_width=True, hide_index=True)

    if "模式对照" in tab_map:
        with tab_map["模式对照"]:
            st.subheader("模式对照")
            if isinstance(live_compare, dict) and live_compare.get("rows"):
                st.markdown("**实时决策差异**")
                st.write(str(live_compare.get("summary") or ""))
                live_compare_df = attach_symbol_name(pd.DataFrame(live_compare.get("rows") or []))
                cols = [col for col in ["symbol", "name", "legacy_action", "legacy_confidence", "new_action", "new_confidence", "different"] if col in live_compare_df.columns]
                st.dataframe(live_compare_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("当前轮次暂无实时新旧模式差异。切到 compare_mode 后会在这里显示。")

            st.markdown("**历史对照实验面板**")
            if comparison_display_df.empty:
                st.info("暂无对照实验记录。")
            else:
                st.bar_chart(
                    comparison_display_df.set_index("显示模式")[["score_total", "total_return", "profit_factor", "win_rate"]],
                    use_container_width=True,
                )
                cols = st.columns(min(4, len(comparison_display_df)))
                for idx, (_, row) in enumerate(comparison_display_df.head(4).iterrows()):
                    with cols[idx % len(cols)]:
                        st.markdown(f"**{row['显示模式']}**")
                        st.metric("总分", f"{float(row['score_total']):.2f}")
                        st.write(f"样本：{row['样本来源']} / {int(row['样本数'])}")
                        st.write(f"收益：{float(row['total_return']):.2%}")
                        st.write(f"回撤：{float(row['max_drawdown']):.2%}")
                        st.write(f"胜率：{float(row['win_rate']):.2%}")
                st.dataframe(
                    comparison_display_df[
                        ["显示模式", "样本来源", "样本数", "score_total", "total_return", "max_drawdown", "win_rate", "profit_factor", "expectancy"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    if "成交流水" in tab_map:
        with tab_map["成交流水"]:
            st.subheader("成交流水")
            if not orders_df.empty:
                order_cols = [col for col in ["ts", "symbol", "name", "side", "price", "qty", "fee", "tax", "slippage", "status", "intent_only", "phase", "strategy_name", "mode_name"] if col in orders_df.columns]
                st.dataframe(orders_df[order_cols], use_container_width=True, hide_index=True)
            else:
                st.info("暂无成交记录。")
            if not manual_df.empty:
                st.markdown("**人工实盘回填记录**")
                cols = [col for col in ["ts", "symbol", "name", "executed", "actual_price", "actual_qty", "reason", "note"] if col in manual_df.columns]
                st.dataframe(manual_df[cols], use_container_width=True, hide_index=True)

    with tab_map["日志筛选"]:
        st.subheader("日志筛选")
        filter_cols = st.columns(4)
        with filter_cols[0]:
            level = st.selectbox("级别", ["全部"] + sorted(logs_df["level"].astype(str).unique().tolist()) if not logs_df.empty and "level" in logs_df.columns else ["全部"])
        with filter_cols[1]:
            module = st.selectbox("模块", ["全部"] + sorted(logs_df["module"].astype(str).unique().tolist()) if not logs_df.empty and "module" in logs_df.columns else ["全部"])
        with filter_cols[2]:
            keyword = st.text_input("关键词")
        with filter_cols[3]:
            time_text = st.text_input("时间片段", placeholder="例如 2026-03-27")
        filtered_logs = logs_df.copy()
        if not filtered_logs.empty:
            if level != "全部":
                filtered_logs = filtered_logs[filtered_logs["level"].astype(str) == level]
            if module != "全部":
                filtered_logs = filtered_logs[filtered_logs["module"].astype(str) == module]
            if keyword:
                filtered_logs = filtered_logs[filtered_logs["message"].astype(str).str.contains(keyword, case=False, na=False)]
            if time_text:
                filtered_logs = filtered_logs[filtered_logs["ts"].astype(str).str.contains(time_text, case=False, na=False)]
        st.dataframe(filtered_logs, use_container_width=True, hide_index=True)

    with tab_map["人工回填"]:
        st.subheader("人工实盘成交回填")
        st.caption("这块现在改成可选项了。短期没有真实人工回填也没关系，8610 会继续优先使用模拟成交闭环和信号代理口径来评估。")
        info_cols = st.columns(3)
        info_cols[0].metric("模拟成交闭环", len(actual_orders))
        info_cols[1].metric("人工回填记录", len(manual_df))
        info_cols[2].metric("待回填信号", len(final_signals_df))

        if not manual_df.empty:
            st.markdown("**最近人工回填记录**")
            cols = [col for col in ["ts", "symbol", "name", "executed", "actual_price", "actual_qty", "reason", "note"] if col in manual_df.columns]
            st.dataframe(manual_df[cols], use_container_width=True, hide_index=True)

        with st.expander("需要对齐真实人工执行时，再展开填写", expanded=False):
            if final_signals_df.empty:
                st.info("当前暂无待回填信号。先不用处理也可以。")
            else:
                options = {
                    f"{int(row['id'])} | {row['symbol']} {row.get('name', row['symbol'])} | {row['action']} | {row.get('strategy_name', '')}": int(row["id"])
                    for _, row in final_signals_df.head(30).iterrows()
                }
                selected_label = st.selectbox("选择信号", list(options.keys()))
                executed = st.toggle("是否执行实盘", value=True)
                form_cols = st.columns(2)
                with form_cols[0]:
                    actual_price = st.number_input("实际成交价", min_value=0.0, step=0.01, value=0.0)
                with form_cols[1]:
                    actual_qty = st.number_input("实际成交数量", min_value=0, step=100, value=0)
                reason = st.text_input("未执行原因/说明")
                note = st.text_area("备注")
                if st.button("写入人工回填", type="primary", use_container_width=True):
                    chosen_id = options[selected_label]
                    chosen_row = final_signals_df[final_signals_df["id"] == chosen_id].iloc[0]
                    conn = connect_db(settings, account_id=selected_account_id)
                    try:
                        manual_execution_service.record_execution(
                            conn,
                            signal_id=chosen_id,
                            symbol=str(chosen_row["symbol"]),
                            executed=executed,
                            actual_price=float(actual_price) if executed and actual_price > 0 else None,
                            actual_qty=int(actual_qty) if executed and actual_qty > 0 else None,
                            reason=reason,
                            note=note,
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    st.cache_data.clear()
                    st.success("人工实盘回填已写入。")
                    st.rerun()


render_dashboard()
