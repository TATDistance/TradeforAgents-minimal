from __future__ import annotations

from datetime import datetime

from app.db import connect_db, initialize_db, seed_account, write_order, write_strategy_evaluation
from app.models import OrderRecord, StrategyEvaluation
from app.settings import load_settings
from app.strategy_evaluation_service import StrategyEvaluationService


def test_strategy_evaluation_service_returns_summary(tmp_path) -> None:
    settings = load_settings()
    settings.project_root = tmp_path
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
                total_return=0.02,
                max_drawdown=0.01,
                win_rate=0.5,
                pnl_ratio=1.5,
                profit_factor=1.8,
                expectancy=0.01,
                score_total=78.0,
                grade="B+",
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
                price=105.0,
                qty=100,
                fee=1.0,
                status="FILLED",
                ts=datetime(2026, 4, 2, 14, 55, 0),
                strategy_name="macd_trend",
                mode_name="ai_decision_engine_mode",
            ),
        )
        conn.commit()

        payload = StrategyEvaluationService(settings).evaluate_strategy_performance(conn, window_days=5)
    finally:
        conn.close()

    assert "momentum" in payload
    assert payload["momentum"]["trades"] == 1
    assert payload["momentum"]["win_rate"] > 0
    assert payload["momentum"]["avg_return"] > 0
