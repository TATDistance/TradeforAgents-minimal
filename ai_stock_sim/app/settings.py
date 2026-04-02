from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv


@dataclass
class StrategyConfig:
    momentum_lookback: int = 20
    momentum_min_score: float = 0.55
    dual_ma_fast_window: int = 10
    dual_ma_slow_window: int = 30
    macd_fast_window: int = 12
    macd_slow_window: int = 26
    macd_signal_window: int = 9
    mean_reversion_rsi_low: float = 30.0
    mean_reversion_boll_window: int = 20
    breakout_window: int = 20
    atr_window: int = 14
    trend_pullback_fast_window: int = 20
    trend_pullback_slow_window: int = 60
    trend_pullback_max_distance_pct: float = 0.03


@dataclass
class AIConfig:
    approval_confidence_floor: float = 0.58
    low_confidence_scale: float = 0.5
    request_timeout_seconds: int = 120


@dataclass
class PathConfig:
    tradeforagents_results_dir: str = "../results"
    tradeforagents_script: str = "../scripts/run_minimal_deepseek.sh"
    vnpy_workspace: str = "external/vnpy_workspace"


@dataclass
class MarketSessionConfig:
    timezone: str = "Asia/Shanghai"
    trade_start: str = "09:30"
    lunch_start: str = "11:30"
    lunch_end: str = "13:00"
    trade_end: str = "15:00"
    post_close_analysis_start: str = "15:05"
    post_close_analysis_end: str = "18:00"
    enable_weekend_guard: bool = True
    allow_post_close_paper_execution: bool = False


@dataclass
class TradingCalendarConfig:
    enabled: bool = True
    timezone: str = "Asia/Shanghai"
    calendar_source: str = "local_file"
    calendar_file: str = "data/calendars/cn_a_2026.json"


@dataclass
class MarketPhaseConfig:
    enabled: bool = True
    pre_open_start: str = "09:00:00"
    open_call_start: str = "09:15:00"
    open_call_end: str = "09:25:00"
    am_continuous_start: str = "09:30:00"
    am_continuous_end: str = "11:30:00"
    midday_start: str = "11:30:00"
    midday_end: str = "13:00:00"
    pm_continuous_start: str = "13:00:00"
    pm_continuous_end: str = "14:57:00"
    closing_call_start: str = "14:57:00"
    closing_call_end: str = "15:00:00"


@dataclass
class ExecutionGateConfig:
    block_new_buy_in_closing_call: bool = True
    block_all_fill_outside_continuous_auction: bool = True
    allow_post_close_analysis: bool = True


@dataclass
class CacheConfig:
    snapshot_ttl_seconds: int = 8
    quote_ttl_seconds: int = 8
    history_market_hours_ttl_seconds: int = 1800
    history_off_hours_ttl_seconds: int = 21600


@dataclass
class EvaluationConfig:
    rolling_trade_windows: List[int] = field(default_factory=lambda: [20, 50])
    rolling_day_windows: List[int] = field(default_factory=lambda: [20, 60])
    enable_strategy_scoring: bool = True
    report_auto_generate: bool = True


@dataclass
class ScoringConfig:
    weight_return: float = 0.30
    weight_risk: float = 0.30
    weight_stability: float = 0.20
    weight_execution: float = 0.20
    min_setup_score_to_watch: float = 0.35
    min_execution_score_to_buy: float = 0.55
    min_execution_score_to_reduce: float = 0.45


@dataclass
class DashboardConfig:
    auto_refresh_seconds: int = 10
    enable_log_filter: bool = True
    enable_mode_comparison: bool = True


@dataclass
class MarketRegimeConfig:
    enabled: bool = True
    default_regime: str = "RANGE_BOUND"


@dataclass
class StrategyWeightConfig:
    enabled: bool = True
    dynamic_adjustment: bool = True


@dataclass
class AIPortfolioManagerConfig:
    enabled: bool = True
    default_risk_mode: str = "NORMAL"
    allow_reduce_actions: bool = True
    allow_sell_actions: bool = True
    allow_new_buy_actions: bool = True


