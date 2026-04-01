from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

try:
    from ai_stock_sim.app.db import connect_db, fetch_rows_by_sql
    from ai_stock_sim.app.market_data_service import MarketDataService
    from ai_stock_sim.app.settings import Settings, load_settings
except ModuleNotFoundError:  # pragma: no cover - test/runtime import compatibility
    from app.db import connect_db, fetch_rows_by_sql
    from app.market_data_service import MarketDataService
    from app.settings import Settings, load_settings


def _charts_dir(settings: Settings) -> Path:
    return settings.cache_dir / "charts"


def _load_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_history_file(settings: Settings, symbol: str) -> Path | None:
    market_dir = settings.cache_dir / "market"
    candidates = sorted(market_dir.glob(f"history_frame_{symbol}_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def get_intraday_chart_data(symbol: str, settings: Settings | None = None) -> Dict[str, object]:
    resolved_settings = settings or load_settings()
    today = datetime.now().date().isoformat()
    chart_dir = _charts_dir(resolved_settings)
    chart_path = chart_dir / f"intraday_{symbol}_{today}.json"
    if not chart_path.exists():
        recent = sorted(chart_dir.glob(f"intraday_{symbol}_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        chart_path = recent[0] if recent else chart_path
    payload = _load_json(chart_path)
    points = payload.get("points") if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    if not points:
        quote_path = resolved_settings.cache_dir / "market" / f"quote_obj_{symbol}.json"
        quote_payload = _load_json(quote_path)
        if not quote_payload:
            try:
                quote_payload = MarketDataService(resolved_settings).fetch_realtime_quote(symbol).model_dump()
            except Exception:
                quote_payload = {}
        if quote_payload:
            points = [
                {
                    "ts": str(quote_payload.get("ts") or datetime.now().isoformat(timespec="seconds")),
                    "price": float(quote_payload.get("latest_price") or 0.0),
                    "pct_change": float(quote_payload.get("pct_change") or 0.0),
                    "amount": float(quote_payload.get("amount") or 0.0),
                }
            ]
    prices = [float(item.get("price") or 0.0) for item in points]
    return {
        "symbol": symbol,
        "points": points[-240:],
        "price_min": min(prices) if prices else 0.0,
        "price_max": max(prices) if prices else 0.0,
        "point_count": len(points),
    }


def get_kline_chart_data(symbol: str, settings: Settings | None = None) -> Dict[str, object]:
    resolved_settings = settings or load_settings()
    history_path = _latest_history_file(resolved_settings, symbol)
    rows: List[Dict[str, object]] = []
    if history_path:
        payload = _load_json(history_path)
        raw_rows = payload.get("rows") if isinstance(payload, dict) else []
        if isinstance(raw_rows, list):
            rows = raw_rows
    if not rows:
        try:
            frame = MarketDataService(resolved_settings).fetch_history_daily(symbol=symbol, limit=120)
            if not frame.empty:
                rows = frame.to_dict(orient="records")
        except Exception:
            rows = []
    return {
        "symbol": symbol,
        "rows": rows[-60:],
    }


def get_equity_curve_data(settings: Settings | None = None) -> Dict[str, object]:
    resolved_settings = settings or load_settings()
    conn = connect_db(resolved_settings)
    try:
        rows = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                "SELECT ts, equity, market_value, drawdown FROM account_snapshots ORDER BY id DESC LIMIT 240",
            )
        ]
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    rows.reverse()
    return {
        "points": rows,
        "point_count": len(rows),
    }
