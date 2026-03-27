from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from app.db import initialize_db, seed_account
from app.market_clock import MarketPhase
from app.models import AIDecision, FinalSignal, MarketQuote, StrategySignal
from app.scheduler import TradingScheduler
from app.settings import load_settings


def test_smoke_bootstrap(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    assert settings.db_path.exists()


def test_scheduler_skips_orders_after_close(tmp_path, monkeypatch):
    settings = load_settings()
    settings.project_root = tmp_path
    initialize_db(settings)
    seed_account(settings, cash=100000)
    scheduler = TradingScheduler(settings=settings)

    monkeypatch.setattr(
        scheduler.market_clock,
        "phase",
        lambda: MarketPhase(
            now=datetime(2026, 3, 27, 15, 30),
            is_trading_day=True,
            is_trading_session=False,
            is_post_close_analysis=True,
            should_fetch_realtime=True,
            should_run_strategy=True,
            should_place_orders=False,
            phase_name="post_close_analysis",
        ),
    )
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
        lambda grouped, trade_date=None: (
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
    assert result["phase"] == "post_close_analysis"
    assert result["final_signal_count"] == 1
    assert result["execution_events"] == []

    conn = sqlite3.connect(str(settings.db_path))
    try:
        order_count = conn.execute("SELECT COUNT(1) FROM orders").fetchone()[0]
        signal_count = conn.execute("SELECT COUNT(1) FROM final_signals").fetchone()[0]
    finally:
        conn.close()
    assert order_count == 0
    assert signal_count == 1
