from __future__ import annotations

from app.db import connect_db, fetch_positions, initialize_db, seed_account
from app.mock_broker import MockBroker
from app.models import FinalSignal, RiskCheckResult
from app.settings import load_settings


def _buy_signal(symbol: str = "600036") -> FinalSignal:
    return FinalSignal(
        symbol=symbol,
        action="BUY",
        entry_price=40.0,
        stop_loss=38.0,
        take_profit=44.0,
        position_pct=0.1,
        confidence=0.8,
        source_strategies=["momentum", "breakout"],
        ai_approved=True,
    )


def test_mock_broker_creates_order(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    broker = MockBroker(settings)
    risk = RiskCheckResult(allowed=True, adjusted_qty=200, adjusted_position_pct=0.08, risk_state="ALLOW")

    order = broker.execute_signal(conn, _buy_signal(), risk, latest_price=40.0)

    assert order.qty > 0
    conn.close()


def test_release_t1_positions_keeps_same_day_buys_locked(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    broker = MockBroker(settings)
    risk = RiskCheckResult(allowed=True, adjusted_qty=100, adjusted_position_pct=0.04, risk_state="ALLOW")

    broker.execute_signal(conn, _buy_signal(symbol="002594"), risk, latest_price=40.0)
    broker.release_t1_positions(conn, trade_date="2026-04-07")

    positions = {str(row["symbol"]): row for row in fetch_positions(conn)}
    assert int(positions["002594"]["qty"]) == 100
    assert int(positions["002594"]["can_sell_qty"]) == 0
    conn.close()


def test_release_t1_positions_unlocks_prior_day_positions(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    broker = MockBroker(settings)
    risk = RiskCheckResult(allowed=True, adjusted_qty=100, adjusted_position_pct=0.04, risk_state="ALLOW")

    broker.execute_signal(conn, _buy_signal(symbol="000001"), risk, latest_price=40.0)
    conn.execute(
        """
        UPDATE orders
        SET ts = '2026-04-06T14:00:00'
        WHERE symbol = '000001' AND side = 'BUY'
        """
    )
    broker.release_t1_positions(conn, trade_date="2026-04-07")

    positions = {str(row["symbol"]): row for row in fetch_positions(conn)}
    assert int(positions["000001"]["can_sell_qty"]) == 100
    conn.close()
