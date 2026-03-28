from __future__ import annotations

import pandas as pd

from app.market_data_service import MarketDataService
from app.market_clock import MarketClock
from app.settings import load_settings


def test_history_fallback_returns_dataframe(monkeypatch):
    service = MarketDataService(load_settings())

    def fake_eastmoney(*args, **kwargs):
        return pd.DataFrame(
            [
                {"trade_date": "2026-03-20", "open": 10, "close": 11, "high": 11.2, "low": 9.8, "volume": 1000, "amount": 11000},
                {"trade_date": "2026-03-21", "open": 11, "close": 11.5, "high": 11.8, "low": 10.9, "volume": 1100, "amount": 12000},
            ]
        )

    monkeypatch.setattr(service, "_fetch_history_eastmoney", fake_eastmoney)
    frame = service.fetch_history_daily("600036")
    assert not frame.empty
    assert list(frame.columns) == ["trade_date", "open", "close", "high", "low", "volume", "amount"]


def test_history_prefers_fresh_cache(tmp_path):
    settings = load_settings()
    settings.project_root = tmp_path
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    service = MarketDataService(settings)
    cache_path = service._cache_file("history_frame", "600036_stock_20260101_20260327_20")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        '[{"rows":[{"trade_date":"2026-03-20","open":10,"close":11,"high":11.2,"low":9.8,"volume":1000,"amount":11000}]}]',
        encoding="utf-8",
    )
    cache_path.write_text(
        '{"rows":[{"trade_date":"2026-03-20","open":10,"close":11,"high":11.2,"low":9.8,"volume":1000,"amount":11000}]}',
        encoding="utf-8",
    )
    frame = service.fetch_history_daily("600036", start_date="20260101", end_date="20260327", limit=20)
    assert len(frame) == 1
    assert float(frame.iloc[0]["close"]) == 11.0


def test_market_clock_reports_post_close_phase():
    settings = load_settings()
    settings.market_session.allow_post_close_paper_execution = False
    clock = MarketClock(settings.market_session)
    phase = clock.phase(now=pd.Timestamp("2026-03-27 15:30:00", tz="Asia/Shanghai").to_pydatetime())
    assert phase.phase_name == "post_close_analysis"
    assert phase.should_run_strategy is True
    assert phase.should_place_orders is False


def test_market_clock_can_enable_post_close_execution():
    settings = load_settings()
    settings.market_session.allow_post_close_paper_execution = True
    clock = MarketClock(settings.market_session)
    phase = clock.phase(now=pd.Timestamp("2026-03-27 15:30:00", tz="Asia/Shanghai").to_pydatetime())
    assert phase.phase_name == "post_close_execution"
    assert phase.should_run_strategy is True
    assert phase.should_place_orders is True
