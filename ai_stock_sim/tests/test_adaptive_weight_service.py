from __future__ import annotations

from datetime import datetime

from app.adaptive_weight_service import AdaptiveWeightService
from app.db import connect_db, initialize_db, seed_account, write_order, write_strategy_evaluation
from app.models import OrderRecord, StrategyEvaluation
from app.realtime_ai_review_tracking_service import RealtimeAIReviewTrackingService
from app.settings import load_settings


def test_adaptive_weight_service_smoothly_adjusts_weights(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    settings.adaptive.min_trades_for_adjustment = 1
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    now = datetime.now().replace(microsecond=0)
    try:
        write_strategy_evaluation(
            conn,
            StrategyEvaluation(
                ts=now,
                strategy_name="momentum",
                period_type="daily",
                total_return=0.04,
                max_drawdown=0.01,
                win_rate=0.7,
                pnl_ratio=1.8,
                profit_factor=2.0,
                expectancy=0.02,
                score_total=85.0,
                grade="A",
                total_trades=1,
            ),
        )
        write_order(
            conn,
            OrderRecord(
                symbol="300750",
                side="BUY",
                price=100.0,
                qty=100,
                fee=1.0,
                status="FILLED",
                ts=now.replace(hour=9, minute=31, second=0),
                strategy_name="momentum",
                mode_name="ai_decision_engine_mode",
            ),
        )
        write_order(
            conn,
            OrderRecord(
                symbol="300750",
                side="SELL",
                price=106.0,
                qty=100,
                fee=1.0,
                status="FILLED",
                ts=now.replace(hour=14, minute=55, second=0),
                strategy_name="macd_trend",
                mode_name="ai_decision_engine_mode",
            ),
        )
        conn.commit()

        payload = AdaptiveWeightService(settings).update_strategy_weights(conn)
    finally:
        conn.close()

    assert float(payload["strategy_weights"]["momentum"]) > 1.0
    assert payload["adjustments"]


def test_adaptive_weight_service_includes_ai_review_feedback(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    settings.adaptive.min_trades_for_adjustment = 1
    initialize_db(settings)
    seed_account(settings, cash=100000)
    tracker = RealtimeAIReviewTrackingService(settings)
    conn = connect_db(settings)
    now = datetime.now().replace(microsecond=0)
    try:
        write_strategy_evaluation(
            conn,
            StrategyEvaluation(
                ts=now,
                strategy_name="breakout",
                period_type="daily",
                total_return=0.03,
                max_drawdown=0.01,
                win_rate=0.65,
                pnl_ratio=1.4,
                profit_factor=1.8,
                expectancy=0.015,
                score_total=82.0,
                grade="A",
                total_trades=2,
            ),
        )
        tracker.persist_reviews(
            conn,
            [
                {
                    "event_id": "evt1",
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
                    "event_id": "evt2",
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
                    "event_id": "evt3",
                    "review_key": "paper_main:action:002594:SELL:100",
                    "submitted_at": "2026-04-07T10:02:00",
                    "trade_date": "2026-04-07",
                    "symbol": "002594",
                    "candidate_type": "action",
                    "draft_action": "SELL",
                    "reviewed_action": "HOLD",
                    "final_action": "HOLD",
                    "review_role": "SOFTEN",
                    "review_status": "DONE",
                    "applied": True,
                },
                {
                    "event_id": "evt4",
                    "review_key": "paper_main:action:002595:SELL:100",
                    "submitted_at": "2026-04-07T10:03:00",
                    "trade_date": "2026-04-07",
                    "symbol": "002595",
                    "candidate_type": "action",
                    "draft_action": "SELL",
                    "reviewed_action": "HOLD",
                    "final_action": "HOLD",
                    "review_role": "SOFTEN",
                    "review_status": "DONE",
                    "applied": True,
                },
                {
                    "event_id": "evt5",
                    "review_key": "paper_main:holding:000001:HOLD:500",
                    "submitted_at": "2026-04-07T10:04:00",
                    "trade_date": "2026-04-07",
                    "symbol": "000001",
                    "candidate_type": "holding",
                    "draft_action": "HOLD",
                    "reviewed_action": "REDUCE",
                    "final_action": "REDUCE",
                    "review_role": "TRIGGER",
                    "review_status": "DONE",
                    "applied": True,
                },
                {
                    "event_id": "evt6",
                    "review_key": "paper_main:holding:000002:HOLD:500",
                    "submitted_at": "2026-04-07T10:05:00",
                    "trade_date": "2026-04-07",
                    "symbol": "000002",
                    "candidate_type": "holding",
                    "draft_action": "HOLD",
                    "reviewed_action": "SELL",
                    "final_action": "SELL",
                    "review_role": "TRIGGER",
                    "review_status": "DONE",
                    "applied": True,
                },
            ],
        )
        conn.execute(
            """
            UPDATE realtime_ai_review_events
            SET benefit_close = CASE event_id
                    WHEN 'evt1' THEN 0.012
                    WHEN 'evt2' THEN 0.010
                    WHEN 'evt3' THEN 0.008
                    WHEN 'evt4' THEN 0.006
                    WHEN 'evt5' THEN 0.009
                    WHEN 'evt6' THEN 0.011
                END,
                benefit_next_close = CASE event_id
                    WHEN 'evt1' THEN 0.011
                    WHEN 'evt2' THEN 0.009
                    WHEN 'evt3' THEN 0.007
                    WHEN 'evt4' THEN 0.005
                    WHEN 'evt5' THEN 0.010
                    WHEN 'evt6' THEN 0.012
                END
            """
        )
        conn.commit()

        payload = AdaptiveWeightService(settings).update_strategy_weights(conn)
    finally:
        conn.close()

    feedback = payload["ai_review_feedback"]
    assert feedback["evaluated_count"] == 6
    assert feedback["suggestions"]
    assert float(payload["ai_score_multiplier"]) > 1.0
