from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from .settings import MarketSessionConfig


@dataclass(frozen=True)
class MarketPhase:
    now: datetime
    is_trading_day: bool
    is_trading_session: bool
    is_post_close_analysis: bool
    should_fetch_realtime: bool
    should_run_strategy: bool
    should_place_orders: bool
    phase_name: str


def parse_hhmm(value: str) -> time:
    hour_str, minute_str = value.split(":", 1)
    return time(hour=int(hour_str), minute=int(minute_str))


class MarketClock:
    def __init__(self, config: MarketSessionConfig) -> None:
        self.config = config
        self.tz = timezone(timedelta(hours=8), name=config.timezone)
        self.trade_start = parse_hhmm(config.trade_start)
        self.lunch_start = parse_hhmm(config.lunch_start)
        self.lunch_end = parse_hhmm(config.lunch_end)
        self.trade_end = parse_hhmm(config.trade_end)
        self.post_close_analysis_start = parse_hhmm(config.post_close_analysis_start)
        self.post_close_analysis_end = parse_hhmm(config.post_close_analysis_end)

    def phase(self, now: datetime | None = None) -> MarketPhase:
        current = now.astimezone(self.tz) if now and now.tzinfo else (now.replace(tzinfo=self.tz) if now else datetime.now(self.tz))
        is_weekend = current.weekday() >= 5
        if self.config.enable_weekend_guard and is_weekend:
            return MarketPhase(
                now=current,
                is_trading_day=False,
                is_trading_session=False,
                is_post_close_analysis=False,
                should_fetch_realtime=False,
                should_run_strategy=False,
                should_place_orders=False,
                phase_name="weekend",
            )

        current_time = current.time()
        in_morning = self.trade_start <= current_time < self.lunch_start
        in_afternoon = self.lunch_end <= current_time < self.trade_end
        in_trading = in_morning or in_afternoon
        in_post_close = self.post_close_analysis_start <= current_time <= self.post_close_analysis_end
        should_fetch = in_trading or in_post_close
        return MarketPhase(
            now=current,
            is_trading_day=True,
            is_trading_session=in_trading,
            is_post_close_analysis=in_post_close,
            should_fetch_realtime=should_fetch,
            should_run_strategy=in_trading or in_post_close,
            should_place_orders=in_trading or (in_post_close and self.config.allow_post_close_paper_execution),
            phase_name=self._phase_name(current_time, in_trading, in_post_close),
        )

    def _phase_name(self, current_time: time, in_trading: bool, in_post_close: bool) -> str:
        if in_trading:
            return "trading"
        if self.lunch_start <= current_time < self.lunch_end:
            return "lunch_break"
        if in_post_close:
            return "post_close_execution" if self.config.allow_post_close_paper_execution else "post_close_analysis"
        if current_time < self.trade_start:
            return "pre_open"
        return "after_hours"
