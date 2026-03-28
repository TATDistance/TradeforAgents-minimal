from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .models import FinalSignal, MarketQuote, PlannedAction, RiskCheckResult
from .settings import Settings, load_settings


BOARD_LOT = 100


@dataclass
class PortfolioState:
    cash: float
    equity: float
    market_value: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float
    current_positions: Dict[str, Dict[str, float]]
    today_open_ratio: float = 0.0


class RiskEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def evaluate(self, signal: FinalSignal, quote: MarketQuote, portfolio: PortfolioState) -> RiskCheckResult:
        if portfolio.drawdown >= self.settings.max_drawdown_pct:
            return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="最大回撤熔断已触发", risk_state="REJECT", final_action="HOLD", risk_mode="RISK_OFF")

        if quote.amount < self.settings.min_turnover:
            return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="流动性不足", risk_state="REJECT", final_action="HOLD")

        if quote.pct_change >= self.settings.limit_up_filter_pct:
            return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="接近涨停，禁止追高", risk_state="REJECT", final_action="BUY")

        if quote.pct_change <= self.settings.limit_down_filter_pct and signal.action == "SELL":
            return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="接近跌停，卖出成交风险过高", risk_state="REJECT", final_action="SELL")

        current_value = float(portfolio.current_positions.get(signal.symbol, {}).get("market_value", 0.0))
        single_cap = max(0.0, portfolio.equity * self.settings.max_single_position_pct - current_value)
        daily_cap = max(0.0, portfolio.equity * self.settings.max_daily_open_position_pct - portfolio.today_open_ratio * portfolio.equity)
        target_value = min(portfolio.equity * signal.position_pct, single_cap, daily_cap, portfolio.cash)
        if signal.action == "SELL":
            can_sell_qty = int(portfolio.current_positions.get(signal.symbol, {}).get("can_sell_qty", 0))
            if can_sell_qty <= 0:
                return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="T+1 限制，可卖数量为 0", risk_state="REJECT", final_action="SELL")
            return RiskCheckResult(allowed=True, adjusted_qty=self._lot_round_down(can_sell_qty), adjusted_position_pct=1.0, risk_state="ALLOW", final_action="SELL")

        if target_value <= 0:
            return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="仓位上限已用尽", risk_state="REJECT", final_action="BUY")

        raw_qty = int(target_value / max(signal.entry_price, 0.01))
        qty = self._lot_round_down(raw_qty)
        if qty <= 0:
            return RiskCheckResult(allowed=False, adjusted_qty=0, adjusted_position_pct=0.0, reject_reason="不足 100 股", risk_state="REJECT", final_action="BUY")

        turnover = qty * signal.entry_price
        fee = turnover * self.settings.commission_rate + turnover * self.settings.transfer_fee_rate
        slip = turnover * self.settings.slippage_rate
        adjusted_pct = min(signal.position_pct, turnover / max(portfolio.equity, 1.0))
        return RiskCheckResult(
            allowed=True,
            adjusted_qty=qty,
            adjusted_position_pct=round(adjusted_pct, 4),
            risk_state="ALLOW" if adjusted_pct >= signal.position_pct * 0.95 else "REDUCE_POSITION",
            final_action="BUY",
            est_fee=round(max(5.0, fee), 4),
            est_tax=0.0,
            est_slippage=round(slip, 4),
        )

    def evaluate_action(self, action: PlannedAction, quote: MarketQuote, portfolio: PortfolioState, risk_mode: str = "NORMAL") -> RiskCheckResult:
        if action.action in {"HOLD", "AVOID_NEW_BUY", "ENTER_DEFENSIVE_MODE"}:
            return RiskCheckResult(
                allowed=False,
                adjusted_qty=0,
                adjusted_position_pct=0.0,
                reject_reason=action.reason,
                risk_state="INFO",
                final_action=action.action,
                risk_mode=risk_mode,
            )

        if portfolio.drawdown >= self.settings.max_drawdown_pct and action.action == "BUY":
            return RiskCheckResult(
                allowed=False,
                adjusted_qty=0,
                adjusted_position_pct=0.0,
                reject_reason="最大回撤熔断已触发，禁止继续开仓",
                risk_state="REJECT",
                final_action=action.action,
                risk_mode="RISK_OFF",
            )

        if quote.amount < self.settings.min_turnover:
            return RiskCheckResult(
                allowed=False,
                adjusted_qty=0,
                adjusted_position_pct=0.0,
                reject_reason="流动性不足",
                risk_state="REJECT",
                final_action=action.action,
                risk_mode=risk_mode,
            )

        if action.action == "BUY":
            signal = FinalSignal(
                symbol=action.symbol,
                action="BUY",
                entry_price=action.planned_price,
                position_pct=action.position_pct,
                confidence=float(action.metadata.get("confidence", 0.6) or 0.6),
                source_strategies=list(action.source),
                ai_approved=True,
                ai_reason=action.reason,
                strategy_reason=action.reason,
                strategy_name="+".join(action.source),
                mode_name=action.mode_name,
            )
            result = self.evaluate(signal, quote, portfolio)
            result.final_action = "BUY"
            result.risk_mode = risk_mode
            return result

        can_sell_qty = int(portfolio.current_positions.get(action.symbol, {}).get("can_sell_qty", 0))
        if can_sell_qty <= 0:
            return RiskCheckResult(
                allowed=False,
                adjusted_qty=0,
                adjusted_position_pct=0.0,
                reject_reason="T+1 限制，可卖数量为 0",
                risk_state="REJECT",
                final_action=action.action,
                risk_mode=risk_mode,
            )

        qty = min(self._lot_round_down(action.planned_qty), self._lot_round_down(can_sell_qty))
        if qty <= 0:
            return RiskCheckResult(
                allowed=False,
                adjusted_qty=0,
                adjusted_position_pct=0.0,
                reject_reason="可卖数量不足 100 股",
                risk_state="REJECT",
                final_action=action.action,
                risk_mode=risk_mode,
            )
        if quote.pct_change <= self.settings.limit_down_filter_pct:
            return RiskCheckResult(
                allowed=False,
                adjusted_qty=0,
                adjusted_position_pct=0.0,
                reject_reason="接近跌停，卖出成交风险过高",
                risk_state="REJECT",
                final_action=action.action,
                risk_mode=risk_mode,
            )
        return RiskCheckResult(
            allowed=True,
            adjusted_qty=qty,
            adjusted_position_pct=1.0 if action.action == "SELL" else max(0.0, min(1.0, action.reduce_pct)),
            risk_state="ALLOW",
            final_action=action.action,
            risk_mode=risk_mode,
            est_fee=round(max(5.0, qty * action.planned_price * self.settings.commission_rate), 4),
            est_tax=round(qty * action.planned_price * self.settings.stamp_duty_rate, 4),
            est_slippage=round(qty * action.planned_price * self.settings.slippage_rate, 4),
        )

    @staticmethod
    def _lot_round_down(quantity: int) -> int:
        if quantity <= 0:
            return 0
        return quantity // BOARD_LOT * BOARD_LOT