@dataclass
class PortfolioFeedbackConfig:
    enabled: bool = True
    drawdown_defensive_threshold: float = 0.03
    drawdown_risk_off_threshold: float = 0.05
    high_position_threshold: float = 0.7


@dataclass
class FusionConfig:
    use_weighted_scoring: bool = True
    min_final_score_to_buy: float = 0.65
    min_final_score_to_sell: float = 0.58


@dataclass
class DecisionEngineConfig:
    enabled: bool = True
    mode: str = "ai_decision_engine_mode"
    use_decision_json_as_research_cache: bool = True
    fallback_to_legacy_mode_on_failure: bool = True
    lightweight_realtime_ai: bool = True


@dataclass
class FeatureLayerConfig:
    use_strategy_scores: bool = True
    use_market_regime: bool = True
    use_portfolio_state: bool = True
    use_position_state: bool = True


@dataclass
class CompareModeConfig:
    enabled: bool = True
    record_mode_differences: bool = True


@dataclass
class RuntimeConfig:
    engine_mode: str = "event_driven_mode"


@dataclass
class TriggerConfig:
    price_change_threshold_pct: float = 0.003
    pct_change_delta_threshold: float = 0.003
    amount_delta_threshold: float = 0.20
    feature_score_delta_threshold: float = 0.08
    portfolio_state_delta_threshold: float = 0.05
    cooldown_seconds: int = 20
    stale_refresh_seconds: int = 120


@dataclass
class WatchlistConfig:
    enable_auto_refresh_on_start: bool = True
    use_recent_candidates_as_fallback: bool = True
    use_default_watchlist_as_last_resort: bool = True


@dataclass
class WatchlistEvolutionConfig:
    enabled: bool = True
    scan_interval_minutes: int = 30
    max_watchlist_size: int = 30
    max_new_symbols_per_scan: int = 10
    max_remove_symbols_per_scan: int = 5
    min_score_to_add: float = 0.55
    min_score_to_keep: float = 0.30
    grace_period_minutes: int = 60


@dataclass
class UIConfig:
    default_page: str = "ai_home"
    enable_research_center: bool = True
    enable_debug_panel: bool = True
    show_intraday_chart: bool = True
    show_kline_chart: bool = True
    show_equity_curve: bool = True
    show_action_timeline: bool = True
    default_symbol_selection_mode: str = "priority_based"


