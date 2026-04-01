from __future__ import annotations

import json
from pathlib import Path

from app.db import connect_db, initialize_db, write_order
from app.models import OrderRecord
from app.settings import load_settings
from dashboard.services.ui_timeline_service import get_recent_action_timeline


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ui_timeline_service_merges_orders_and_rejections(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    initialize_db(settings)
    conn = connect_db(settings)
    try:
        write_order(
            conn,
            OrderRecord(
                symbol="300750",
                side="BUY",
                price=100.0,
                qty=100,
                status="INTENT_ONLY",
                intent_only=True,
                phase="MIDDAY_BREAK",
                note="盘中先记录买入意图",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    settings.live_state_path.parent.mkdir(parents=True, exist_ok=True)
    settings.live_state_path.write_text(
        json.dumps(
            {
                "ts": "2026-04-01T11:31:00",
                "risk_results": [
                    {
                        "symbol": "600036",
                        "action": "BUY",
                        "allowed": False,
                        "phase": "MIDDAY_BREAK",
                        "reason": "午休阶段禁止成交",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = get_recent_action_timeline(settings=settings)

    assert any(item["status"] == "intent" for item in rows)
    assert any(item["status"] == "rejected" for item in rows)
