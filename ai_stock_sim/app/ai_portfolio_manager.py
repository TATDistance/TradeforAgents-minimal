from __future__ import annotations

from typing import List, Mapping, Sequence

from .models import FinalSignal, MarketRegimeState, PortfolioManagerAction, PortfolioManagerDecision
from .settings import Settings, load_settings


class AIPortfolioManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def review(
        self,
        regime_state: MarketRegimeState,
        portfolio_feedback: Mapping[str, object],
        candidate_signals: Sequence[FinalSignal],
        strategy_weights: Mapping[str, float],
    ) -> PortfolioManagerDecision:
        if not self.settings.ai_portfolio_manager.enabled:
            return PortfolioManagerDecision(
                portfolio_view="组合管理器已关闭，沿用策略与风控结果。",
                risk_mode=self.settings.ai_portfolio_manager.default_risk_mode,
                actions=[],
                reason="disabled",
            )

        drawdown = float(portfolio_feedback.get("drawdown", 0.0) or 0.0)
        total_position_pct = float(portfolio_feedback.get("total_position_pct", 0.0) or 0.0)
        positions = portfolio_feedback.get("positions_detail") or []
        risk_mode = self._resolve_risk_mode(regime_state, drawdown, total_position_pct)
        actions: List[PortfolioManagerAction] = []

        if risk_mode in {"DEFENSIVE", "RISK_OFF"}:
            actions.append(
                PortfolioManagerAction(
                    symbol="*",
                    action="ENTER_DEFENSIVE_MODE" if risk_mode == "RISK_OFF" else "AVOID_NEW_BUY",
                    reason="账户回撤或市场状态触发防守模式，优先控制风险暴露。",
                    priority=0.98 if risk_mode == "RISK_OFF" else 0.9,
                    source=["ai_pm", regime_state.regime],
                )
            )

        if isinstance(positions, list):
            for item in positions:
                if not isinstance(item, Mapping):
                    continue
                symbol = str(item.get("symbol") or "")
                can_sell_qty = int(item.get("can_sell_qty") or 0)
                if not symbol or can_sell_qty <= 0:
                    continue
                unrealized_pct = float(item.get("unrealized_pct", 0.0) or 0.0)
                hold_days = int(item.get("hold_days", 0) or 0)
                if risk_mode == "RISK_OFF" and self.settings.ai_portfolio_manager.allow_sell_actions:
                    actions.append(
                        PortfolioManagerAction(
                            symbol=symbol,
                            action="SELL",
                            reason="组合进入风险关闭模式，优先降低已有持仓暴露。",
                            priority=0.96,
                            source=["ai_pm", "portfolio_feedback"],
                        )
                    )
                elif unrealized_pct >= 0.06 and regime_state.risk_bias in {"DEFENSIVE", "RISK_OFF"} and self.settings.ai_portfolio_manager.allow_reduce_actions:
                    actions.append(
                        PortfolioManagerAction(
                            symbol=symbol,
                            action="REDUCE",
                            reduce_pct=0.5,
                            reason="已有浮盈且市场偏谨慎，建议先锁定部分利润。",
                            priority=0.82,
                            source=["ai_pm", regime_state.regime],
                        )
                    )
                elif unrealized_pct <= -0.05 and self.settings.ai_portfolio_manager.allow_sell_actions:
                    actions.append(
                        PortfolioManagerAction(
                            symbol=symbol,
                            action="SELL",
                            reason="持仓回撤已扩大，建议止损退出。",
                            priority=0.88,
                            source=["ai_pm", "portfolio_feedback"],
                        )
                    )
                elif hold_days >= 10 and unrealized_pct > 0.03 and self.settings.ai_portfolio_manager.allow_reduce_actions:
                    actions.append(
                        PortfolioManagerAction(
                            symbol=symbol,
                            action="REDUCE",
                            reduce_pct=0.3,
                            reason="持有时间较长且已有盈利，建议做阶段性减仓。",
                            priority=0.7,
                            source=["ai_pm"],
                        )
                    )

        if self.settings.ai_portfolio_manager.allow_new_buy_actions and risk_mode not in {"RISK_OFF"}:
            for signal in sorted(candidate_signals, key=lambda item: item.confidence, reverse=True)[:3]:
                if signal.action != "BUY":
                    continue
                boost = float(strategy_weights.get(signal.source_strategies[0], 1.0)) if signal.source_strategies else 1.0
                adjusted_pct = signal.position_pct * (0.9 if risk_mode == "DEFENSIVE" else 1.0)
                actions.append(
                    PortfolioManagerAction(
                        symbol=signal.symbol,
                        action="BUY",
                        position_pct=round(adjusted_pct, 4),
                        reason="候选信号通过 AI 审核，且与当前市场状态一致。",
                        priority=round(min(0.95, signal.confidence * 0.75 + boost * 0.1), 4),
                        source=["ai_pm", "ai_reviewer", *signal.source_strategies],
                        metadata={"weighted_score": signal.weighted_score},
                    )
                )

        portfolio_view = self._portfolio_view(regime_state, risk_mode, drawdown, total_position_pct)
        return PortfolioManagerDecision(
            portfolio_view=portfolio_view,
            risk_mode=risk_mode,
            actions=actions,
            reason=regime_state.reason,
        )

    def _resolve_risk_mode(self, regime_state: MarketRegimeState, drawdown: float, total_position_pct: float) -> str:
        if drawdown >= self.settings.portfolio_feedback.drawdown_risk_off_threshold or regime_state.regime == "RISK_OFF":
            return "RISK_OFF"
        if (
            drawdown >= self.settings.portfolio_feedback.drawdown_defensive_threshold
            or regime_state.risk_bias == "DEFENSIVE"
            or total_position_pct >= self.settings.portfolio_feedback.high_position_threshold
        ):
            return "DEFENSIVE"
        return self.settings.ai_portfolio_manager.default_risk_mode

    @staticmethod
    def _portfolio_view(regime_state: MarketRegimeState, risk_mode: str, drawdown: float, total_position_pct: float) -> str:
        return (
            f"当前市场状态为 {regime_state.regime}，风险模式 {risk_mode}；"
            f"账户回撤 {drawdown:.2%}，总仓位 {total_position_pct:.2%}。"
        )
