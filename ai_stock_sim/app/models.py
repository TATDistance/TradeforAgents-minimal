from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Action = Literal["BUY", "SELL", "HOLD"]


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
    action: Action
    score: float
    signal_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_pct: float
    reason: str


class AIDecision(BaseModel):
    symbol: str
    ai_action: Action
    confidence: float = 0.5
    risk_score: float = 0.5
    approved: bool = True
    reason: str = ""
    source_mode: str = "disabled"


class FinalSignal(BaseModel):
    symbol: str
    action: Action
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_pct: float
    confidence: float
    source_strategies: List[str]
    ai_approved: bool = False
    ai_reason: str = ""
    strategy_reason: str = ""


class RiskCheckResult(BaseModel):
    allowed: bool
    adjusted_qty: int
    adjusted_position_pct: float
    reject_reason: Optional[str] = None
    risk_state: str = "REJECT"
    est_fee: float = 0.0
    est_tax: float = 0.0
    est_slippage: float = 0.0


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
