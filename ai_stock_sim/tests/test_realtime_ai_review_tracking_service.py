from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.db import connect_db, initialize_db
from app.realtime_ai_review_tracking_service import RealtimeAIReviewTrackingService
from app.settings import load_settings


def test_tracking_service_classifies_review_roles() -> None:
    assert RealtimeAIReviewTrackingService.classify_review_role("action", "BUY", "HOLD") == "VETO"
    assert RealtimeAIReviewTrackingService.classify_review_role("action", "SELL", "REDUCE") == "SOFTEN"
    assert RealtimeAIReviewTrackingService.classify_review_role("holding", "HOLD", "SELL") == "TRIGGER"
    assert RealtimeAIReviewTrackingService.classify_review_role("action", "HOLD", "HOLD") == "NO_CHANGE"


def test_tracking_service_labels_positive_outcomes() -> None:
    service = RealtimeAIReviewTrackingService(load_settings())

    assert service._outcome_label("VETO", 0.01) == "避免亏损"
    assert service._outcome_label("SOFTEN", 0.01) == "避免卖飞"
    assert service._outcome_label("TRIGGER", 0.01) == "降低回撤"
    assert service._outcome_label("TRIGGER", -0.01) == "卖出偏早"


def test_tracking_service_reads_intraday_outcomes(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    chart_dir = settings.cache_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": "300750",
        "trade_date": "2026-04-07",
        "points": [
            {"ts": "2026-04-07T10:00:00", "price": 100.0},
            {"ts": "2026-04-07T11:05:00", "price": 96.0},
            {"ts": "2026-04-07T14:55:00", "price": 95.0},
        ],
    }
    next_payload = {
        "symbol": "300750",
        "trade_date": "2026-04-08",
        "points": [
            {"ts": "2026-04-08T14:55:00", "price": 94.0},
        ],
    }
    (chart_dir / "intraday_300750_2026-04-07.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (chart_dir / "intraday_300750_2026-04-08.json").write_text(json.dumps(next_payload, ensure_ascii=False), encoding="utf-8")

    service = RealtimeAIReviewTrackingService(settings)
    symbol_points = service._load_symbol_points("300750")

    one_hour_price = service._price_at_or_after(symbol_points, datetime.fromisoformat("2026-04-07T11:00:00").timestamp())
    close_price = service._same_day_close_price(symbol_points, "2026-04-07", service._read_points(Path(chart_dir / "intraday_300750_2026-04-07.json"))[0]["ts"])
    next_close_price = service._next_day_close_price(symbol_points, "2026-04-07")

    assert one_hour_price == 96.0
    assert close_price == 95.0
    assert next_close_price == 94.0


def test_tracking_service_builds_learning_feedback(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    service = RealtimeAIReviewTrackingService(settings)
    conn = connect_db(settings)
    try:
        service.persist_reviews(
            conn,
            [
                {
                    "event_id": "evt-veto",
                    "review_key": "paper_main:action:300750:BUY:0",
                    "submitted_at": "2026-04-07T10:00:00",
                    "trade_date": "2026-04-07",
                    "symbol": "300750",
                    "candidate_type": "action",
                    "draft_action": "BUY",
                    "reviewed_action": "HOLD",
                    "final_action": "HOLD",
                    "review_role": "VETO",
                    "review_status": "DONE",
                    "applied": True,
                },
                {
                    "event_id": "evt-veto-2",
                    "review_key": "paper_main:action:300751:BUY:0",
                    "submitted_at": "2026-04-07T10:01:00",
                    "trade_date": "2026-04-07",
                    "symbol": "300751",
                    "candidate_type": "action",
                    "draft_action": "BUY",
                    "reviewed_action": "HOLD",
                    "final_action": "HOLD",
                    "review_role": "VETO",
                    "review_status": "DONE",
                    "applied": True,
                },
                {
                    "event_id": "evt-soften",
                    "review_key": "paper_main:action:002594:SELL:100",
                    "submitted_at": "2026-04-07T10:05:00",
                    "trade_date": "2026-04-07",
                    "symbol": "002594",
                    "candidate_type": "action",
                    "draft_action": "SELL",
                    "reviewed_action": "HOLD",
                    "final_action": "HOLD",
                    "review_role": "SOFTEN",
                    "review_status": "DONE",
                    "applied": True,
                    "market_regime_name": "TRENDING_UP",
                },
                {
                    "event_id": "evt-soften-2",
                    "review_key": "paper_main:action:002595:SELL:100",
                    "submitted_at": "2026-04-07T10:06:00",
                    "trade_date": "2026-04-07",
                    "symbol": "002595",
                    "candidate_type": "action",
                    "draft_action": "SELL",
                    "reviewed_action": "HOLD",
                    "final_action": "HOLD",
                    "review_role": "SOFTEN",
                    "review_status": "DONE",
                    "applied": True,
                    "market_regime_name": "TRENDING_UP",
                },
                {
                    "event_id": "evt-trigger",
                    "review_key": "paper_main:holding:000001:HOLD:500",
                    "submitted_at": "2026-04-07T10:10:00",
                    "trade_date": "2026-04-07",
                    "symbol": "000001",
                    "candidate_type": "holding",
                    "draft_action": "HOLD",
                    "reviewed_action": "REDUCE",
                    "final_action": "REDUCE",
                    "review_role": "TRIGGER",
                    "review_status": "DONE",
                    "applied": True,
                    "market_regime_name": "RISK_OFF",
                },
                {
                    "event_id": "evt-trigger-2",
                    "review_key": "paper_main:holding:000002:HOLD:500",
                    "submitted_at": "2026-04-07T10:11:00",
                    "trade_date": "2026-04-07",
                    "symbol": "000002",
                    "candidate_type": "holding",
                    "draft_action": "HOLD",
                    "reviewed_action": "SELL",
                    "final_action": "SELL",
                    "review_role": "TRIGGER",
                    "review_status": "DONE",
                    "applied": True,
                    "market_regime_name": "RISK_OFF",
                },
            ],
        )
        conn.execute(
            """
            UPDATE realtime_ai_review_events
            SET benefit_close = CASE event_id
                    WHEN 'evt-veto' THEN 0.012
                    WHEN 'evt-veto-2' THEN 0.011
                    WHEN 'evt-soften' THEN 0.008
                    WHEN 'evt-soften-2' THEN 0.007
                    WHEN 'evt-trigger' THEN 0.009
                    WHEN 'evt-trigger-2' THEN 0.010
                END,
                benefit_next_close = CASE event_id
                    WHEN 'evt-veto' THEN 0.010
                    WHEN 'evt-veto-2' THEN 0.009
                    WHEN 'evt-soften' THEN 0.006
                    WHEN 'evt-soften-2' THEN 0.005
                    WHEN 'evt-trigger' THEN 0.011
                    WHEN 'evt-trigger-2' THEN 0.010
                END
            """
        )
        conn.commit()
        feedback = service.build_learning_feedback(conn, limit=10)
    finally:
        conn.close()

    assert feedback["evaluated_count"] == 6
    assert feedback["positive_close_count"] == 6
    assert feedback["ai_multiplier_bias"] > 0
    assert feedback["risk_multiplier_bias"] > 0
    assert feedback["role_stats"]["VETO"]["count"] == 2
    assert feedback["suggestions"]


def test_tracking_service_async_submit_writes_to_account_db(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    initialize_db(settings, account_id="paper_small_1w")
    service = RealtimeAIReviewTrackingService(settings)

    service.submit_reviews(
        "paper_small_1w",
        [
            {
                "event_id": "evt-small-1",
                "review_key": "paper_small_1w:holding:000890:HOLD:100",
                "submitted_at": "2026-04-07T10:10:00",
                "trade_date": "2026-04-07",
                "symbol": "000890",
                "candidate_type": "holding",
                "draft_action": "HOLD",
                "reviewed_action": "REDUCE",
                "final_action": "REDUCE",
                "review_role": "TRIGGER",
                "review_status": "DONE",
                "applied": True,
            }
        ],
    )

    assert service.wait_for_idle("paper_small_1w", timeout=3.0) is True

    conn = connect_db(settings, account_id="paper_small_1w")
    try:
        row = conn.execute(
            "SELECT event_id, review_status, review_role FROM realtime_ai_review_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert dict(row)["event_id"] == "evt-small-1"
    assert dict(row)["review_status"] == "DONE"
    assert dict(row)["review_role"] == "TRIGGER"
