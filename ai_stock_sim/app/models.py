from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SignalAction = Literal["BUY", "SELL", "HOLD"]
PortfolioActionType = Literal[
    "BUY",
    "SELL",
    "REDUCE",
    "HOLD",
    "AVOID_NEW_BUY",
    "ENTER_DEFENSIVE_MODE",
    "WATCH_NEXT_DAY",
    "PREPARE_BUY",
    "PREPARE_REDUCE",
    "HOLD_FOR_TOMORROW",
]
StrategyDirection = Literal["LONG", "SHORT", "NEUTRAL"]


class MarketQuote(BaseModel):
    ts: datetime
    symbol: str
    name: str
    market: str
    asset_type: Literal["stock", "etf"] = "stock"
    latest_price: float
    pct_change: float
    open_price: float
    high_price: float
    low_price: float
    prev_close: float
    volume: float
    amount: float
    turnover_rate: float = 0.0
    is_st: bool = False
    data_source: str


class StrategySignal(BaseModel):
    symbol: str
    strategy: str
    action: SignalAction
    score: float
    signal_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_pct: float
    reason: str


class StrategyFeature(BaseModel):
    symbol: str
    strategy_name: str
    score: float
    direction: StrategyDirection
    strength: float
    reason: str = ""
    features: Dict[str, float] = Field(default_factory=dict)


class FeatureFusionScore(BaseModel):
    symbol: str
    feature_score: float = 0.0
    dominant_direction: StrategyDirection = "NEUTRAL"
    ai_decision_score: float = 0.0
    risk_penalty: float = 0.0
    final_score: float = 0.0
    final_action: PortfolioActionType = "HOLD"
    feature_breakdown: Dict[str, float] = Field(default_factory=dict)
    summary: str = ""


class AIDecision(BaseModel):
    symbol: str
    ai_action: SignalAction
    confidence: float = 0.5
    risk_score: float = 0.5
    approved: bool = True
    reason: str = ""
    source_mode: str = "disabled"
    context_json: Optional[str] = None
    context_summary: str = ""


class FinalSignal(BaseModel):
    symbol: str
    action: SignalAction
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_pct: float
    confidence: float
    source_strategies: List[str]
    ai_approved: bool = False
    ai_reason: str = ""
    strategy_reason: str = ""
    strategy_name: str = ""
    mode_name: str = "strategy_plus_ai_plus_risk"
    weighted_score: float = 0.0
    risk_penalty: float = 0.0


class MarketRegimeState(BaseModel):
    regime: str
    confidence: float = 0.5
    reason: str = ""
    risk_bias: str = "NORMAL"
    breadth: float = 0.0
    volatility: float = 0.0


class MarketPhaseState(BaseModel):
    is_trading_day: bool
    phase: str
    allow_market_update: bool = False
    allow_signal_generation: bool = False
    allow_ai_decision: bool = False
    allow_new_buy: bool = False
    allow_sell_reduce: bool = False
    allow_simulate_fill: bool = False
    allow_post_close_analysis: bool = False
    allow_report_generation: bool = False
    reason: str = ""
    trade_date: str = ""
    next_trading_day: Optional[str] = None
    previous_trading_day: Optional[str] = None


class ExecutionGateState(BaseModel):
    can_update_market: bool = False
    can_generate_signal: bool = False
    can_run_ai_decision: bool = False
    can_plan_actions: bool = False
    can_open_position: bool = False
    can_reduce_position: bool = False
    can_execute_fill: bool = False
    can_generate_report: bool = False
    can_mark_to_market: bool = True
    intent_only_mode: bool = False
    reason: str = ""
    phase: str = ""
    is_trading_day: bool = False


class PortfolioManagerAction(BaseModel):
    symbol: str
    action: PortfolioActionType
    position_pct: float = 0.0
    reduce_pct: float = 0.0
    reason: str = ""
    priority: float = 0.0
    source: List[str] = Field(default_factory=list)
    mode_name: str = "legacy_review_mode"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PortfolioManagerDecision(BaseModel):
    portfolio_view: str = ""
    risk_mode: str = "NORMAL"
    actions: List[PortfolioManagerAction] = Field(default_factory=list)
    reason: str = ""


class PlannedAction(BaseModel):
    symbol: str
    action: PortfolioActionType
    planned_qty: int = 0
    planned_price: float = 0.0
    estimated_cost: float = 0.0
    position_pct: float = 0.0
    reduce_pct: float = 0.0
    priority: float = 0.0
    source: List[str] = Field(default_factory=list)
    mode_name: str = "legacy_review_mode"
    reason: str = ""
    intent_only: bool = False
    executable_now: bool = False
    phase: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RiskCheckResult(BaseModel):
    allowed: bool
    adjusted_qty: int
    adjusted_position_pct: float
    reject_reason: Optional[str] = None
    risk_state: str = "REJECT"
    final_action: PortfolioActionType = "HOLD"
    risk_mode: str = "NORMAL"
    est_fee: float = 0.0
    est_tax: float = 0.0
    est_slippage: float = 0.0
    phase_blocked: bool = False


class OrderRecord(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float
    qty: int
    fee: float = 0.0
    tax: float = 0.0
    slippage: float = 0.0
    status: str = "PENDING"
    ts: datetime = Field(default_factory=datetime.now)
    note: str = ""
    strategy_name: str = ""
    mode_name: str = "strategy_plus_ai_plus_risk"
    signal_id: Optional[int] = None
    intent_only: bool = False
    phase: str = ""


class PositionRecord(BaseModel):
    symbol: str
    qty: int
    avg_cost: float
    last_price: float
    market_value: float
    unrealized_pnl: float
    can_sell_qty: int
    updated_at: datetime


class AccountSnapshot(BaseModel):
    ts: datetime = Field(default_factory=datetime.now)
    cash: float
    equity: float
    market_value: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float


class ReviewReport(BaseModel):
    trade_date: str
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    ending_equity: float
    summary: str


class StrategyEvaluation(BaseModel):
    ts: datetime = Field(default_factory=datetime.now)
    strategy_name: str
    period_type: str
    total_return: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    win_rate: float = 0.0
    pnl_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    return_drawdown_ratio: float = 0.0
    monthly_positive_ratio: float = 0.0
    recent_win_rate: float = 0.0
    recent_profit_factor: float = 0.0
    recent_expectancy: float = 0.0
    score_total: float = 0.0
    score_return: float = 0.0
    score_risk: float = 0.0
    score_stability: float = 0.0
    score_execution: float = 0.0
    grade: str = "D"
    status: str = "OBSERVE"
    total_trades: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    metadata_json: Optional[str] = None


class ModeComparison(BaseModel):
    ts: datetime = Field(default_factory=datetime.now)
    mode_name: str
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    score_total: float = 0.0
    metadata_json: Optional[str] = None


class ManualExecutionLog(BaseModel):
    ts: datetime = Field(default_factory=datetime.now)
    signal_id: int
    symbol: str
    executed: bool
    actual_price: Optional[float] = None
    actual_qty: Optional[int] = None
    reason: str = ""
    note: str = ""