@dataclass
class Settings:
    project_root: Path
    initial_cash: float = 100000.0
    refresh_interval_seconds: int = 10
    scan_limit: int = 200
    strategy_candidate_limit: int = 20
    max_single_position_pct: float = 0.20
    max_daily_open_position_pct: float = 0.40
    max_drawdown_pct: float = 0.08
    commission_rate: float = 0.0003
    stamp_duty_rate: float = 0.0005
    slippage_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    ai_mode: str = "quick"
    enable_ai: bool = True
    use_eastmoney_realtime: bool = True
    min_turnover: float = 50_000_000.0
    min_listing_days: int = 120
    limit_up_filter_pct: float = 0.097
    limit_down_filter_pct: float = -0.097
    dashboard_refresh_seconds: int = 5
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    market_session: MarketSessionConfig = field(default_factory=MarketSessionConfig)
    trading_calendar: TradingCalendarConfig = field(default_factory=TradingCalendarConfig)
    market_phase: MarketPhaseConfig = field(default_factory=MarketPhaseConfig)
    execution_gate: ExecutionGateConfig = field(default_factory=ExecutionGateConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    market_regime: MarketRegimeConfig = field(default_factory=MarketRegimeConfig)
    strategy_weights: StrategyWeightConfig = field(default_factory=StrategyWeightConfig)
    ai_portfolio_manager: AIPortfolioManagerConfig = field(default_factory=AIPortfolioManagerConfig)
    portfolio_feedback: PortfolioFeedbackConfig = field(default_factory=PortfolioFeedbackConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    decision_engine: DecisionEngineConfig = field(default_factory=DecisionEngineConfig)
    feature_layer: FeatureLayerConfig = field(default_factory=FeatureLayerConfig)
    compare_mode: CompareModeConfig = field(default_factory=CompareModeConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    watchlist: WatchlistConfig = field(default_factory=WatchlistConfig)
    watchlist_evolution: WatchlistEvolutionConfig = field(default_factory=WatchlistEvolutionConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def calendars_dir(self) -> Path:
        return self.data_dir / "calendars"

    @property
    def live_state_path(self) -> Path:
        return self.cache_dir / "live_decision_state.json"

    @property
    def trading_calendar_file(self) -> Path:
        return (self.project_root / self.trading_calendar.calendar_file).resolve()

    @property
    def tradeforagents_results_dir(self) -> Path:
        return (self.project_root / self.paths.tradeforagents_results_dir).resolve()

    @property
    def tradeforagents_script(self) -> Path:
        return (self.project_root / self.paths.tradeforagents_script).resolve()

    @property
    def vnpy_workspace(self) -> Path:
        return (self.project_root / self.paths.vnpy_workspace).resolve()


@dataclass
class SymbolConfig:
    stock_watchlist: List[str]
    etf_watchlist: List[str]
    blacklist: List[str]
    include_stocks: bool
    include_etfs: bool


def load_symbol_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        # Use BaseLoader to preserve stock codes like 002155 as strings.
        return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or {}
    except Exception:
        return {}


def _normalize_symbol_list(values: List[Any]) -> List[str]:
    symbols: List[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if text.isdigit():
            if len(text) == 6:
                symbols.append(text)
                continue
            # Ignore malformed numeric symbols rather than leaking broken codes to UI/runtime.
            continue
        symbols.append(text)
    return list(dict.fromkeys(symbols))


def _merge_dataclass(instance: Any, payload: Dict[str, Any]) -> Any:
    for key, value in payload.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(instance, key, value)
    return instance


def load_settings(project_root: Path | None = None) -> Settings:
    root = project_root or Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
    settings_path = os.getenv("AI_STOCK_SIM_SETTINGS", "config/settings.yaml")
    settings_file = (root / settings_path).resolve()
    payload: Dict[str, Any] = {}
    if settings_file.exists():
        payload = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    settings = Settings(project_root=root)
    _merge_dataclass(settings, payload)
    if settings.dashboard.auto_refresh_seconds:
        settings.dashboard_refresh_seconds = settings.dashboard.auto_refresh_seconds
    return settings


def load_symbol_config(project_root: Path | None = None) -> SymbolConfig:
    root = project_root or Path(__file__).resolve().parents[1]
    symbols_path = os.getenv("AI_STOCK_SIM_SYMBOLS", "config/symbols.yaml")
    symbols_file = (root / symbols_path).resolve()
    payload: Dict[str, Any] = load_symbol_yaml(symbols_file)
    runtime_symbols_file = (root / "config" / "runtime_symbols.yaml").resolve()
    if runtime_symbols_file.exists():
        runtime_payload = load_symbol_yaml(runtime_symbols_file)
        watchlist_payload = runtime_payload.get("watchlist") or {}
        if watchlist_payload:
            payload["watchlist"] = watchlist_payload
        if runtime_payload.get("blacklist") is not None:
            payload["blacklist"] = runtime_payload.get("blacklist")
        if runtime_payload.get("universe") is not None:
            payload["universe"] = runtime_payload.get("universe")

    watchlist = payload.get("watchlist") or {}
    universe = payload.get("universe") or {}
    return SymbolConfig(
        stock_watchlist=_normalize_symbol_list(list(watchlist.get("stocks", []))),
        etf_watchlist=_normalize_symbol_list(list(watchlist.get("etfs", []))),
        blacklist=_normalize_symbol_list(list(payload.get("blacklist", []))),
        include_stocks=bool(universe.get("include_stocks", True)),
        include_etfs=bool(universe.get("include_etfs", True)),
    )
