from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd
import streamlit as st
import requests

from app.db import connect_db, fetch_recent_equity_curve, fetch_recent_rows
from app.settings import load_settings


st.set_page_config(page_title="AI Stock Sim 控制台", layout="wide")
settings = load_settings(Path(__file__).resolve().parents[1])
SYMBOL_NAME_CACHE: Dict[str, str] = {}


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

    reports_dir = settings.reports_dir
    auto_candidates_files = sorted(reports_dir.glob("auto_candidates_*.json"))
    if auto_candidates_files:
        latest_auto = auto_candidates_files[-1]
        try:
            payload = json.loads(latest_auto.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        selected = payload.get("selected") or []
        if isinstance(selected, list):
            for item in selected:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").strip()
                name = str(item.get("name") or "").strip()
                if symbol and name and symbol not in mapping:
                    mapping[symbol] = name
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
    symbol_values = enriched["symbol"].astype(str)
    missing_symbols = tuple(sorted({symbol for symbol in symbol_values if symbol not in mapping}))
    if missing_symbols:
        mapping = {**mapping, **fetch_eastmoney_symbol_names(missing_symbols)}
    name_values = symbol_values.map(lambda symbol: mapping.get(symbol, symbol))
    insert_at = int(enriched.columns.get_loc("symbol")) + 1
    enriched.insert(insert_at, "name", name_values)
    return enriched


if "auto_refresh" not in st.session_state:
    st.session_state["auto_refresh"] = False

st.title("AI 股票模拟交易控制台")
st.caption("东财实时行情 + 公开策略 + TradeforAgents AI 审批 + A 股模拟撮合")

toolbar_left, toolbar_mid, toolbar_right = st.columns([3, 1.2, 1.2])
with toolbar_left:
    st.write(f"数据库：`{settings.db_path}`")
with toolbar_mid:
    st.session_state["auto_refresh"] = st.toggle("局部自动刷新", value=st.session_state["auto_refresh"])
with toolbar_right:
    if st.button("立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if st.session_state["auto_refresh"]:
    st.caption(f"当前为局部自动刷新模式，每 {settings.dashboard_refresh_seconds} 秒更新数据，不整页跳动。")
else:
    st.caption("当前为手动刷新模式。页面不会自动跳动，适合长时间观看。")

run_every = f"{settings.dashboard_refresh_seconds}s" if st.session_state["auto_refresh"] else None


@st.fragment(run_every=run_every)
def render_dashboard() -> None:
    quotes_df = attach_symbol_name(load_table("signals", limit=30))
    ai_df = attach_symbol_name(load_table("ai_decisions", limit=30))
    positions_df = attach_symbol_name(load_table("positions", limit=30))
    orders_df = attach_symbol_name(load_table("orders", limit=50))
    logs_df = load_table("system_logs", limit=100)
    equity_df = load_equity_curve()
    account_df = load_table("account_snapshots", limit=1)

    st.caption(f"上次数据刷新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    st.subheader("1. 市场总览")
    st.dataframe(
        quotes_df[["ts", "symbol", "name", "strategy_name", "action", "score", "signal_price"]] if not quotes_df.empty else quotes_df,
        use_container_width=True,
    )

    st.subheader("2. AI 决策流")
    st.dataframe(
        ai_df[["ts", "symbol", "name", "ai_action", "confidence", "risk_score", "approved", "reason"]] if not ai_df.empty else ai_df,
        use_container_width=True,
    )

    st.subheader("3. 模拟盘账户")
    st.dataframe(account_df, use_container_width=True)

    st.subheader("4. 当前持仓")
    st.dataframe(positions_df, use_container_width=True)

    st.subheader("5. 成交流水")
    st.dataframe(orders_df, use_container_width=True)

    st.subheader("6. 收益曲线")
    if not equity_df.empty:
        st.line_chart(equity_df.set_index("ts")[["equity", "drawdown"]], use_container_width=True)
    else:
        st.info("暂无权益曲线数据。")

    st.subheader("7. 日志与告警")
    st.dataframe(logs_df, use_container_width=True)


render_dashboard()
