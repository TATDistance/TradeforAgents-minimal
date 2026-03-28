from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from .models import MarketPhaseState
from .settings import Settings, load_settings
from .trading_calendar_service import TradingCalendarService


class MarketPhaseService:
    def __init__(self, settings: Settings | None = None, calendar_service: TradingCalendarService | None = None) -> None:
        self.settings = settings or load_settings()
        self.calendar_service = calendar_service or TradingCalendarService(self.settings)
        self.timezone = ZoneInfo(self.settings.trading_calendar.timezone)
        self.config = self.settings.market_phase
        self.pre_open_start = self._parse_time(self.config.pre_open_start)
        self.open_call_start = self._parse_time(self.config.open_call_start)
        self.open_call_end = self._parse_time(self.config.open_call_end)
        self.am_continuous_start = self._parse_time(self.config.am_continuous_start)
        self.am_continuous_end = self._parse_time(self.config.am_continuous_end)
        self.midday_start = self._parse_time(self.config.midday_start)
        self.midday_end = self._parse_time(self.config.midday_end)
        self.pm_continuous_start = self._parse_time(self.config.pm_continuous_start)
        self.pm_continuous_end = self._parse_time(self.config.pm_continuous_end)
        self.closing_call_start = self._parse_time(self.config.closing_call_start)
        self.closing_call_end = self._parse_time(self.config.closing_call_end)

    def resolve(self, now: datetime | None = None) -> MarketPhaseState:
        current = now.astimezone(self.timezone) if now and now.tzinfo else (now.replace(tzinfo=self.timezone) if now else datetime.now(self.timezone))
        trade_day = current.date()
        next_day = self.calendar_service.next_trading_day(trade_day).isoformat()
        prev_day = self.calendar_service.previous_trading_day(trade_day).isoformat()
        if not self.calendar_service.is_trading_day(trade_day):
            return MarketPhaseState(
                is_trading_day=False,
                phase="NON_TRADING_DAY",
                allow_market_update=False,
                allow_signal_generation=False,
                allow_ai_decision=False,
                allow_new_buy=False,
                allow_sell_reduce=False,
                allow_simulate_fill=False,
                allow_post_close_analysis=False,
                allow_report_generation=False,
                reason="当前日期不是 A 股交易日",
                trade_date=trade_day.isoformat(),
                next_trading_day=next_day,
                previous_trading_day=prev_day,
            )

        current_time = current.timetz().replace(tzinfo=None)
        phase = "PRE_OPEN"
        reason = "盘前准备阶段"
        allow_new_buy = False
        allow_sell_reduce = False
        allow_simulate_fill = False
        allow_post_close_analysis = False
        allow_report_generation = False

        if current_time < self.open_call_start:
            phase = "PRE_OPEN"
            reason = "盘前准备阶段"
        elif current_time < self.am_continuous_start:
            phase = "OPEN_CALL_AUCTION"
            reason = "开盘集合竞价阶段"
        elif current_time < self.am_continuous_end:
            phase = "CONTINUOUS_AUCTION_AM"
            reason = "上午连续竞价阶段"
            allow_new_buy = True
            allow_sell_reduce = True
            allow_simulate_fill = True
        elif current_time < self.midday_end:
            phase = "MIDDAY_BREAK"
            reason = "午间休市阶段"
        elif current_time < self.pm_continuous_end:
            phase = "CONTINUOUS_AUCTION_PM"
            reason = "下午连续竞价阶段"
            allow_new_buy = True
            allow_sell_reduce = True
            allow_simulate_fill = True
        elif current_time < self.closing_call_end:
            phase = "CLOSING_AUCTION"
            reason = "收盘集合竞价阶段"
        else:
            phase = "POST_CLOSE"
            reason = "收盘后分析阶段"
            allow_post_close_analysis = True
            allow_report_generation = True

        return MarketPhaseState(
            is_trading_day=True,
            phase=phase,
            allow_market_update=True,
            allow_signal_generation=True,
            allow_ai_decision=True,
            allow_new_buy=allow_new_buy,
            allow_sell_reduce=allow_sell_reduce,
            allow_simulate_fill=allow_simulate_fill,
            allow_post_close_analysis=allow_post_close_analysis,
            allow_report_generation=allow_report_generation,
            reason=reason,
            trade_date=trade_day.isoformat(),
            next_trading_day=next_day,
            previous_trading_day=prev_day,
        )

    @staticmethod
    def _parse_time(raw: str) -> time:
        if isinstance(raw, int):
            hour = raw // 3600
            minute = (raw % 3600) // 60
            second = raw % 60
            return time(hour=hour, minute=minute, second=second)
        return time.fromisoformat(str(raw))
