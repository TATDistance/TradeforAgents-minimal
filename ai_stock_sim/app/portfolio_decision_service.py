from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence

from .ai_engine_protocol import AIDecisionEngineOutput
from .models import FinalSignal, MarketRegimeState, PortfolioManagerAction, PortfolioManagerDecision
from .settings import Settings, load_settings


class PortfolioDecisionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def merge(
        self,
        candidate_signals: Sequence[FinalSignal],
        manager_decision: PortfolioManagerDecision,
        market_regime: MarketRegimeState,
    ) -> List[PortfolioManagerAction]:
        merged: Dict[str, PortfolioManagerAction] = {}
        suppress_new_buys = any(action.action in {"AVOID_NEW_BUY", "ENTER_DEFENSIVE_MODE"} for action in manager_decision.actions)

        for action in manager_decision.actions:
            key = action.symbol
            merged[key] = action

        for signal in candidate_signals:
            if signal.action == "BUY":
                if suppress_new_buys:
                    continue
                action = PortfolioManagerAction(
                    symbol=signal.symbol,
                    action="BUY",
                    position_pct=signal.position_pct,
                    reason=signal.ai_reason or signal.strategy_reason or "策略与 AI 审核均通过",
                    priority=round(min(0.95, signal.confidence), 4),
                    source=["ai_reviewer", *signal.source_strategies],
                    mode_name="legacy_review_mode",
                    metadata={"confidence": signal.confidence, "weighted_score": signal.weighted_score, "mode_name": "legacy_review_mode"},
                )
            elif signal.action == "SELL":
                action = PortfolioManagerAction(
                    symbol=signal.symbol,
                    action="SELL",
                    reason=signal.ai_reason or signal.strategy_reason or "策略触发卖出",
                    priority=round(min(0.96, signal.confidence + 0.08), 4),
                    source=["ai_reviewer", *signal.source_strategies],
                    mode_name="legacy_review_mode",
                    metadata={"confidence": signal.confidence, "weighted_score": signal.weighted_score, "mode_name": "legacy_review_mode"},
                )
            else:
                action = PortfolioManagerAction(
                    symbol=signal.symbol,
                    action="HOLD",
                    reason=signal.ai_reason or "保持观察",
                    priority=0.3,
                    source=["ai_reviewer", *signal.source_strategies],
                    mode_name="legacy_review_mode",
                    metadata={"mode_name": "legacy_review_mode"},
                )
            self._merge_action(merged, action)

        if market_regime.regime == "RISK_OFF":
            merged.setdefault(
                "*",
                PortfolioManagerAction(
                    symbol="*",
                    action="ENTER_DEFENSIVE_MODE",
                    reason="市场状态机识别为风险关闭模式",
                    priority=0.99,
                    source=["market_regime"],
                    mode_name="legacy_review_mode",
                    metadata={"mode_name": "legacy_review_mode"},
                ),
            )

        return sorted(merged.values(), key=lambda item: item.priority, reverse=True)

    def merge_engine(
        self,
        engine_decisions: Mapping[str, AIDecisionEngineOutput],
        market_regime: MarketRegimeState,
    ) -> List[PortfolioManagerAction]:
        actions: List[PortfolioManagerAction] = []
        defensive_inserted = False
        for symbol, decision in engine_decisions.items():
            if decision.action == "HOLD":
                priority = 0.25
            elif decision.action == "BUY":
                priority = 0.55 + decision.confidence * 0.35
            elif decision.action == "REDUCE":
                priority = 0.72 + decision.confidence * 0.18
            elif decision.action == "SELL":
                priority = 0.85 + decision.confidence * 0.12
            else:
                priority = 0.8
            actions.append(
                PortfolioManagerAction(
                    symbol=symbol,
                    action=decision.action,  # type: ignore[arg-type]
                    position_pct=decision.position_pct,
                    reduce_pct=decision.reduce_pct or 0.0,
                    reason=decision.reason,
                    priority=round(min(priority, 0.99), 4),
                    source=["ai_decision_engine"],
                    mode_name=decision.source_mode,
                    metadata={
                        "confidence": decision.confidence,
                        "final_score": decision.final_score,
                        "feature_score": decision.feature_score,
                        "risk_mode": decision.risk_mode,
                        "warnings": decision.warnings,
                        "mode_name": decision.source_mode,
                    },
                )
            )
            if decision.risk_mode in {"DEFENSIVE", "RISK_OFF"} and not defensive_inserted:
                actions.append(
                    PortfolioManagerAction(
                        symbol="*",
                        action="ENTER_DEFENSIVE_MODE" if decision.risk_mode == "RISK_OFF" else "AVOID_NEW_BUY",
                        reason=f"AI 决策引擎当前风险模式为 {decision.risk_mode}",
                        priority=0.97 if decision.risk_mode == "RISK_OFF" else 0.88,
                        source=["ai_decision_engine", "risk_mode"],
                        mode_name=decision.source_mode,
                        metadata={"mode_name": decision.source_mode},
                    )
                )
                defensive_inserted = True

        if market_regime.regime == "RISK_OFF" and not defensive_inserted:
            actions.append(
                PortfolioManagerAction(
                    symbol="*",
                    action="ENTER_DEFENSIVE_MODE",
                    reason="市场状态机识别为风险关闭模式",
                    priority=0.99,
                    source=["market_regime"],
                    mode_name="ai_decision_engine_mode",
                    metadata={"mode_name": "ai_decision_engine_mode"},
                )
            )
        return sorted(actions, key=lambda item: item.priority, reverse=True)

    def _merge_action(self, merged: Dict[str, PortfolioManagerAction], action: PortfolioManagerAction) -> None:
        existing = merged.get(action.symbol)
        if existing is None:
            merged[action.symbol] = action
            return
        precedence = {
            "SELL": 5,
            "REDUCE": 4,
            "ENTER_DEFENSIVE_MODE": 4,
            "AVOID_NEW_BUY": 3,
            "BUY": 2,
            "HOLD": 1,
        }
        if precedence.get(action.action, 0) > precedence.get(existing.action, 0):
            merged[action.symbol] = action
            return
        if precedence.get(action.action, 0) == precedence.get(existing.action, 0) and action.priority > existing.priority:
            merged[action.symbol] = action
