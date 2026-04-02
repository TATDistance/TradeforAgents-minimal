from __future__ import annotations

from datetime import datetime

from app.adaptive_weight_service import AdaptiveWeightService
from app.db import connect_db, initialize_db, seed_account, write_order, write_strategy_evaluation
from app.models import OrderRecord, StrategyEvaluation
from app.settings import load_settings


def test_adaptive_weight_service_smoothly_adjusts_weights(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
    settings.adaptive.min_trades_for_adjustment = 1
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = connect_db(settings)
    try:
        write_strategy_evaluation(
            conn,
            StrategyEvaluation(
                ts=datetime(2026, 4, 2, 15, 0, 0),
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
                ts=datetime(2026, 4, 2, 9, 31, 0),
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
                ts=datetime(2026, 4, 2, 14, 55, 0),
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
