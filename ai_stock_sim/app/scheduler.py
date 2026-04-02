from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Mapping

from apscheduler.schedulers.background import BackgroundScheduler

from .action_planner import ActionPlanner
from .adaptive_weight_service import AdaptiveWeightService
from .ai_decision_engine import AIDecisionEngine
from .ai_portfolio_manager import AIPortfolioManager
from .decision_attribution_service import DecisionAttributionService
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
from .opportunity_pool_service import OpportunityPoolService
from .portfolio_service import build_portfolio_feedback, build_portfolio_state, mark_to_market
from .intraday_selector_service import IntradaySelectorService
from .report_service import ReportService
from .realtime_engine import RealtimeEngine
from .review_service import ReviewService
from .risk_engine import RiskEngine
from .settings import Settings, SimulationAccountConfig, get_primary_simulation_account, load_settings, resolve_simulation_accounts
from .signal_fusion import SignalFusion
from .style_profile_service import StyleProfileService
from .strategy_evaluation_service import StrategyEvaluationService
from .strategy_weight_service import StrategyWeightService
from .strategy_engine import StrategyEngine
from .trading_calendar_service import TradingCalendarService
from .universe_service import UniverseService
from .watchlist_evolution_service import WatchlistEvolutionService
from .watchlist_sync_service import load_runtime_watchlist, sync_watchlist_to_runtime


