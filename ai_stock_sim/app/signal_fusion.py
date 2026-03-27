from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from .ai_decision_service import AIDecisionService
from .models import AIDecision, FinalSignal, StrategySignal
from .settings import Settings, load_settings


class SignalFusion:
    def __init__(self, settings: Settings | None = None, ai_service: AIDecisionService | None = None) -> None:
        self.settings = settings or load_settings()
        self.ai_service = ai_service or AIDecisionService(self.settings)

    def fuse(self, grouped_signals: Dict[str, List[StrategySignal]], trade_date: str | None = None) -> tuple[List[FinalSignal], List[AIDecision]]:
        final_signals: List[FinalSignal] = []
        ai_decisions: List[AIDecision] = []
        for symbol, signals in grouped_signals.items():
            if len(signals) < 2:
                continue
            by_action: Dict[str, List[StrategySignal]] = defaultdict(list)
            for signal in signals:
                by_action[signal.action].append(signal)
            dominant_action, same_side = max(by_action.items(), key=lambda item: len(item[1]))
            if dominant_action == "HOLD" or len(same_side) < 2:
                continue
            stop_candidates = [item.stop_loss for item in same_side if item.stop_loss is not None]
            take_candidates = [item.take_profit for item in same_side if item.take_profit is not None]

            avg_score = sum(item.score for item in same_side) / len(same_side)
            candidate = StrategySignal(
                symbol=symbol,
                strategy="+".join(item.strategy for item in same_side),
                action=dominant_action,  # type: ignore[arg-type]
                score=avg_score,
                signal_price=sum(item.signal_price for item in same_side) / len(same_side),
                stop_loss=min(stop_candidates) if stop_candidates else None,
                take_profit=max(take_candidates) if take_candidates else None,
                position_pct=min(sum(item.position_pct for item in same_side) / len(same_side), self.settings.max_single_position_pct),
                reason="；".join(item.reason for item in same_side),
            )
            ai_decision = self.ai_service.review_signal(symbol=symbol, candidate=candidate, trade_date=trade_date)
            ai_decisions.append(ai_decision)
            if not ai_decision.approved or ai_decision.ai_action == "HOLD":
                continue
            position_pct = candidate.position_pct
            if ai_decision.confidence < self.settings.ai.approval_confidence_floor:
                position_pct *= self.settings.ai.low_confidence_scale

            final_signals.append(
                FinalSignal(
                    symbol=symbol,
                    action=candidate.action,
                    entry_price=round(candidate.signal_price, 3),
                    stop_loss=candidate.stop_loss,
                    take_profit=candidate.take_profit,
                    position_pct=round(position_pct, 4),
                    confidence=round((candidate.score + ai_decision.confidence) / 2, 4),
                    source_strategies=[item.strategy for item in same_side],
                    ai_approved=ai_decision.approved,
                    ai_reason=ai_decision.reason,
                    strategy_reason=candidate.reason,
                )
            )
        return final_signals, ai_decisions
