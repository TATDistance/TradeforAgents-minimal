from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd
import requests
import streamlit as st

from app.db import connect_db, fetch_recent_equity_curve, fetch_recent_rows
from app.evaluation_service import EvaluationService
from app.manual_execution_service import ManualExecutionService
from app.settings import load_settings


st.set_page_config(page_title="AI Stock Sim 控制台", layout="wide")
settings = load_settings(Path(__file__).resolve().parents[1])
evaluation_service = EvaluationService(settings)
manual_execution_service = ManualExecutionService(settings)
SYMBOL_NAME_CACHE: Dict[str, str] = {}


COLOR_MAP = {
    "profit": "#0f9d58",
    "loss": "#db4437",
    "warn": "#f29900",
    "reject": "#9aa0a6",
    "ai": "#2563eb",
}


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
        except Exception:
            continue
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


if "auto_refresh" not in st.session_state:
    st.session_state["auto_refresh"] = False

st.title("AI 股票模拟交易控制台")
st.caption("东财实时行情 + 公开策略 + TradeforAgents AI 审批 + A 股模拟撮合 + 周期评估")

toolbar_left, toolbar_mid, toolbar_right = st.columns([3, 1.3, 1.2])
with toolbar_left:
    st.write(f"数据库：`{settings.db_path}`")
with toolbar_mid:
    st.session_state["auto_refresh"] = st.toggle("局部自动刷新", value=st.session_state["auto_refresh"])
with toolbar_right:
    if st.button("立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

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
    evaluations_df = load_table("strategy_evaluations", limit=80)
    comparisons_df = load_table("mode_comparisons", limit=20)
    manual_df = attach_symbol_name(load_table("manual_execution_logs", limit=50))

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

    top_tabs = st.tabs(["市场总览", "AI 审批流", "账户与持仓", "策略评估", "周期统计", "对照实验", "成交流水", "日志筛选", "人工回填"])

    with top_tabs[0]:
        st.subheader("市场总览")
        overview_cols = [col for col in ["ts", "symbol", "name", "strategy_name", "action", "score", "signal_price"] if col in signals_df.columns]
        st.dataframe(signals_df[overview_cols] if not signals_df.empty else signals_df, use_container_width=True, hide_index=True)
        if not final_signals_df.empty:
            st.markdown("**最终候选信号**")
            cols = [col for col in ["ts", "symbol", "name", "action", "confidence", "strategy_name", "mode_name"] if col in final_signals_df.columns]
            st.dataframe(final_signals_df[cols], use_container_width=True, hide_index=True)

    with top_tabs[1]:
        st.subheader("AI 审批流")
        if not ai_df.empty:
            cols = [col for col in ["ts", "symbol", "name", "ai_action", "confidence", "risk_score", "approved", "reason", "context_summary"] if col in ai_df.columns]
            st.dataframe(ai_df[cols], use_container_width=True, hide_index=True)
            approved_count = int((ai_df["approved"] == 1).sum()) if "approved" in ai_df.columns else 0
            rejected_count = int((ai_df["approved"] == 0).sum()) if "approved" in ai_df.columns else 0
            st.markdown(
                f"AI 批准：{color_text(str(approved_count), 'ai')}，AI 拒绝：{color_text(str(rejected_count), 'reject')}",
                unsafe_allow_html=True,
            )
        else:
            st.info("暂无 AI 审批记录。")

    with top_tabs[2]:
        st.subheader("账户与持仓")
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

    with top_tabs[3]:
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

    with top_tabs[4]:
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

    with top_tabs[5]:
        st.subheader("对照实验面板")
        if comparisons_df.empty:
            st.info("暂无对照实验记录。")
        else:
            cols = st.columns(4)
            mode_names = {"strategy_only": "纯策略", "strategy_plus_ai": "策略+AI", "strategy_plus_risk": "策略+风控", "strategy_plus_ai_plus_risk": "策略+AI+风控"}
            for idx, (_, row) in enumerate(comparisons_df.head(4).iterrows()):
                with cols[idx % 4]:
                    st.markdown(f"**{mode_names.get(str(row['mode_name']), str(row['mode_name']))}**")
                    st.metric("总分", f"{float(row['score_total']):.2f}")
                    st.write(f"收益：{float(row['total_return']):.2%}")
                    st.write(f"回撤：{float(row['max_drawdown']):.2%}")
                    st.write(f"胜率：{float(row['win_rate']):.2%}")
                    st.write(f"利润因子：{float(row['profit_factor']):.2f}")
            st.dataframe(comparisons_df, use_container_width=True, hide_index=True)

    with top_tabs[6]:
        st.subheader("成交流水")
        if not orders_df.empty:
            order_cols = [col for col in ["ts", "symbol", "name", "side", "price", "qty", "fee", "tax", "slippage", "status", "strategy_name", "mode_name"] if col in orders_df.columns]
            st.dataframe(orders_df[order_cols], use_container_width=True, hide_index=True)
        else:
            st.info("暂无成交记录。")
        if not manual_df.empty:
            st.markdown("**人工实盘回填记录**")
            st.dataframe(manual_df, use_container_width=True, hide_index=True)

    with top_tabs[7]:
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

    with top_tabs[8]:
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
