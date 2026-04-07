from __future__ import annotations

import sys
import types
from datetime import timezone

zoneinfo_stub = types.ModuleType("zoneinfo")
zoneinfo_stub.ZoneInfo = lambda _name: timezone.utc
sys.modules.setdefault("zoneinfo", zoneinfo_stub)

from app.scheduler import TradingScheduler
from app.settings import load_settings


def test_scheduler_runs_realtime_review_for_positions_even_without_actions() -> None:
    settings = load_settings()
    settings.ai.realtime_position_review_enabled = True
    scheduler = TradingScheduler(settings)

    assert (
        scheduler._should_run_realtime_ai_review(
            [],
            {
                "positions_detail": [
                    {"symbol": "600036", "can_sell_qty": 500},
                ]
            },
        )
        is True
    )
    assert (
        scheduler._should_run_realtime_ai_review(
            [],
            {
                "positions_detail": [
                    {"symbol": "600036", "can_sell_qty": 0},
                ]
            },
        )
        is False
    )


def test_scheduler_normalizes_snapshot_pct_change_to_fraction() -> None:
    assert TradingScheduler._normalize_snapshot_pct_change(-0.2) == -0.002
    assert TradingScheduler._normalize_snapshot_pct_change(6.22) == 0.0622
