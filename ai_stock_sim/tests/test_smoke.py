from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from app.db import initialize_db, seed_account, write_account_snapshot, write_order
from app.evaluation_service import EvaluationService
from app.backtest_service import BacktestService
from app.models import AIDecision, AccountSnapshot, ExecutionGateState, FinalSignal, MarketPhaseState, MarketQuote, OrderRecord, StrategySignal
from app.scheduler import TradingScheduler
from app.settings import load_settings


def test_smoke_bootstrap(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    assert settings.db_path.exists()
    conn = sqlite3.connect(str(settings.db_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "strategy_evaluations" in tables
    assert "mode_comparisons" in tables
    assert "manual_execution_logs" in tables


def test_scheduler_skips_orders_after_close(tmp_path, monkeypatch):
    settings = load_settings()
    settings.project_root = tmp_path
    settings.decision_engine.mode = "legacy_review_mode"
    initialize_db(settings)
    seed_account(settings, cash=100000)
    scheduler = TradingScheduler(settings=settings)

    phase_state = MarketPhaseState(
        is_trading_day=True,
        phase="POST_CLOSE",
        allow_market_update=True,
        allow_signal_generation=True,
        allow_ai_decision=True,
        allow_new_buy=False,
        allow_sell_reduce=False,
        allow_simulate_fill=False,
        allow_post_close_analysis=True,
        allow_report_generation=True,
        trade_date="2026-03-27",
        next_trading_day="2026-03-30",
        previous_trading_day="2026-03-26",
        reason="收盘后分析阶段",
    )
    gate_state = ExecutionGateState(
        can_update_market=True,
        can_generate_signal=True,
        can_run_ai_decision=True,
        can_plan_actions=True,
        can_open_position=False,
        can_reduce_position=False,
        can_execute_fill=False,
        can_generate_report=True,
        can_mark_to_market=True,
        intent_only_mode=True,
        reason="收盘后只允许盘后分析",
        phase="POST_CLOSE",
        is_trading_day=True,
    )
    monkeypatch.setattr(scheduler.market_phase_service, "resolve", lambda now=None: phase_state)
    monkeypatch.setattr(scheduler.execution_gate_service, "resolve", lambda _phase: gate_state)
    monkeypatch.setattr(
        scheduler.universe,
        "build_universe",
        lambda: scheduler.universe.empty_result("test"),
    )
    scheduler.universe.build_universe = lambda: type("U", (), {
        "snapshot": pd.DataFrame([{"symbol": "600036", "asset_type": "stock"}]),
        "selected_symbols": ["600036"],
        "warnings": [],
        "data_source": "test",
    })()
    monkeypatch.setattr(
        scheduler.strategy_engine,
        "run_batch",
        lambda symbols, asset_type_map=None: {
            "600036": [
                StrategySignal(symbol="600036", strategy="momentum", action="BUY", score=0.7, signal_price=40.0, stop_loss=38.0, take_profit=44.0, position_pct=0.10, reason="m"),
                StrategySignal(symbol="600036", strategy="breakout", action="BUY", score=0.75, signal_price=40.2, stop_loss=38.5, take_profit=45.0, position_pct=0.12, reason="b"),
            ]
        },
    )
    monkeypatch.setattr(
        scheduler.signal_fusion,
        "fuse",
        lambda grouped, trade_date=None, **kwargs: (
            [
                FinalSignal(
                    symbol="600036",
                    action="BUY",
                    entry_price=40.1,
                    stop_loss=38.0,
                    take_profit=44.5,
                    position_pct=0.10,
                    confidence=0.74,
                    source_strategies=["momentum", "breakout"],
                    ai_approved=True,
                    ai_reason="ok",
                    strategy_reason="ok",
                )
            ],
            [
                AIDecision(
                    symbol="600036",
                    ai_action="BUY",
                    confidence=0.8,
                    risk_score=0.2,
                    approved=True,
                    reason="ok",
                    source_mode="test",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        scheduler.market_data,
        "fetch_realtime_quote",
        lambda symbol: MarketQuote(
            ts=datetime.now(),
            symbol=symbol,
            name=symbol,
            market="SH",
            asset_type="stock",
            latest_price=40.0,
            pct_change=0.01,
            open_price=39.8,
            high_price=40.2,
            low_price=39.6,
            prev_close=39.5,
            volume=1000,
            amount=100000000,
            data_source="test",
        ),
    )

    result = scheduler.run_cycle()
    assert result["phase"] == "POST_CLOSE"
    assert result["final_signal_count"] == 1
    assert any(event["intent_only"] for event in result["execution_events"])

    conn = sqlite3.connect(str(settings.db_path))
    try:
        rows = conn.execute("SELECT status, intent_only FROM orders").fetchall()
        signal_count = conn.execute("SELECT COUNT(1) FROM final_signals").fetchone()[0]
    finally:
        conn.close()
    assert rows
    assert all(int(row[1]) == 1 for row in rows)
    assert signal_count == 1


def test_backtest_report_lists_expanded_strategies(tmp_path, monkeypatch):
    settings = load_settings()
    settings.project_root = tmp_path
    service = BacktestService(settings)

    fake_frame = pd.DataFrame(
        [
            {"trade_date": f"2026-01-{idx:02d}", "open": 10 + idx * 0.1, "close": 10 + idx * 0.12, "high": 10 + idx * 0.13, "low": 10 + idx * 0.08, "volume": 1000 + idx, "amount": 100000 + idx * 100}
            for idx in range(1, 100)
        ]
    )
    monkeypatch.setattr(service.market_data, "fetch_history_daily", lambda *args, **kwargs: fake_frame)
    report = service.run_simple_backtest("600036", strategy_name="dual_ma")
    assert "dual_ma" == report["strategy"]
    assert "macd_trend" in report["available_strategies"]
    assert "trend_pullback" in report["available_strategies"]


def test_evaluation_persists_exit_strategy_scores(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        write_account_snapshot(
            conn,
            AccountSnapshot(
                ts=datetime(2026, 3, 27, 9, 30),
                cash=100000,
                equity=100000,
                market_value=0,
                realized_pnl=0,
                unrealized_pnl=0,
                drawdown=0,
            ),
        )
        write_order(
            conn,
            OrderRecord(
                symbol="600036",
                side="BUY",
                price=40.0,
                qty=100,
                fee=5,
                tax=0,
                slippage=2,
                status="FILLED",
                strategy_name="momentum",
                mode_name="strategy_plus_ai_plus_risk",
                ts=datetime(2026, 3, 27, 9, 35),
            ),
        )
        write_order(
            conn,
            OrderRecord(
                symbol="600036",
                side="SELL",
                price=42.0,
                qty=100,
                fee=5,
                tax=2,
                slippage=2,
                status="FILLED",
                strategy_name="dual_ma",
                mode_name="strategy_plus_ai_plus_risk",
                ts=datetime(2026, 3, 27, 14, 30),
            ),
        )
        write_account_snapshot(
            conn,
            AccountSnapshot(
                ts=datetime(2026, 3, 27, 15, 0),
                cash=100186,
                equity=100186,
                market_value=0,
                realized_pnl=186,
                unrealized_pnl=0,
                drawdown=0,
            ),
        )
        service = EvaluationService(settings)
        service.persist_evaluations(conn, reference_date="2026-03-27")
        conn.commit()
        row = conn.execute(
            "SELECT strategy_name, total_trades FROM strategy_evaluations WHERE strategy_name = ? AND period_type = ?",
            ("exit::dual_ma", "daily"),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["strategy_name"] == "exit::dual_ma"
    assert int(row["total_trades"]) >= 1
