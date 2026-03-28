from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .settings import Settings, load_settings


class TradingCalendarService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.timezone = ZoneInfo(self.settings.trading_calendar.timezone)
        self.closed_dates = self._load_closed_dates()

    def is_trading_day(self, value: date | datetime | str) -> bool:
        day = self._coerce_date(value)
        if not self.settings.trading_calendar.enabled:
            return day.weekday() < 5
        if day.weekday() >= 5:
            return False
        return day.isoformat() not in self.closed_dates

    def next_trading_day(self, value: date | datetime | str) -> date:
        day = self._coerce_date(value)
        cursor = day + timedelta(days=1)
        while not self.is_trading_day(cursor):
            cursor += timedelta(days=1)
        return cursor

    def previous_trading_day(self, value: date | datetime | str) -> date:
        day = self._coerce_date(value)
        cursor = day - timedelta(days=1)
        while not self.is_trading_day(cursor):
            cursor -= timedelta(days=1)
        return cursor

    def trading_day_summary(self, value: date | datetime | str) -> dict[str, object]:
        day = self._coerce_date(value)
        return {
            "date": day.isoformat(),
            "is_trading_day": self.is_trading_day(day),
            "next_trading_day": self.next_trading_day(day).isoformat(),
            "previous_trading_day": self.previous_trading_day(day).isoformat(),
        }

    def _load_closed_dates(self) -> set[str]:
        path = self.settings.trading_calendar_file
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        raw_dates = payload.get("closed_dates") or []
        return {str(item) for item in raw_dates if str(item)}

    def _coerce_date(self, value: date | datetime | str) -> date:
        if isinstance(value, datetime):
            dt = value.astimezone(self.timezone) if value.tzinfo else value.replace(tzinfo=self.timezone)
            return dt.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if "T" in text or " " in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            dt = dt.astimezone(self.timezone) if dt.tzinfo else dt.replace(tzinfo=self.timezone)
            return dt.date()
        return date.fromisoformat(text)
