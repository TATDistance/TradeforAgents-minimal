from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd
import requests
import streamlit as st
import yaml

from app.db import connect_db, fetch_recent_equity_curve, fetch_recent_rows
from app.evaluation_service import EvaluationService
from app.manual_execution_service import ManualExecutionService
from app.settings import load_settings


st.set_page_config(page_title="AI Stock Sim 调试面板", layout="wide")
settings = load_settings(Path(__file__).resolve().parents[1])
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
def load_table(table: str, limit: int = 50) -> pd.DataFrame:
    conn = connect_db(settings)
    try:
        rows = fetch_recent_rows(conn, table, limit=limit)
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


@st.cache_data(ttl=5)
def load_equity_curve() -> pd.DataFrame:
    conn = connect_db(settings)
    try:
        rows = fetch_recent_equity_curve(conn, limit=200)
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


@st.cache_data(ttl=5)
def load_live_state() -> Dict[str, object]:
    path = settings.live_state_path
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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

st.title("AI 股票模拟交易调试面板")
st.caption("这里保留特征、上下文、风控、日志和模式对照；默认产品入口请回到 8600 的 AI 首页。")

toolbar_left, toolbar_mid, toolbar_right = st.columns([3, 1.3, 1.2])
with toolbar_left:
    st.write(f"数据库：`{settings.db_path}`")
with toolbar_mid:
    st.session_state["auto_refresh"] = st.toggle("局部自动刷新", value=st.session_state["auto_refresh"])
