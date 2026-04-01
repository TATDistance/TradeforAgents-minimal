from __future__ import annotations

import json
from datetime import datetime

from app.db import connect_db, initialize_db, seed_account, write_account_snapshot, write_order
from app.evaluation_service import EvaluationService
from app.models import AccountSnapshot, OrderRecord
from app.settings import load_settings


def test_evaluation_service_collects_runtime_event_metrics(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    try:
        conn.execute(
            "INSERT INTO system_logs (ts, level, module, message) VALUES (?, ?, ?, ?)",
            (
                "2026-04-01T09:35:00",
                "INFO",
                "trigger",
                json.dumps({"symbol": "300750", "reasons": ["PRICE_UPDATED"]}, ensure_ascii=False),
            ),
        )
        conn.execute(
            "INSERT INTO system_logs (ts, level, module, message) VALUES (?, ?, ?, ?)",
            (
                "2026-04-01T09:35:01",
                "INFO",
                "decision_engine",
                json.dumps(
                    {
                        "symbol": "300750",
                        "action": "BUY",
                        "setup_score": 0.61,
                        "execution_score": 0.58,
                        "ai_score": 0.14,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        write_order(
            conn,
            OrderRecord(
                symbol="300750",
                side="BUY",
                price=410.0,
                qty=100,
                fee=5.0,
                status="FILLED",
                ts=datetime(2026, 4, 1, 9, 36, 0),
                strategy_name="ai_decision_engine",
                mode_name="ai_decision_engine_mode",
                phase="CONTINUOUS_AUCTION_AM",
            ),
        )
        write_account_snapshot(
            conn,
            AccountSnapshot(
                ts=datetime(2026, 4, 1, 9, 30, 0),
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
                ts=datetime(2026, 4, 1, 15, 0, 0),
                cash=58995.0,
                equity=100300.0,
                market_value=41305.0,
                realized_pnl=0.0,
                unrealized_pnl=300.0,
                drawdown=0.0,
            ),
        )
        conn.commit()

        evaluation = EvaluationService(settings).compute_daily_metrics(conn, "2026-04-01")
    finally:
        conn.close()

    metadata = json.loads(evaluation.metadata_json or "{}")
    runtime = metadata.get("runtime_event_metrics") or {}
    assert runtime["trigger_count"] == 1
    assert runtime["decision_count"] == 1
    assert runtime["actual_fill_count"] == 1
    assert runtime["effective_trigger_rate"] == 1.0
    assert runtime["trigger_fill_rate"] == 1.0
