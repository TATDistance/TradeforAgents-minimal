from __future__ import annotations

import json
from datetime import datetime

from app.db import connect_db, fetch_rows_by_sql, initialize_db, seed_account
from app.decision_attribution_service import DecisionAttributionService
from app.settings import load_settings


def test_record_decision_snapshot_serializes_datetime_context(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    try:
        context = {
            "symbol": "300750",
            "strategy_features": {"momentum": {"score": 0.8}},
            "phase_state": {"ts": datetime(2026, 4, 2, 11, 58, 48)},
            "generated_at": datetime(2026, 4, 2, 11, 58, 48),
        }
        action = {
            "symbol": "300750",
            "action": "BUY",
            "execution_score": 0.62,
            "setup_score": 0.71,
            "ai_score": 0.18,
            "warnings": ["test"],
            "risk_mode": "NORMAL",
        }
        row_id = DecisionAttributionService(settings).record_decision_snapshot(
            conn,
            context,
            action,
            market_regime="TRENDING_UP",
            style_profile="trend_following",
        )
        conn.commit()

        rows = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                "SELECT context_json, feature_json, metadata_json FROM decision_snapshots WHERE id = ?",
                (row_id,),
            )
        ]
    finally:
        conn.close()

    assert row_id > 0
    assert rows
    context_json = json.loads(rows[0]["context_json"])
    assert context_json["generated_at"].startswith("2026-04-02 11:58:48")
    assert json.loads(rows[0]["feature_json"])["momentum"]["score"] == 0.8
    assert json.loads(rows[0]["metadata_json"])["risk_mode"] == "NORMAL"
