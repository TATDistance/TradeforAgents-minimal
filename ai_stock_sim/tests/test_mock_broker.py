from __future__ import annotations

from app.db import connect_db, initialize_db, seed_account
from app.mock_broker import MockBroker
from app.models import FinalSignal, RiskCheckResult
from app.settings import load_settings


def test_mock_broker_creates_order(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    broker = MockBroker(settings)
    signal = FinalSignal(
        symbol="600036",
        action="BUY",
        entry_price=40.0,
        stop_loss=38.0,
        take_profit=44.0,
        position_pct=0.1,
        confidence=0.8,
        source_strategies=["momentum", "breakout"],
        ai_approved=True,
    )
    risk = RiskCheckResult(allowed=True, adjusted_qty=200, adjusted_position_pct=0.08, risk_state="ALLOW")
    order = broker.execute_signal(conn, signal, risk, latest_price=40.0)
    assert order.qty > 0
    conn.close()
