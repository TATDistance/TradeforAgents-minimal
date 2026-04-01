from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

from apscheduler.schedulers.background import BackgroundScheduler

from .action_planner import ActionPlanner
from .ai_decision_engine import AIDecisionEngine
from .ai_portfolio_manager import AIPortfolioManager
from .decision_compare_service import DecisionCompareService
from .decision_context_builder import DecisionContextBuilder
from .decision_mode_router import AI_ENGINE_MODE, COMPARE_MODE, DecisionModeRouter, LEGACY_MODE
from .db import connect_db, initialize_db, write_ai_decision, write_final_signal, write_signal, write_system_log
from .execution_gate_service import ExecutionGateService
from .market_regime_service import MarketRegimeService
from .logger import log_event
from .models import FinalSignal, MarketRegimeState, PortfolioManagerDecision, StrategySignal
from .market_phase_service import MarketPhaseService
from .portfolio_decision_service import PortfolioDecisionService
from .evaluation_service import EvaluationService
from .market_data_service import MarketDataService
from .mock_broker import MockBroker
from .portfolio_service import build_portfolio_feedback, build_portfolio_state, mark_to_market
from .report_service import ReportService
from .review_service import ReviewService
from .risk_engine import RiskEngine
from .settings import Settings, load_settings
from .signal_fusion import SignalFusion
from .strategy_weight_service import StrategyWeightService
from .strategy_engine import StrategyEngine
from .trading_calendar_service import TradingCalendarService
from .universe_service import UniverseService


