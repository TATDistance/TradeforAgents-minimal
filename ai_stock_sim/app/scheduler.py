from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from apscheduler.schedulers.background import BackgroundScheduler

from .db import connect_db, initialize_db, write_ai_decision, write_final_signal, write_signal, write_system_log
from .logger import log_event
from .market_data_service import MarketDataService
from .market_clock import MarketClock
from .mock_broker import MockBroker
from .models import StrategySignal
from .portfolio_service import build_portfolio_state, mark_to_market
from .review_service import ReviewService
from .risk_engine import RiskEngine
from .settings import Settings, load_settings
from .signal_fusion import SignalFusion
from .strategy_engine import StrategyEngine
from .universe_service import UniverseService


class TradingScheduler:
    def __init__(self, settings: Settings | None = None, logger=None) -> None:
        self.settings = settings or load_settings()
        self.logger = logger
        self.universe = UniverseService(self.settings)
        self.market_data = MarketDataService(self.settings)
        self.market_clock = MarketClock(self.settings.market_session)
        self.strategy_engine = StrategyEngine(self.settings, self.market_data)
        self.signal_fusion = SignalFusion(self.settings)
        self.risk_engine = RiskEngine(self.settings)
        self.broker = MockBroker(self.settings)
        self.review_service = ReviewService()
        self.scheduler = BackgroundScheduler()
        self._last_t1_release_date: str | None = None

    def start(self) -> None:
        self.scheduler.add_job(self.run_cycle, "interval", seconds=self.settings.refresh_interval_seconds, max_instances=1)
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    def run_cycle(self) -> Dict[str, object]:
        phase = self.market_clock.phase()
        trade_date = phase.now.date().isoformat()
        conn = connect_db(self.settings)
        initialize_db(self.settings)
        try:
            if phase.is_trading_day and self._last_t1_release_date != trade_date:
                self.broker.release_t1_positions(conn)
                self._last_t1_release_date = trade_date

            universe_result = self.universe.build_universe() if phase.should_fetch_realtime else self.universe.empty_result("market_closed")
            asset_type_map = {
                str(row["symbol"]): str(row["asset_type"])
                for _, row in universe_result.snapshot.iterrows()
            }
            grouped: Dict[str, List[StrategySignal]] = {}
            final_signals = []
            ai_decisions = []
            if phase.should_run_strategy:
                grouped = self.strategy_engine.run_batch(universe_result.selected_symbols, asset_type_map=asset_type_map)
                for signal_list in grouped.values():
                    for signal in signal_list:
                        write_signal(conn, signal)
                final_signals, ai_decisions = self.signal_fusion.fuse(grouped, trade_date=trade_date)
                for decision in ai_decisions:
                    write_ai_decision(conn, decision)
                for final_signal in final_signals:
                    write_final_signal(conn, final_signal)

            portfolio = build_portfolio_state(conn)
            execution_events: List[Dict[str, object]] = []
            if phase.should_place_orders:
                for final_signal in final_signals:
                    try:
                        quote = self.market_data.fetch_realtime_quote(final_signal.symbol)
                    except Exception as exc:
                        write_system_log(conn, "WARNING", "market_data", f"{final_signal.symbol} 实时行情获取失败，跳过成交: {exc}")
                        continue
                    risk = self.risk_engine.evaluate(final_signal, quote, portfolio)
                    order = self.broker.execute_signal(conn, final_signal, risk, latest_price=quote.latest_price)
                    execution_events.append({"symbol": final_signal.symbol, "status": order.status, "qty": order.qty})
                    portfolio = build_portfolio_state(conn)
            elif final_signals:
                write_system_log(conn, "INFO", "scheduler", f"当前处于 {phase.phase_name}，仅生成信号，不执行模拟成交")

            latest_prices: Dict[str, float] = {}
            quote_symbols = list(dict.fromkeys(universe_result.selected_symbols + list(portfolio.current_positions.keys())))
            for symbol in quote_symbols:
                if not phase.should_fetch_realtime and symbol not in portfolio.current_positions:
                    continue
                try:
                    latest_prices[symbol] = self.market_data.fetch_realtime_quote(symbol).latest_price
                except Exception as exc:
                    write_system_log(conn, "WARNING", "market_data", f"{symbol} 最新价刷新失败，已跳过: {exc}")
            snapshot = mark_to_market(conn, latest_prices)
            from .db import write_account_snapshot  # local import to avoid cycle

            write_account_snapshot(conn, snapshot)
            for warning in universe_result.warnings:
                write_system_log(conn, "WARNING", "universe", warning)
            conn.commit()
            if self.logger:
                log_event(
                    self.logger,
                    "info",
                    "scheduler",
                    "cycle_completed",
                    phase=phase.phase_name,
                    candidates=len(universe_result.selected_symbols),
                    final_signals=len(final_signals),
                    orders=len(execution_events),
                )
            return {
                "trade_date": trade_date,
                "phase": phase.phase_name,
                "candidate_count": len(universe_result.selected_symbols),
                "final_signal_count": len(final_signals),
                "execution_events": execution_events,
                "warnings": universe_result.warnings,
            }
        except Exception as exc:
            write_system_log(conn, "ERROR", "scheduler", str(exc))
            conn.commit()
            raise
        finally:
            conn.close()

    def run_end_of_day_review(self) -> Dict[str, object]:
        conn = connect_db(self.settings)
        try:
            report = self.review_service.build_report(conn, datetime.now().date().isoformat())
            path = self.review_service.save_report(report, self.settings.reports_dir)
            return {"report_path": str(path), "summary": report.summary}
        finally:
            conn.close()
