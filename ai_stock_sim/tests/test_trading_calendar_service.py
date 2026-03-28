from __future__ import annotations

from datetime import date

from app.settings import load_settings
from app.trading_calendar_service import TradingCalendarService


def test_weekend_is_not_trading_day():
    service = TradingCalendarService(load_settings())
    assert service.is_trading_day(date(2026, 3, 28)) is False


def test_known_holiday_is_not_trading_day():
    service = TradingCalendarService(load_settings())
    assert service.is_trading_day(date(2026, 2, 18)) is False


def test_next_trading_day_skips_holiday_range():
    service = TradingCalendarService(load_settings())
    assert service.next_trading_day(date(2026, 2, 13)).isoformat() == "2026-02-24"