class TradingScheduler:
    def __init__(self, settings: Settings | None = None, logger=None) -> None:
        self.settings = settings or load_settings()
        self.logger = logger
        self.universe = UniverseService(self.settings)
        self.market_data = MarketDataService(self.settings)
        self.trading_calendar_service = TradingCalendarService(self.settings)
        self.market_phase_service = MarketPhaseService(self.settings, self.trading_calendar_service)
        self.execution_gate_service = ExecutionGateService(self.settings)
        self.market_regime_service = MarketRegimeService(self.settings)
        self.strategy_weight_service = StrategyWeightService(self.settings)
        self.strategy_engine = StrategyEngine(self.settings, self.market_data)
        self.signal_fusion = SignalFusion(self.settings)
        self.decision_context_builder = DecisionContextBuilder(self.settings)
        self.ai_decision_engine = AIDecisionEngine(self.settings)
        self.decision_mode_router = DecisionModeRouter(self.settings)
        self.decision_compare_service = DecisionCompareService()
        self.ai_portfolio_manager = AIPortfolioManager(self.settings)
        self.portfolio_decision_service = PortfolioDecisionService(self.settings)
        self.action_planner = ActionPlanner(self.settings)
        self.risk_engine = RiskEngine(self.settings)
        self.broker = MockBroker(self.settings)
        self.review_service = ReviewService()
        self.evaluation_service = EvaluationService(self.settings)
        self.report_service = ReportService(self.settings, evaluation_service=self.evaluation_service)
        self.scheduler = BackgroundScheduler()
        self._last_t1_release_date: str | None = None
        self._last_evaluation_trade_date: str | None = None
        self._last_report_trade_date: str | None = None
        self._last_phase_key: str | None = None

    def start(self) -> None:
        self.scheduler.add_job(self.run_cycle, "interval", seconds=self.settings.refresh_interval_seconds, max_instances=1)
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    def run_cycle(self) -> Dict[str, object]:
        phase_state = self.market_phase_service.resolve()
        execution_gate = self.execution_gate_service.resolve(phase_state)
        trade_date = phase_state.trade_date
        mode_state = self.decision_mode_router.resolve()
        conn = connect_db(self.settings)
        initialize_db(self.settings)

        def _safe_log(level: str, module: str, message: str) -> None:
            try:
                write_system_log(conn, level, module, message)
            except sqlite3.Error as exc:
                if self.logger:
                    log_event(
                        self.logger,
                        level.lower(),
                        module,
                        "db_log_failed",
                        message=message,
                        db_error=str(exc),
                    )

        try:
            phase_key = f"{trade_date}:{phase_state.phase}"
            if phase_key != self._last_phase_key:
                _safe_log("INFO", "market_phase", f"{trade_date} 阶段切换到 {phase_state.phase}：{phase_state.reason}")
                self._last_phase_key = phase_key

            if phase_state.is_trading_day and self._last_t1_release_date != trade_date:
                self.broker.release_t1_positions(conn)
                self._last_t1_release_date = trade_date

            universe_result = self.universe.build_universe() if execution_gate.can_update_market else self.universe.empty_result("market_closed")
            asset_type_map = {
                str(row["symbol"]): str(row["asset_type"])
                for _, row in universe_result.snapshot.iterrows()
            }
            grouped: Dict[str, List[StrategySignal]] = {}
            feature_map = {}
            feature_fusions = {}
            decision_contexts = {}
            engine_decisions = {}
            compare_result = {}
            final_signals: List[FinalSignal] = []
            ai_decisions = []
            portfolio = build_portfolio_state(conn)
            portfolio_feedback = build_portfolio_feedback(conn, self.settings)
            market_regime = self.market_regime_service.evaluate(universe_result.snapshot, portfolio_feedback)
            self.market_regime_service.save_state(market_regime)
            strategy_weights = self.strategy_weight_service.resolve_weights(market_regime, portfolio_feedback)
            manager_decision = PortfolioManagerDecision(portfolio_view="暂无主动组合建议", risk_mode=portfolio_feedback.get("risk_mode", "NORMAL"), actions=[])
            final_actions = []
            planned_actions = []
            risk_results: List[Dict[str, object]] = []
            if execution_gate.can_generate_signal:
                frame_map = {}

                if mode_state.run_legacy:
                    grouped = self.strategy_engine.run_batch(universe_result.selected_symbols, asset_type_map=asset_type_map)
                    for signal_list in grouped.values():
                        for signal in signal_list:
                            write_signal(conn, signal)
                    context_map = self._build_ai_context_map(universe_result, grouped, portfolio)
                    final_signals, ai_decisions = self.signal_fusion.fuse(
                        grouped,
                        trade_date=trade_date,
                        context_map=context_map,
                        strategy_weights=strategy_weights,
                        market_regime=market_regime,
                        mode_name=LEGACY_MODE,
                    )
                    for decision in ai_decisions:
                        write_ai_decision(conn, decision)
                    signal_ids: Dict[str, int] = {}
                    for final_signal in final_signals:
                        signal_ids[final_signal.symbol] = write_final_signal(conn, final_signal)
                    manager_decision = self.ai_portfolio_manager.review(
                        regime_state=market_regime,
                        portfolio_feedback=portfolio_feedback,
                        candidate_signals=final_signals,
                        strategy_weights=strategy_weights,
                    )
                    legacy_actions = self.portfolio_decision_service.merge(final_signals, manager_decision, market_regime)
                else:
                    signal_ids = {}
                    legacy_actions = []

                if mode_state.run_engine:
                    frame_map = {
                        symbol: self.strategy_engine.load_bars(symbol, asset_type=asset_type_map.get(symbol, "stock"))
                        for symbol in universe_result.selected_symbols
                    }
                    feature_map = {
                        symbol: self.strategy_engine.run_features_for_symbol_on_frame(symbol, frame)
                        for symbol, frame in frame_map.items()
                    }
                    snapshot_rows = {
                        str(row["symbol"]): {
                            "symbol": str(row["symbol"]),
                            "name": str(row.get("name") or row["symbol"]),
                            "latest_price": float(row.get("latest_price") or 0.0),
                            "pct_change": float(row.get("pct_change") or 0.0),
                            "amount": float(row.get("amount") or 0.0),
                            "turnover_rate": float(row.get("turnover_rate") or 0.0),
                        }
                        for _, row in universe_result.snapshot.iterrows()
                    } if hasattr(universe_result, "snapshot") and not universe_result.snapshot.empty else {}
                    feature_fusions = self.signal_fusion.fuse_features(
                        feature_map,
                        strategy_weights=strategy_weights,
                        market_regime=market_regime,
                        portfolio_feedback=portfolio_feedback,
                    )
                    decision_contexts = self.decision_context_builder.build_batch(
                        universe_result.selected_symbols,
                        snapshot_rows,
                        feature_map,
                        frame_map,
                        market_regime,
                        portfolio_feedback,
                        phase_state,
                        execution_gate,
                    )
                    try:
                        engine_decisions = self.ai_decision_engine.decide_batch(
                            decision_contexts,
                            {symbol: item.model_dump() for symbol, item in feature_fusions.items()},
                            trade_date=trade_date,
                        )
                    except Exception as exc:
                        _safe_log("ERROR", "ai_decision_engine", f"AI 决策引擎运行失败: {exc}")
                        mode_state = self.decision_mode_router.fallback_on_failure(mode_state)
                        engine_decisions = {}
                        if mode_state.effective_mode == LEGACY_MODE and not grouped:
                            grouped = self.strategy_engine.run_batch(universe_result.selected_symbols, asset_type_map=asset_type_map)
                            for signal_list in grouped.values():
                                for signal in signal_list:
                                    write_signal(conn, signal)
                            context_map = self._build_ai_context_map(universe_result, grouped, portfolio)
                            final_signals, ai_decisions = self.signal_fusion.fuse(
                                grouped,
                                trade_date=trade_date,
                                context_map=context_map,
                                strategy_weights=strategy_weights,
                                market_regime=market_regime,
                                mode_name=LEGACY_MODE,
                            )
                            for decision in ai_decisions:
                                write_ai_decision(conn, decision)
                            for final_signal in final_signals:
                                signal_ids[final_signal.symbol] = write_final_signal(conn, final_signal)
                            manager_decision = self.ai_portfolio_manager.review(
                                regime_state=market_regime,
                                portfolio_feedback=portfolio_feedback,
                                candidate_signals=final_signals,
                                strategy_weights=strategy_weights,
                            )
                            legacy_actions = self.portfolio_decision_service.merge(final_signals, manager_decision, market_regime)
                    engine_actions = self.portfolio_decision_service.merge_engine(engine_decisions, market_regime) if engine_decisions else []
                else:
                    engine_actions = []

                if mode_state.effective_mode == LEGACY_MODE:
                    final_actions = legacy_actions
                elif mode_state.effective_mode == AI_ENGINE_MODE:
                    final_actions = engine_actions
                else:
                    final_actions = engine_actions
                    compare_result = self.decision_compare_service.compare(final_signals, engine_decisions)
            else:
                signal_ids = {}
                legacy_actions = []
                engine_actions = []

            quote_symbols = list(
                dict.fromkeys(
                    universe_result.selected_symbols
                    + list(portfolio.current_positions.keys())
                    + [action.symbol for action in final_actions if action.symbol != "*"]
                )
            )
            latest_prices: Dict[str, float] = {}
            quote_map = {}
            snapshot_quote_map = {}
            if hasattr(universe_result, "snapshot") and not universe_result.snapshot.empty:
                for _, row in universe_result.snapshot.iterrows():
                    symbol = str(row.get("symbol") or "")
                    if not symbol:
                        continue
                    snapshot_quote_map[symbol] = self.market_data.build_quote_from_snapshot_row(row.to_dict())
            for symbol in quote_symbols:
                if not execution_gate.can_update_market and symbol not in portfolio.current_positions:
                    continue
                try:
                    quote = self.market_data.fetch_realtime_quote(symbol)
                    quote_map[symbol] = quote
                    latest_prices[symbol] = quote.latest_price
                except Exception as exc:
                    snapshot_quote = snapshot_quote_map.get(symbol)
                    if snapshot_quote is not None and snapshot_quote.latest_price > 0:
                        quote_map[symbol] = snapshot_quote
                        latest_prices[symbol] = snapshot_quote.latest_price
                        _safe_log("WARNING", "market_data", f"{symbol} 实时行情获取失败，已回退到本轮快照价格: {exc}")
                    else:
                        _safe_log("WARNING", "market_data", f"{symbol} 最新价刷新失败，已跳过: {exc}")

            planned_actions = self.action_planner.plan(final_actions, portfolio_feedback, latest_prices, phase_state, execution_gate)
            execution_events: List[Dict[str, object]] = []
            if execution_gate.can_execute_fill or execution_gate.intent_only_mode:
                for action in planned_actions:
                    if action.symbol == "*":
                        _safe_log("INFO", "ai_pm", action.reason)
                        continue
                    quote = quote_map.get(action.symbol)
                    if quote is None:
                        _safe_log("WARNING", "market_data", f"{action.symbol} 实时行情获取失败，跳过动作执行")
                        continue
                    effective_risk_mode = str(action.metadata.get("risk_mode") or manager_decision.risk_mode)
                    risk = self.risk_engine.evaluate_action(
                        action,
                        quote,
                        portfolio,
                        risk_mode=effective_risk_mode,
                        phase_state=phase_state,
                        execution_gate=execution_gate,
                    )
                    risk_results.append(
                        {
                            "symbol": action.symbol,
                            "action": action.action,
                            "mode_name": action.mode_name,
                            "phase": action.phase,
                            "intent_only": action.intent_only,
                            "executable_now": action.executable_now,
                            "allowed": risk.allowed,
                            "final_action": risk.final_action,
                            "adjusted_qty": risk.adjusted_qty,
                            "risk_state": risk.risk_state,
                            "phase_blocked": risk.phase_blocked,
                            "reason": risk.reject_reason or action.reason,
                        }
                    )
                    if action.action in {"HOLD", "AVOID_NEW_BUY", "ENTER_DEFENSIVE_MODE"}:
                        _safe_log("INFO", "portfolio_decision", f"{action.symbol} {action.action}: {action.reason}")
                        continue
                    if action.intent_only or not action.executable_now:
                        intent_order = self.broker.record_action_intent(conn, action, risk, signal_id=signal_ids.get(action.symbol))
                        if intent_order is not None:
                            execution_events.append(
                                {
                                    "symbol": action.symbol,
                                    "status": intent_order.status,
                                    "qty": intent_order.qty,
                                    "action": action.action,
                                    "mode_name": action.mode_name,
                                    "intent_only": True,
                                }
                            )
                        continue
                    order = self.broker.execute_action(conn, action, risk, latest_price=quote.latest_price, signal_id=signal_ids.get(action.symbol))
                    if order is not None:
                        execution_events.append(
                            {
                                "symbol": action.symbol,
                                "status": order.status,
                                "qty": order.qty,
                                "action": action.action,
                                "mode_name": action.mode_name,
                                "intent_only": False,
                            }
                        )
                    portfolio = build_portfolio_state(conn)
            elif final_signals:
                _safe_log("INFO", "scheduler", f"当前处于 {phase_state.phase}，仅生成信号与组合动作计划，不执行模拟成交")

            snapshot = mark_to_market(conn, latest_prices)
            from .db import write_account_snapshot  # local import to avoid cycle

            write_account_snapshot(conn, snapshot)
            portfolio_feedback = build_portfolio_feedback(conn, self.settings)
            if self._should_persist_evaluation(trade_date, phase_state.phase, execution_events):
                self.evaluation_service.persist_evaluations(conn, reference_date=trade_date)
                self._last_evaluation_trade_date = trade_date
            if self.settings.evaluation.report_auto_generate and execution_gate.can_generate_report and phase_state.phase == "POST_CLOSE" and self._last_report_trade_date != trade_date:
                self.report_service.export_daily_report(conn, trade_date)
                current_day = datetime.fromisoformat(trade_date).date()
                week_start = current_day - timedelta(days=current_day.weekday())
                self.report_service.export_weekly_report(conn, week_start.isoformat(), trade_date)
                self.report_service.export_monthly_report(conn, current_day.strftime("%Y-%m"))
                self._last_report_trade_date = trade_date
            for warning in universe_result.warnings:
                _safe_log("WARNING", "universe", warning)
            self._write_live_state(
                phase_name=phase_state.phase,
                trading_calendar={
                    "is_trading_day": phase_state.is_trading_day,
                    "trade_date": trade_date,
                    "next_trading_day": phase_state.next_trading_day,
                    "previous_trading_day": phase_state.previous_trading_day,
                },
                execution_gate=execution_gate.model_dump(),
                decision_mode=mode_state.effective_mode,
                market_regime=market_regime,
                strategy_weights=strategy_weights,
                ai_decisions=ai_decisions,
                manager_decision=manager_decision,
                feature_fusions=feature_fusions,
                decision_contexts=decision_contexts,
                engine_decisions=engine_decisions,
                compare_result=compare_result,
                planned_actions=planned_actions,
                risk_results=risk_results,
                portfolio_feedback=portfolio_feedback,
                final_signals=final_signals,
            )
            conn.commit()
            if self.logger:
                log_event(
                    self.logger,
                    "info",
                    "scheduler",
                    "cycle_completed",
                    phase=phase_state.phase,
                    trading_day=phase_state.is_trading_day,
                    decision_mode=mode_state.effective_mode,
                    candidates=len(universe_result.selected_symbols),
                    final_signals=len(final_signals),
                    orders=len(execution_events),
                )
            return {
                "trade_date": trade_date,
                "phase": phase_state.phase,
                "is_trading_day": phase_state.is_trading_day,
                "decision_mode": mode_state.effective_mode,
                "candidate_count": len(universe_result.selected_symbols),
                "final_signal_count": len(final_signals),
                "planned_action_count": len(planned_actions),
                "execution_events": execution_events,
                "warnings": universe_result.warnings,
            }
        except Exception as exc:
            _safe_log("ERROR", "scheduler", str(exc))
            try:
                conn.commit()
            except sqlite3.Error as db_exc:
                if self.logger:
                    log_event(
                        self.logger,
                        "error",
                        "scheduler",
                        "commit_failed_after_exception",
                        error=str(exc),
                        db_error=str(db_exc),
                    )
            raise
        finally:
            conn.close()

    def _build_ai_context_map(self, universe_result, grouped: Dict[str, List[StrategySignal]], portfolio) -> Dict[str, Dict[str, object]]:
        snapshot_rows = {}
        if hasattr(universe_result, "snapshot") and not universe_result.snapshot.empty:
            for _, row in universe_result.snapshot.iterrows():
                snapshot_rows[str(row["symbol"])] = {
                    "latest_price": float(row.get("latest_price") or 0.0),
                    "pct_change": float(row.get("pct_change") or 0.0),
                    "amount": float(row.get("amount") or 0.0),
                    "turnover_rate": float(row.get("turnover_rate") or 0.0),
                    "name": str(row.get("name") or row.get("symbol")),
                }
        context_map: Dict[str, Dict[str, object]] = {}
        for symbol, signals in grouped.items():
            actions: Dict[str, int] = {}
            for signal in signals:
                actions[signal.action] = actions.get(signal.action, 0) + 1
            context_map[symbol] = {
                "market_snapshot": snapshot_rows.get(symbol, {}),
                "technical_summary": {
                    "strategy_count": len(signals),
                    "actions": actions,
                    "avg_score": round(sum(signal.score for signal in signals) / max(len(signals), 1), 4),
                    "strategies": [signal.strategy for signal in signals],
                },
                "portfolio_context": {
                    "cash": portfolio.cash,
                    "equity": portfolio.equity,
                    "market_value": portfolio.market_value,
                    "has_position": symbol in portfolio.current_positions,
                    "position_qty": int(portfolio.current_positions.get(symbol, {}).get("qty", 0)),
                    "can_sell_qty": int(portfolio.current_positions.get(symbol, {}).get("can_sell_qty", 0)),
                },
                "risk_constraints": {
                    "max_single_position_pct": self.settings.max_single_position_pct,
                    "max_daily_open_position_pct": self.settings.max_daily_open_position_pct,
                    "max_drawdown_pct": self.settings.max_drawdown_pct,
                    "current_drawdown": portfolio.drawdown,
                },
            }
        return context_map

    def _write_live_state(
        self,
        phase_name: str,
        trading_calendar: Dict[str, object],
        execution_gate: Dict[str, object],
        decision_mode: str,
        market_regime: MarketRegimeState,
        strategy_weights: Dict[str, float],
        ai_decisions,
        manager_decision: PortfolioManagerDecision,
        feature_fusions,
        decision_contexts,
        engine_decisions,
        compare_result,
        planned_actions,
        risk_results,
        portfolio_feedback,
        final_signals: List[FinalSignal],
    ) -> None:
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "phase": phase_name,
            "trading_calendar": trading_calendar,
            "execution_gate": execution_gate,
            "decision_mode": decision_mode,
            "market_regime": market_regime.model_dump(),
            "strategy_weights": strategy_weights,
            "ai_reviewer": [decision.model_dump() for decision in ai_decisions],
            "ai_portfolio_manager": manager_decision.model_dump(),
            "feature_fusions": {symbol: item.model_dump() for symbol, item in feature_fusions.items()} if isinstance(feature_fusions, dict) else {},
            "decision_contexts": decision_contexts,
            "ai_decision_engine": {symbol: item.model_dump() for symbol, item in engine_decisions.items()} if isinstance(engine_decisions, dict) else {},
            "decision_compare": compare_result,
            "final_actions": [action.model_dump() for action in planned_actions],
            "risk_results": risk_results,
            "portfolio_feedback": portfolio_feedback,
            "final_signals": [signal.model_dump() for signal in final_signals],
        }
        self.settings.live_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.live_state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _should_persist_evaluation(self, trade_date: str, phase_name: str, execution_events: List[Dict[str, object]]) -> bool:
        if self._last_evaluation_trade_date != trade_date:
            return True
        if any(not bool(item.get("intent_only")) for item in execution_events):
            return True
        return phase_name in {"POST_CLOSE", "NON_TRADING_DAY"}

    def run_end_of_day_review(self) -> Dict[str, object]:
        conn = connect_db(self.settings)
        try:
            report = self.review_service.build_report(conn, datetime.now().date().isoformat())
            path = self.review_service.save_report(report, self.settings.reports_dir)
            return {"report_path": str(path), "summary": report.summary}
        finally:
            conn.close()
