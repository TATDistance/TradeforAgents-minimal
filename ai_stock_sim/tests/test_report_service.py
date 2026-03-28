from __future__ import annotations

from datetime import datetime

from app.db import connect_db, initialize_db, seed_account, write_account_snapshot, write_order
from app.models import AccountSnapshot, OrderRecord
from app.report_service import ReportService
from app.settings import load_settings


def test_report_service_exports_daily_bundle(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    try:
        write_order(
            conn,
            OrderRecord(
                symbol="600036",
                side="BUY",
                price=40.0,
                qty=100,
                fee=5.0,
                status="FILLED",
                ts=datetime(2026, 3, 27, 10, 0, 0),
                strategy_name="momentum+breakout",
            ),
        )
        write_order(
            conn,
            OrderRecord(
                symbol="600036",
                side="SELL",
                price=42.0,
                qty=100,
                fee=5.0,
                tax=2.1,
                status="FILLED",
                ts=datetime(2026, 3, 27, 14, 30, 0),
                strategy_name="momentum+breakout",
            ),
        )
        write_account_snapshot(
            conn,
            AccountSnapshot(
                ts=datetime(2026, 3, 27, 9, 30, 0),
                cash=100000.0,
                equity=100000.0,
                market_value=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                drawdown=0.0,
            ),
        )
        write_account_snapshot(
            conn,
            AccountSnapshot(
                ts=datetime(2026, 3, 27, 15, 0, 0),
                cash=100187.9,
                equity=100187.9,
                market_value=0.0,
                realized_pnl=187.9,
                unrealized_pnl=0.0,
                drawdown=0.0,
            ),
        )
        conn.commit()

        service = ReportService(settings)
        bundle = service.export_daily_report(conn, "2026-03-27")
    finally:
        conn.close()

    assert bundle["json"].exists()
    assert bundle["markdown"].exists()
    assert bundle["html"].exists()
