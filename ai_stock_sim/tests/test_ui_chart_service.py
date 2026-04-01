from __future__ import annotations

import json
from pathlib import Path

from app.db import connect_db, initialize_db, write_account_snapshot
from app.models import AccountSnapshot
from app.settings import load_settings
from dashboard.services.ui_chart_service import get_equity_curve_data, get_intraday_chart_data, get_kline_chart_data


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ui_chart_service_handles_cached_points_and_kline(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)

    intraday_path = settings.cache_dir / "charts" / "intraday_300750_2026-04-01.json"
    intraday_path.parent.mkdir(parents=True, exist_ok=True)
    intraday_path.write_text(
        json.dumps(
            {
                "symbol": "300750",
                "trade_date": "2026-04-01",
                "points": [
                    {"ts": "2026-04-01T09:31:00", "price": 100.0, "pct_change": 0.01, "amount": 1},
                    {"ts": "2026-04-01T09:32:00", "price": 101.0, "pct_change": 0.02, "amount": 2},
                ],
            }
        ),
        encoding="utf-8",
    )
    history_path = settings.cache_dir / "market" / "history_frame_300750_stock_20250605_20260401_150.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(
            {
                "rows": [
                    {"trade_date": "2026-03-31", "open": 100, "close": 101, "high": 102, "low": 99, "volume": 1, "amount": 1},
                    {"trade_date": "2026-04-01", "open": 101, "close": 103, "high": 104, "low": 100, "volume": 1, "amount": 1},
                ]
            }
        ),
        encoding="utf-8",
    )

    intraday = get_intraday_chart_data("300750", settings)
    kline = get_kline_chart_data("300750", settings)

    assert intraday["point_count"] == 2
    assert len(kline["rows"]) == 2


def test_ui_chart_service_reads_equity_curve(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    initialize_db(settings)
    conn = connect_db(settings)
    try:
        write_account_snapshot(
            conn,
            AccountSnapshot(
                cash=100000,
                equity=100000,
                market_value=0,
                realized_pnl=0,
                unrealized_pnl=0,
                drawdown=0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    equity = get_equity_curve_data(settings)
    assert equity["point_count"] >= 1