class TradingScheduler:
    REJECT_RETRY_COOLDOWN_SECONDS = 600
    NON_EXECUTABLE_BUY_MARKERS = (
        "不足 100 股",
        "买一手约需",
        "仓位上限已用尽",
    )

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
        self.strategy_evaluation_service = StrategyEvaluationService(self.settings)
        self.adaptive_weight_service = AdaptiveWeightService(self.settings, strategy_evaluation_service=self.strategy_evaluation_service)
        self.style_profile_service = StyleProfileService(self.settings)
        self.decision_attribution_service = DecisionAttributionService(self.settings)
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
        self.realtime_engine = RealtimeEngine(self.settings)
        self.intraday_selector_service = IntradaySelectorService(self.settings, market_data=self.market_data, strategy_engine=self.strategy_engine)
        self.opportunity_pool_service = OpportunityPoolService(self.settings)
        self.watchlist_evolution_service = WatchlistEvolutionService(self.settings)
        self.scheduler = BackgroundScheduler()
        self._last_t1_release_date: Dict[str, str] = {}
        self._last_evaluation_trade_date: Dict[str, str] = {}
        self._last_report_trade_date: Dict[str, str] = {}
        self._last_phase_key: Dict[str, str] = {}
        self._last_intraday_scan_at: datetime | None = None

    def start(self) -> None:
        self.scheduler.add_job(self.run_cycle, "interval", seconds=self.settings.refresh_interval_seconds, max_instances=1)
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    def run_cycle(self, account: SimulationAccountConfig | None = None) -> Dict[str, object]:
        if account is None:
            accounts = resolve_simulation_accounts(self.settings)
            if self.settings.simulation_accounts:
                primary_account = get_primary_simulation_account(self.settings)
                summaries: List[Dict[str, object]] = []
                primary_result: Dict[str, object] | None = None
                for item in accounts:
                    result = self.run_cycle(account=item)
                    summaries.append(result)
                    if item.account_id == primary_account.account_id:
                        primary_result = result
                self._write_accounts_summary(summaries)
                return primary_result or (summaries[0] if summaries else {})
            account = get_primary_simulation_account(self.settings)

        phase_state = self.market_phase_service.resolve()
        execution_gate = self.execution_gate_service.resolve(phase_state)
        trade_date = phase_state.trade_date
        mode_state = self.decision_mode_router.resolve()
        conn = connect_db(self.settings, account_id=account.account_id)
        initialize_db(self.settings, account_id=account.account_id)

        def _safe_log(level: str, module: str, message: str) -> None:
            scoped_module = f"{module}[{account.account_id}]"
            try:
                write_system_log(conn, level, scoped_module, message)
            except sqlite3.Error as exc:
                if self.logger:
                    log_event(
                        self.logger,
                        level.lower(),
                        scoped_module,
                        "db_log_failed",
                        message=message,
                        db_error=str(exc),
                    )

        try:
            phase_key = f"{trade_date}:{phase_state.phase}"
            if phase_key != self._last_phase_key.get(account.account_id):
                _safe_log("INFO", "market_phase", f"{trade_date} 阶段切换到 {phase_state.phase}：{phase_state.reason}")
                self._last_phase_key[account.account_id] = phase_key

            if phase_state.is_trading_day and self._last_t1_release_date.get(account.account_id) != trade_date:
                self.broker.release_t1_positions(conn)
                self._last_t1_release_date[account.account_id] = trade_date

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
            runtime_events = []
            trigger_decisions = []
            runtime_states = self.realtime_engine.state_store.export()
            final_signals: List[FinalSignal] = []
            ai_decisions = []
            portfolio = build_portfolio_state(conn)
            portfolio_feedback = build_portfolio_feedback(conn, self.settings)
            market_regime = self.market_regime_service.evaluate(universe_result.snapshot, portfolio_feedback)
            self.market_regime_service.save_state(market_regime)
            adaptive_weights = self.adaptive_weight_service.get_current_weights(conn)
            style_profile = self.style_profile_service.determine_style(
                market_regime.model_dump(),
                portfolio_feedback=portfolio_feedback,
                adaptive_weights=adaptive_weights,
            )
            strategy_weights = self.strategy_weight_service.resolve_weights(market_regime, portfolio_feedback)
            runtime_watchlist = load_runtime_watchlist(self.settings)
            watchlist_scan_result: Dict[str, object] = {"scan_time": "", "candidates": [], "reason": ""}
            watchlist_evolution_result: Dict[str, object] = dict(runtime_watchlist.get("watchlist_evolution") or {})
            watchlist_events: List[Dict[str, object]] = list(runtime_watchlist.get("watchlist_events") or [])
            if self._should_run_intraday_scan(phase_state.phase):
                watchlist_symbols = list(runtime_watchlist.get("symbols") or universe_result.selected_symbols)
                watchlist_scan_result = self.intraday_selector_service.scan(
                    universe_result.snapshot,
                    current_watchlist=watchlist_symbols,
                    current_positions=list(portfolio.current_positions.keys()),
                    market_regime=market_regime.model_dump(),
                )
                scan_candidates = list(watchlist_scan_result.get("candidates") or [])
                pool_result = self.opportunity_pool_service.update(scan_candidates)
                watchlist_scan_result["pool_size"] = len(pool_result.get("items") or [])
                watchlist_scan_result["source"] = "intraday_scan"
                evolution_watchlist = self.watchlist_evolution_service.evolve(
                    runtime_watchlist or {
                        "symbols": universe_result.selected_symbols,
                        "source": universe_result.data_source,
                        "generated_at": datetime.now().isoformat(timespec="seconds"),
                        "valid_until": "",
                        "trading_day": trade_date,
                    },
                    opportunity_pool=pool_result.get("items") or [],
                    runtime_states=runtime_states,
                    ai_decisions={},
                    holdings=list(portfolio.current_positions.keys()),
                )
                watchlist_evolution_result = dict(evolution_watchlist.get("evolution") or {})
                watchlist_events = self._build_watchlist_events(
                    watchlist_evolution_result,
                    watchlist_scan_result,
                    runtime_states,
                    trade_date,
                )
                evolution_watchlist["watchlist_events"] = watchlist_events
                evolution_watchlist["last_scan_at"] = str(watchlist_scan_result.get("scan_time") or "")
                runtime_watchlist = sync_watchlist_to_runtime(evolution_watchlist, self.settings)
                universe_result.selected_symbols = [
                    symbol
                    for symbol in list(runtime_watchlist.get("symbols") or [])
                    if symbol in set(universe_result.snapshot["symbol"].astype(str).tolist())
                ] or universe_result.selected_symbols
                self._last_intraday_scan_at = datetime.now()
                _safe_log(
                    "INFO",
                    "watchlist_scan",
                    json.dumps(
                        {
                            "trade_date": trade_date,
                            "phase": phase_state.phase,
                            "candidates": len(scan_candidates),
                            "added": len(watchlist_evolution_result.get("added") or []),
                            "removed": len(watchlist_evolution_result.get("removed") or []),
                            "added_symbols": list(watchlist_evolution_result.get("added") or []),
                            "removed_symbols": list(watchlist_evolution_result.get("removed") or []),
                            "watchlist_size": len(runtime_watchlist.get("symbols") or []),
                        },
                        ensure_ascii=False,
                    ),
                )
            manager_decision = PortfolioManagerDecision(portfolio_view="暂无主动组合建议", risk_mode=portfolio_feedback.get("risk_mode", "NORMAL"), actions=[])
            final_actions = []
            planned_actions = []
            risk_results: List[Dict[str, object]] = []
            if execution_gate.can_generate_signal:
                frame_map = {}
                snapshot_rows = {
                    str(row["symbol"]): {
                        "symbol": str(row["symbol"]),
                        "name": str(row.get("name") or row["symbol"]),
                        "latest_price": float(row.get("latest_price") or 0.0),
                        "pct_change": float(row.get("pct_change") or 0.0),
                        "amount": float(row.get("amount") or 0.0),
                        "turnover_rate": float(row.get("turnover_rate") or 0.0),
                        "market": str(row.get("market") or ""),
                        "asset_type": str(row.get("asset_type") or "stock"),
                    }
                    for _, row in universe_result.snapshot.iterrows()
                } if hasattr(universe_result, "snapshot") and not universe_result.snapshot.empty else {}
                engine_symbols = list(universe_result.selected_symbols)

                if mode_state.run_legacy:
                    legacy_symbols = list(universe_result.selected_symbols)
                    if self.settings.runtime.engine_mode == "event_driven_mode":
                        event_preview = self.realtime_engine.select_symbols_for_cycle(
                            symbols=universe_result.selected_symbols,
                            snapshot_rows=snapshot_rows,
                            feature_scores={},
                            market_regime=market_regime.regime,
                            portfolio_feedback=portfolio_feedback,
                            phase_name=phase_state.phase,
                        )
                        runtime_events = event_preview.get("events") or []
                        trigger_decisions = event_preview.get("trigger_decisions") or []
                        runtime_states = event_preview.get("runtime_states") or runtime_states
                        self._log_trigger_decisions(_safe_log, trigger_decisions, phase_state.phase, market_regime.regime)
                        changed = list(event_preview.get("changed_symbols") or [])
                        if changed:
                            legacy_symbols = changed
                            engine_symbols = changed
                        else:
                            legacy_symbols = []
                            engine_symbols = []
                    grouped = self.strategy_engine.run_batch(legacy_symbols, asset_type_map=asset_type_map) if legacy_symbols else {}
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
                        for symbol in engine_symbols
                    }
                    feature_map = {
                        symbol: self.strategy_engine.run_features_for_symbol_on_frame(symbol, frame)
                        for symbol, frame in frame_map.items()
                    }
                    feature_fusions = self.signal_fusion.fuse_features(
                        feature_map,
                        strategy_weights=strategy_weights,
                        market_regime=market_regime,
                        portfolio_feedback=portfolio_feedback,
                    )
                    if self.settings.runtime.engine_mode == "event_driven_mode" and not trigger_decisions:
                        event_result = self.realtime_engine.select_symbols_for_cycle(
                            symbols=engine_symbols,
                            snapshot_rows=snapshot_rows,
                            feature_scores={symbol: item.model_dump() for symbol, item in feature_fusions.items()},
                            market_regime=market_regime.regime,
                            portfolio_feedback=portfolio_feedback,
                            phase_name=phase_state.phase,
                        )
                        runtime_events = event_result.get("events") or []
                        trigger_decisions = event_result.get("trigger_decisions") or []
                        runtime_states = event_result.get("runtime_states") or runtime_states
                        self._log_trigger_decisions(_safe_log, trigger_decisions, phase_state.phase, market_regime.regime)
                        changed = list(event_result.get("changed_symbols") or [])
                        if changed:
                            engine_symbols = changed
                            frame_map = {symbol: frame_map[symbol] for symbol in changed if symbol in frame_map}
                            feature_map = {symbol: feature_map[symbol] for symbol in changed if symbol in feature_map}
                            feature_fusions = {symbol: feature_fusions[symbol] for symbol in changed if symbol in feature_fusions}
                        else:
                            engine_symbols = []
                            frame_map = {}
                            feature_map = {}
                            feature_fusions = {}
                    decision_contexts = self.decision_context_builder.build_batch(
                        engine_symbols,
                        snapshot_rows,
                        feature_map,
                        frame_map,
                        market_regime,
                        portfolio_feedback,
                        phase_state,
                        execution_gate,
                        adaptive_weights=adaptive_weights,
                        style_profile=style_profile.model_dump(),
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
                    self._log_engine_decisions(_safe_log, engine_decisions, phase_state.phase)
                    for symbol, decision in engine_decisions.items():
                        position_detail = next(
                            (
                                item for item in (portfolio_feedback.get("positions_detail") or [])
                                if isinstance(item, Mapping) and str(item.get("symbol")) == symbol
                            ),
                            {},
                        )
                        self.realtime_engine.state_store.update_scores(
                            symbol,
                            feature_score=decision.feature_score,
                            setup_score=decision.setup_score,
                            execution_score=decision.execution_score,
                            ai_score=decision.ai_score,
                            ai_action=decision.action,
                            position_qty=int(position_detail.get("qty", 0) or 0) if isinstance(position_detail, Mapping) else 0,
                            cash_pct=float(portfolio_feedback.get("cash_pct", 0.0) or 0.0),
                        )
                        if str(decision.action) != "HOLD" or float(decision.setup_score or 0.0) >= self.settings.scoring.min_setup_score_to_watch:
                            self.decision_attribution_service.record_decision_snapshot(
                                conn,
                                context=decision_contexts.get(symbol) or {"symbol": symbol},
                                action=decision.model_dump(),
                                market_regime=market_regime.regime,
                                style_profile=style_profile.style,
                            )
                    runtime_states = self.realtime_engine.state_store.export()
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

            self._persist_intraday_points(quote_map, trade_date)

            planned_actions = self.action_planner.plan(final_actions, portfolio_feedback, latest_prices, phase_state, execution_gate)
            execution_events: List[Dict[str, object]] = []
            if execution_gate.can_execute_fill or execution_gate.intent_only_mode:
                for action in planned_actions:
                    if action.symbol == "*":
                        _safe_log("INFO", "ai_pm", action.reason)
                        continue
                    reject_reason = self._recent_reject_reason(action.symbol, action.action)
                    if reject_reason:
                        _safe_log("INFO", "portfolio_decision", f"{action.symbol} BUY 冷却中: {reject_reason}")
                        risk_results.append(
                            {
                                "symbol": action.symbol,
                                "action": action.action,
                                "mode_name": action.mode_name,
                                "phase": action.phase,
                                "intent_only": action.intent_only,
                                "executable_now": False,
                                "allowed": False,
                                "final_action": "HOLD",
                                "adjusted_qty": 0,
                                "risk_state": "COOLDOWN",
                                "phase_blocked": False,
                                "reason": reject_reason,
                            }
                        )
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
                    if not risk.allowed and action.action == "BUY":
                        self.realtime_engine.state_store.mark_reject(
                            action.symbol,
                            action=action.action,
                            reason=risk.reject_reason or action.reason,
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
            self.decision_attribution_service.backfill_trade_results(conn, lookback_days=max(3, int(self.settings.adaptive.evaluation_window_days or 5)))
            if self._should_persist_evaluation(account.account_id, trade_date, phase_state.phase, execution_events):
                self.evaluation_service.persist_evaluations(conn, reference_date=trade_date)
                self._last_evaluation_trade_date[account.account_id] = trade_date
            adaptive_update = adaptive_weights
            if phase_state.phase == "POST_CLOSE" and self.settings.adaptive.enabled:
                adaptive_update = self.adaptive_weight_service.update_strategy_weights(conn)
                style_profile = self.style_profile_service.determine_style(
                    market_regime.model_dump(),
                    portfolio_feedback=portfolio_feedback,
                    adaptive_weights=adaptive_update,
                )
                self.style_profile_service.save(conn, style_profile)
            elif phase_state.phase in {"CONTINUOUS_AUCTION_AM", "CONTINUOUS_AUCTION_PM"} and datetime.now().minute == 0:
                style_profile = self.style_profile_service.determine_style(
                    market_regime.model_dump(),
                    portfolio_feedback=portfolio_feedback,
                    adaptive_weights=adaptive_weights,
                )
                self.style_profile_service.save(conn, style_profile)
            if self.settings.evaluation.report_auto_generate and execution_gate.can_generate_report and phase_state.phase == "POST_CLOSE" and self._last_report_trade_date.get(account.account_id) != trade_date:
                self.report_service.export_daily_report(conn, trade_date)
                current_day = datetime.fromisoformat(trade_date).date()
                week_start = current_day - timedelta(days=current_day.weekday())
                self.report_service.export_weekly_report(conn, week_start.isoformat(), trade_date)
                self.report_service.export_monthly_report(conn, current_day.strftime("%Y-%m"))
                self._last_report_trade_date[account.account_id] = trade_date
            for warning in universe_result.warnings:
                _safe_log("WARNING", "universe", warning)
            self._write_live_state(
                account_id=account.account_id,
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
                runtime_events=runtime_events,
                trigger_decisions=trigger_decisions,
                runtime_states=runtime_states,
                planned_actions=planned_actions,
                risk_results=risk_results,
                portfolio_feedback=portfolio_feedback,
                adaptive_weights=adaptive_update,
                style_profile=style_profile.model_dump(),
                strategy_performance=self.strategy_evaluation_service.evaluate_strategy_performance(
                    conn,
                    window_days=min(3, int(self.settings.adaptive.evaluation_window_days or 5)),
                ),
                bad_decisions=self.decision_attribution_service.analyze_bad_decisions(conn, limit=10),
                final_signals=final_signals,
                runtime_watchlist=runtime_watchlist,
                watchlist_scan_result=watchlist_scan_result,
                watchlist_evolution_result=watchlist_evolution_result,
                watchlist_events=watchlist_events,
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
                    engine_mode=self.settings.runtime.engine_mode,
                    candidates=len(universe_result.selected_symbols),
                    changed_symbols=len(engine_symbols) if execution_gate.can_generate_signal else 0,
                    final_signals=len(final_signals),
                    orders=len(execution_events),
                )
            return {
                "account_id": account.account_id,
                "account_name": account.name,
                "trade_date": trade_date,
                "phase": phase_state.phase,
                "is_trading_day": phase_state.is_trading_day,
                "decision_mode": mode_state.effective_mode,
                "engine_mode": self.settings.runtime.engine_mode,
                "candidate_count": len(universe_result.selected_symbols),
                "changed_symbol_count": len(engine_symbols) if execution_gate.can_generate_signal else 0,
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

    @staticmethod
    def _log_trigger_decisions(_safe_log, trigger_decisions: List[Dict[str, object]], phase_name: str, regime_name: str) -> None:
        for item in trigger_decisions:
            if not bool(item.get("triggered")):
                continue
            payload = {
                "symbol": str(item.get("symbol") or ""),
                "phase": phase_name,
                "regime": regime_name,
                "reasons": list(item.get("reasons") or []),
                "cooldown_blocked": bool(item.get("cooldown_blocked")),
            }
            _safe_log("INFO", "trigger", json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _log_engine_decisions(_safe_log, engine_decisions: Mapping[str, object], phase_name: str) -> None:
        for symbol, decision in (engine_decisions or {}).items():
            payload = {
                "symbol": symbol,
                "phase": phase_name,
                "action": getattr(decision, "action", "HOLD"),
                "setup_score": round(float(getattr(decision, "setup_score", 0.0) or 0.0), 6),
                "execution_score": round(float(getattr(decision, "execution_score", 0.0) or 0.0), 6),
                "ai_score": round(float(getattr(decision, "ai_score", 0.0) or 0.0), 6),
                "confidence": round(float(getattr(decision, "confidence", 0.0) or 0.0), 6),
                "risk_mode": str(getattr(decision, "risk_mode", "NORMAL")),
            }
            _safe_log("INFO", "decision_engine", json.dumps(payload, ensure_ascii=False))

    def _write_live_state(
        self,
        account_id: str,
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
        runtime_events,
        trigger_decisions,
        runtime_states,
        planned_actions,
        risk_results,
        portfolio_feedback,
        adaptive_weights: Dict[str, object],
        style_profile: Dict[str, object],
        strategy_performance: Dict[str, object],
        bad_decisions: List[Dict[str, object]],
        final_signals: List[FinalSignal],
        runtime_watchlist: Dict[str, object],
        watchlist_scan_result: Dict[str, object],
        watchlist_evolution_result: Dict[str, object],
        watchlist_events: List[Dict[str, object]],
    ) -> None:
        payload = {
            "account_id": account_id,
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
            "engine_mode": self.settings.runtime.engine_mode,
            "runtime_events": runtime_events,
            "trigger_decisions": trigger_decisions,
            "runtime_states": runtime_states,
            "final_actions": [action.model_dump() for action in planned_actions],
            "risk_results": risk_results,
            "portfolio_feedback": portfolio_feedback,
            "adaptive_weights": adaptive_weights,
            "style_profile": style_profile,
            "strategy_performance": strategy_performance,
            "bad_decisions": bad_decisions,
            "final_signals": [signal.model_dump() for signal in final_signals],
            "runtime_watchlist": runtime_watchlist,
            "watchlist_scan": watchlist_scan_result,
            "watchlist_evolution": watchlist_evolution_result,
            "watchlist_events": watchlist_events,
        }
        target_path = self.settings.resolved_account_live_state_path(account_id)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        target_path.write_text(content, encoding="utf-8")
        if account_id == get_primary_simulation_account(self.settings).account_id:
            self.settings.live_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings.live_state_path.write_text(content, encoding="utf-8")

    def _write_accounts_summary(self, summaries: List[Dict[str, object]]) -> None:
        primary_account = get_primary_simulation_account(self.settings)
        primary_path = self.settings.account_live_state_path(primary_account.account_id)
        if primary_path.exists():
            try:
                payload = json.loads(primary_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        else:
            payload = {}
        payload["accounts_summary"] = summaries
        self.settings.live_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.live_state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _persist_intraday_points(
        self,
        quote_map: Mapping[str, object],
        trade_date: str,
    ) -> None:
        chart_dir = self.settings.cache_dir / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="seconds")
        for symbol, quote in quote_map.items():
            latest_price = float(getattr(quote, "latest_price", 0.0) or 0.0)
            if latest_price <= 0:
                continue
            path = chart_dir / f"intraday_{symbol}_{trade_date}.json"
            existing = {"symbol": symbol, "trade_date": trade_date, "points": []}
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    existing = {"symbol": symbol, "trade_date": trade_date, "points": []}
            points = list(existing.get("points") or [])
            point = {
                "ts": ts,
                "price": latest_price,
                "pct_change": float(getattr(quote, "pct_change", 0.0) or 0.0),
                "amount": float(getattr(quote, "amount", 0.0) or 0.0),
            }
            if points and str(points[-1].get("ts") or "") == point["ts"]:
                points[-1] = point
            else:
                points.append(point)
            existing["points"] = points[-300:]
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def _should_run_intraday_scan(self, phase_name: str) -> bool:
        if not self.settings.watchlist_evolution.enabled:
            return False
        if phase_name not in {"CONTINUOUS_AUCTION_AM", "CONTINUOUS_AUCTION_PM"}:
            return False
        if self._last_intraday_scan_at is None:
            return True
        interval = timedelta(minutes=int(self.settings.watchlist_evolution.scan_interval_minutes or 30))
        return datetime.now() - self._last_intraday_scan_at >= interval

    def _recent_reject_reason(self, symbol: str, action: str) -> str | None:
        if action != "BUY":
            return None
        state = self.realtime_engine.state_store.get(symbol)
        if state is None or state.last_reject_action != "BUY" or not state.last_reject_at:
            return None
        reason = str(state.last_reject_reason or "")
        if not any(marker in reason for marker in self.NON_EXECUTABLE_BUY_MARKERS):
            return None
        try:
            rejected_at = datetime.fromisoformat(str(state.last_reject_at))
        except Exception:
            return None
        if (datetime.now() - rejected_at).total_seconds() > self.REJECT_RETRY_COOLDOWN_SECONDS:
            return None
        return f"{reason}；系统将在冷却后再尝试，避免连续重复下单"

    @staticmethod
    def _build_watchlist_events(
        evolution: Mapping[str, object],
        scan_result: Mapping[str, object],
        runtime_states: Mapping[str, Mapping[str, object]],
        trade_date: str,
    ) -> List[Dict[str, object]]:
        updated_at = str(evolution.get("updated_at") or scan_result.get("scan_time") or datetime.now().isoformat(timespec="seconds"))
        reason_summary = evolution.get("reason_summary") or {}
        events: List[Dict[str, object]] = []
        for symbol in evolution.get("added") or []:
            events.append(
                {
                    "ts": updated_at,
                    "symbol": symbol,
                    "action": "ADD",
                    "reason": str(reason_summary.get(symbol) or "盘中动态扫描发现强势新机会，加入监控池"),
                    "trade_date": trade_date,
                }
            )
        for symbol in evolution.get("removed") or []:
            state = dict(runtime_states.get(symbol) or {})
            fallback_reason = "长期低分且无持仓，移出监控池"
            if state.get("last_setup_score") or state.get("last_execution_score"):
                fallback_reason = "长期低分且近期无动作，暂时移出监控池"
            events.append(
                {
                    "ts": updated_at,
                    "symbol": symbol,
                    "action": "REMOVE",
                    "reason": str(reason_summary.get(symbol) or fallback_reason),
                    "trade_date": trade_date,
                }
            )
        return events[:20]

    def _should_persist_evaluation(self, account_id: str, trade_date: str, phase_name: str, execution_events: List[Dict[str, object]]) -> bool:
        if self._last_evaluation_trade_date.get(account_id) != trade_date:
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