with toolbar_right:
    if st.button("立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.container(border=True):
    st.markdown("**模拟时段设置**")
    setting_cols = st.columns([1.4, 1.0, 1.2])
    with setting_cols[0]:
        st.toggle(
            "允许盘后保留准备动作",
            key="allow_post_close_execution",
            help="打开后，收盘后仍会保留 PREPARE_BUY / PREPARE_REDUCE 这类次日准备动作；关闭时更偏保守，只保留观察建议。",
        )
    with setting_cols[1]:
        current_label = "盘后准备动作：开启" if st.session_state["allow_post_close_execution"] else "盘后仅观察（推荐）"
        render_status_badge(current_label, "ai" if st.session_state["allow_post_close_execution"] else "warn")
    with setting_cols[2]:
        if st.button("保存模拟时段设置", use_container_width=True):
            save_post_close_execution_flag(bool(st.session_state["allow_post_close_execution"]))
            st.success("设置已保存。重启 8600 中的实时引擎后生效。")
    st.caption("这个设置会写回 config/settings.yaml。无论开关如何，盘后都不会新增真实模拟成交。")

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
    signals_df = attach_symbol_name(load_table("signals", limit=50))
    ai_df = attach_symbol_name(load_table("ai_decisions", limit=50))
    final_signals_df = attach_symbol_name(load_table("final_signals", limit=50))
    positions_df = attach_symbol_name(load_table("positions", limit=30))
    orders_df = attach_symbol_name(load_table("orders", limit=80))
    logs_df = attach_symbol_name(load_table("system_logs", limit=200))
    equity_df = load_equity_curve()
    account_df = load_table("account_snapshots", limit=1)
    evaluations_df = load_table("strategy_evaluations", limit=300)
    comparisons_df = load_table("mode_comparisons", limit=20)
    manual_df = attach_symbol_name(load_table("manual_execution_logs", limit=50))
    live_state = load_live_state()

    st.caption(f"上次数据刷新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if evaluations_df.empty:
        conn = connect_db(settings)
        try:
            evaluation_service.persist_evaluations(conn, reference_date=datetime.now().date().isoformat())
            conn.commit()
        finally:
            conn.close()
        st.cache_data.clear()
        evaluations_df = load_table("strategy_evaluations", limit=80)
        comparisons_df = load_table("mode_comparisons", limit=20)

    current_mode = str((live_state or {}).get("decision_mode") or settings.decision_engine.mode)
    mode_label = MODE_LABELS.get(current_mode, current_mode)
    trading_calendar = live_state.get("trading_calendar") if isinstance(live_state, dict) else {}
    execution_gate = live_state.get("execution_gate") if isinstance(live_state, dict) else {}
    with st.container(border=True):
        st.markdown("**当前运行模式**")
        summary_cols = st.columns(5)
        summary_cols[0].metric("决策模式", mode_label)
        summary_cols[1].metric("当前阶段", str((live_state or {}).get("phase", "-")))
        summary_cols[2].metric("AI 决策标的数", len((live_state or {}).get("ai_decision_engine") or {}))
        summary_cols[3].metric("计划动作数", len((live_state or {}).get("final_actions") or []))
        summary_cols[4].metric("可成交", "是" if bool((execution_gate or {}).get("can_execute_fill")) else "否")
        if isinstance(trading_calendar, dict) and trading_calendar:
            st.caption(
                f"交易日：{'是' if bool(trading_calendar.get('is_trading_day')) else '否'} | "
                f"下一交易日：{trading_calendar.get('next_trading_day') or '-'} | "
                f"最近交易日：{trading_calendar.get('previous_trading_day') or '-'}"
            )
        with st.expander("查看当前版本 AI 单次轮询流程图"):
            st.code(FLOWCHART_TEXT, language="text")

    top_tabs = st.tabs(
        [
            "当前模式与总览",
            "交易日历状态",
            "当前交易阶段",
            "当前执行权限",
            "动作意图 vs 实际成交",
            "盘后模式",
            "市场状态机",
            "策略权重",
            "AI 决策输入",
            "AI 审核员",
            "AI 决策中心",
            "执行结果",
            "账户与持仓",
            "策略评估",
            "周期统计",
            "模式对照",
            "成交流水",
            "日志筛选",
            "人工回填",
        ]
    )

    with top_tabs[0]:
        st.subheader("当前模式与市场总览")
        st.write(f"当前实时主链运行在：**{mode_label}**")
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
            cols = [col for col in ["symbol", "name", "action", "confidence", "risk_mode", "final_score", "reason"] if col in quick_df.columns]
            st.dataframe(quick_df[cols], use_container_width=True, hide_index=True)

    with top_tabs[1]:
        st.subheader("交易日历状态")
        if isinstance(trading_calendar, dict) and trading_calendar:
            cols = st.columns(3)
            cols[0].metric("今天是否交易日", "是" if bool(trading_calendar.get("is_trading_day")) else "否")
            cols[1].metric("下一交易日", str(trading_calendar.get("next_trading_day") or "-"))
            cols[2].metric("最近交易日", str(trading_calendar.get("previous_trading_day") or "-"))
        else:
            st.info("暂无交易日历状态。")

    with top_tabs[2]:
        st.subheader("当前交易阶段")
        phase_name = str((live_state or {}).get("phase", "-"))
        phase_color = "profit" if "CONTINUOUS_AUCTION" in phase_name else "warn" if phase_name in {"PRE_OPEN", "OPEN_CALL_AUCTION", "MIDDAY_BREAK"} else "reject"
        render_status_badge(phase_name, phase_color)
        if isinstance(execution_gate, dict) and execution_gate:
            st.write(str(execution_gate.get("reason") or ""))
        else:
            st.info("暂无阶段状态。")

    with top_tabs[3]:
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

    with top_tabs[4]:
        st.subheader("动作意图 vs 实际成交")
        planned_rows = live_state.get("final_actions") if isinstance(live_state, dict) else []
        planned_df = attach_symbol_name(pd.DataFrame(planned_rows)) if planned_rows else pd.DataFrame()
        if not planned_df.empty:
            intent_df = planned_df[planned_df["intent_only"].astype(bool)] if "intent_only" in planned_df.columns else pd.DataFrame()
            exec_df = planned_df[planned_df["executable_now"].astype(bool)] if "executable_now" in planned_df.columns else pd.DataFrame()
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
        if not orders_df.empty and "intent_only" in orders_df.columns:
            actual_orders = orders_df[orders_df["intent_only"] == 0]
            intent_orders = orders_df[orders_df["intent_only"] == 1]
        elif not orders_df.empty and "status" in orders_df.columns:
            actual_orders = orders_df[orders_df["status"].astype(str).str.contains("FILLED", na=False)]
            intent_orders = orders_df[orders_df["status"].astype(str) == "INTENT_ONLY"]
        else:
            actual_orders = pd.DataFrame()
            intent_orders = pd.DataFrame()
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

    with top_tabs[5]:
        st.subheader("盘后模式")
        post_close_intents = orders_df[orders_df["phase"].astype(str) == "POST_CLOSE"] if not orders_df.empty and "phase" in orders_df.columns else pd.DataFrame()
        if not post_close_intents.empty:
            st.markdown("**明日观察与准备动作**")
            cols = [col for col in ["ts", "symbol", "name", "side", "qty", "note"] if col in post_close_intents.columns]
            st.dataframe(post_close_intents[cols], use_container_width=True, hide_index=True)
        else:
            st.info("当前暂无盘后准备动作。")
        risk_df = pd.DataFrame(live_state.get("risk_results") or []) if isinstance(live_state, dict) else pd.DataFrame()
        if not risk_df.empty and "phase_blocked" in risk_df.columns:
            blocked_df = attach_symbol_name(risk_df[risk_df["phase_blocked"].astype(bool)].copy())
            st.markdown("**今日因阶段权限被拦截的动作**")
            if not blocked_df.empty:
                cols = [col for col in ["symbol", "name", "action", "phase", "reason"] if col in blocked_df.columns]
                st.dataframe(blocked_df[cols], use_container_width=True, hide_index=True)
            else:
                st.info("暂无阶段拦截动作。")

    with top_tabs[6]:
        st.subheader("市场状态机")
        regime = live_state.get("market_regime") if isinstance(live_state, dict) else {}
        if isinstance(regime, dict) and regime:
            metric_cols = st.columns(4)
            metric_cols[0].metric("当前 Regime", str(regime.get("regime", "-")))
            metric_cols[1].metric("置信度", f"{float(regime.get('confidence', 0.0) or 0.0):.2%}")
            metric_cols[2].metric("风险偏好", str(regime.get("risk_bias", "-")))
            metric_cols[3].metric("市场广度", f"{float(regime.get('breadth', 0.0) or 0.0):.2%}")
            st.write(str(regime.get("reason", "")))
        else:
            st.info("暂无市场状态缓存。")

    with top_tabs[7]:
        st.subheader("策略权重")
        weights = live_state.get("strategy_weights") if isinstance(live_state, dict) else {}
        if isinstance(weights, dict) and weights:
            weights_df = pd.DataFrame(
                [{"strategy": key, "weight": value} for key, value in weights.items()]
            ).sort_values("weight", ascending=False)
            st.bar_chart(weights_df.set_index("strategy"), use_container_width=True)
            st.dataframe(weights_df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无策略权重数据。")

    with top_tabs[8]:
        st.subheader("AI 决策输入摘要")
        context_map = live_state.get("decision_contexts") if isinstance(live_state, dict) else {}
        feature_map = live_state.get("feature_fusions") if isinstance(live_state, dict) else {}
        if isinstance(context_map, dict) and context_map:
            rows = []
            for symbol, payload in context_map.items():
                if not isinstance(payload, dict):
                    continue
                snapshot = dict(payload.get("snapshot") or {})
                portfolio_state = dict(payload.get("portfolio_state") or {})
                position_state = dict(payload.get("position_state") or {})
                market_regime = dict(payload.get("market_regime") or {})
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
                        "market_regime": market_regime.get("regime"),
                        "feature_score": fusion.get("feature_score"),
                        "final_score": fusion.get("final_score"),
                    }
                )
            context_df = attach_symbol_name(pd.DataFrame(rows))
            cols = [col for col in ["symbol", "name", "latest_price", "pct_change", "amount", "cash_pct", "drawdown", "has_position", "hold_days", "market_regime", "feature_score", "final_score"] if col in context_df.columns]
            st.dataframe(context_df[cols], use_container_width=True, hide_index=True)
        else:
            st.info("本轮暂无 AI 决策输入摘要。")

    with top_tabs[9]:
        st.subheader("AI 审核员")
        reviewer = live_state.get("ai_reviewer") if isinstance(live_state, dict) else []
        reviewer_df = attach_symbol_name(pd.DataFrame(reviewer)) if reviewer else pd.DataFrame()
        if not reviewer_df.empty:
            cols = [col for col in ["symbol", "name", "ai_action", "approved", "confidence", "risk_score", "reason", "context_summary"] if col in reviewer_df.columns]
            st.dataframe(reviewer_df[cols], use_container_width=True, hide_index=True)
        else:
            st.info("本轮暂无 AI 审核结果。")

    with top_tabs[10]:
        st.subheader("AI 决策中心")
        engine_payload = live_state.get("ai_decision_engine") if isinstance(live_state, dict) else {}
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

        st.markdown("**第三阶段组合管理器参考视图**")
        manager = live_state.get("ai_portfolio_manager") if isinstance(live_state, dict) else {}
        if isinstance(manager, dict) and manager:
            header_cols = st.columns(3)
            header_cols[0].metric("当前风险模式", str(manager.get("risk_mode", "-")))
            header_cols[1].metric("建议动作数", len(manager.get("actions") or []))
            header_cols[2].metric("当前阶段", str(live_state.get("phase", "-")))
            st.write(str(manager.get("portfolio_view", "")))
            actions_df = attach_symbol_name(pd.DataFrame(manager.get("actions") or []))
            if not actions_df.empty:
                cols = [col for col in ["symbol", "name", "action", "position_pct", "reduce_pct", "priority", "reason"] if col in actions_df.columns]
                st.dataframe(actions_df[cols], use_container_width=True, hide_index=True)
        else:
            st.info("暂无组合管理建议。")

    with top_tabs[11]:
        st.subheader("执行结果")
        final_actions = live_state.get("final_actions") if isinstance(live_state, dict) else []
        risks = live_state.get("risk_results") if isinstance(live_state, dict) else []
        actions_df = attach_symbol_name(pd.DataFrame(final_actions)) if final_actions else pd.DataFrame()
        risk_df = attach_symbol_name(pd.DataFrame(risks)) if risks else pd.DataFrame()
        if not actions_df.empty:
            cols = [col for col in ["symbol", "name", "action", "planned_qty", "planned_price", "priority", "mode_name", "reason"] if col in actions_df.columns]
            st.dataframe(actions_df[cols], use_container_width=True, hide_index=True)
        else:
            st.info("本轮暂无最终动作计划。")
        if not risk_df.empty:
            st.markdown("**风控结果**")
            cols = [col for col in ["symbol", "name", "action", "mode_name", "final_action", "allowed", "adjusted_qty", "risk_state", "reason"] if col in risk_df.columns]
            st.dataframe(risk_df[cols], use_container_width=True, hide_index=True)

    with top_tabs[12]:
        st.subheader("账户与持仓")
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
            st.line_chart(equity_df.set_index("ts")[["equity", "drawdown"]], use_container_width=True)
        else:
            st.info("暂无权益曲线数据。")

    with top_tabs[13]:
        st.subheader("策略评估面板")
        if evaluations_df.empty:
            st.info("暂无策略评估记录。")
        else:
            latest_daily = evaluations_df[evaluations_df["period_type"] == "daily"].head(1)
            row = latest_daily.iloc[0] if not latest_daily.empty else evaluations_df.iloc[0]
            score_cols = st.columns(4)
            score_cols[0].metric("当前策略", str(row["strategy_name"]))
            score_cols[1].metric("总分", f"{float(row['score_total']):.2f}")
            score_cols[2].metric("评级", str(row["grade"]))
            score_cols[3].metric("状态", str(row["status"]))
            detail_cols = st.columns(5)
            detail_cols[0].metric("总收益率", f"{float(row['total_return']):.2%}")
            detail_cols[1].metric("最大回撤", f"{float(row['max_drawdown']):.2%}")
            detail_cols[2].metric("胜率", f"{float(row['win_rate']):.2%}")
            detail_cols[3].metric("盈亏比", f"{float(row['pnl_ratio']):.2f}")
            detail_cols[4].metric("利润因子", f"{float(row['profit_factor']):.2f}")
            render_value("每笔期望收益", float(row["expectancy"]))
            st.dataframe(evaluations_df, use_container_width=True, hide_index=True)

            st.markdown("**入场策略横向比较**")
            strategy_compare = _latest_by_strategy(evaluations_df, period_type="daily")
            if not strategy_compare.empty:
                strategy_compare = strategy_compare.copy()
                strategy_compare["显示名称"] = strategy_compare["strategy_name"].astype(str).map(_display_strategy_name)
                bar_df = strategy_compare.set_index("显示名称")[["score_total", "win_rate", "profit_factor", "expectancy"]]
                st.bar_chart(bar_df, use_container_width=True)
                st.dataframe(
                    strategy_compare[
                        ["显示名称", "score_total", "grade", "total_return", "max_drawdown", "win_rate", "pnl_ratio", "profit_factor", "expectancy"]
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
                exit_bar_df = exit_compare.set_index("显示名称")[["score_total", "win_rate", "profit_factor", "expectancy"]]
                st.bar_chart(exit_bar_df, use_container_width=True)
                st.dataframe(
                    exit_compare[
                        ["显示名称", "score_total", "grade", "total_return", "max_drawdown", "win_rate", "pnl_ratio", "profit_factor", "expectancy", "total_trades"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("暂无卖出策略评分记录。需要先有真实平仓成交，才能判断哪种退出更好。")

    with top_tabs[14]:
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

    with top_tabs[15]:
        st.subheader("模式对照")
        live_compare = live_state.get("decision_compare") if isinstance(live_state, dict) else {}
        if isinstance(live_compare, dict) and live_compare.get("rows"):
            st.markdown("**实时决策差异**")
            st.write(str(live_compare.get("summary") or ""))
            live_compare_df = attach_symbol_name(pd.DataFrame(live_compare.get("rows") or []))
            cols = [col for col in ["symbol", "name", "legacy_action", "legacy_confidence", "new_action", "new_confidence", "different"] if col in live_compare_df.columns]
            st.dataframe(live_compare_df[cols], use_container_width=True, hide_index=True)
        else:
            st.info("当前轮次暂无实时新旧模式差异。切到 compare_mode 后会在这里显示。")

        st.markdown("**历史对照实验面板**")
        if comparisons_df.empty:
            st.info("暂无对照实验记录。")
        else:
            chart_df = comparisons_df.copy()
            chart_df["显示模式"] = chart_df["mode_name"].map(
                {
                    "legacy_review_mode": "旧模式：策略主导 + AI 审批",
                    "ai_decision_engine_mode": "新模式：AI 决策引擎",
                    "strategy_only": "纯策略",
                    "strategy_plus_ai": "策略+AI",
                    "strategy_plus_risk": "策略+风控",
                    "strategy_plus_ai_plus_risk": "策略+AI+风控",
                }
            ).fillna(chart_df["mode_name"])
            st.bar_chart(
                chart_df.set_index("显示模式")[["score_total", "total_return", "profit_factor", "win_rate"]],
                use_container_width=True,
            )
            cols = st.columns(4)
            mode_names = {
                "legacy_review_mode": "旧模式：策略主导 + AI 审批",
                "ai_decision_engine_mode": "新模式：AI 决策引擎",
                "strategy_only": "纯策略",
                "strategy_plus_ai": "策略+AI",
                "strategy_plus_risk": "策略+风控",
                "strategy_plus_ai_plus_risk": "策略+AI+风控",
            }
            for idx, (_, row) in enumerate(comparisons_df.head(4).iterrows()):
                with cols[idx % 4]:
                    st.markdown(f"**{mode_names.get(str(row['mode_name']), str(row['mode_name']))}**")
                    st.metric("总分", f"{float(row['score_total']):.2f}")
                    st.write(f"收益：{float(row['total_return']):.2%}")
                    st.write(f"回撤：{float(row['max_drawdown']):.2%}")
                    st.write(f"胜率：{float(row['win_rate']):.2%}")
                    st.write(f"利润因子：{float(row['profit_factor']):.2f}")
            st.dataframe(comparisons_df, use_container_width=True, hide_index=True)

    with top_tabs[16]:
        st.subheader("成交流水")
        if not orders_df.empty:
            order_cols = [col for col in ["ts", "symbol", "name", "side", "price", "qty", "fee", "tax", "slippage", "status", "intent_only", "phase", "strategy_name", "mode_name"] if col in orders_df.columns]
            st.dataframe(orders_df[order_cols], use_container_width=True, hide_index=True)
        else:
            st.info("暂无成交记录。")
        if not manual_df.empty:
            st.markdown("**人工实盘回填记录**")
            st.dataframe(manual_df, use_container_width=True, hide_index=True)

    with top_tabs[17]:
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

    with top_tabs[18]:
        st.subheader("人工实盘成交回填")
        if final_signals_df.empty:
            st.info("暂无可回填的信号。")
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
                conn = connect_db(settings)
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
