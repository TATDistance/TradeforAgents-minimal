from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Optional

from .ai_decision_service import AIDecisionService
from .models import AIDecision, FeatureFusionScore, FinalSignal, MarketRegimeState, StrategyFeature, StrategySignal
from .settings import Settings, load_settings


class SignalFusion:
    def __init__(self, settings: Settings | None = None, ai_service: AIDecisionService | None = None) -> None:
        self.settings = settings or load_settings()
        self.ai_service = ai_service or AIDecisionService(self.settings)

    def fuse(
        self,
        grouped_signals: Dict[str, List[StrategySignal]],
        trade_date: str | None = None,
        context_map: Optional[Dict[str, Mapping[str, object]]] = None,
        strategy_weights: Optional[Mapping[str, float]] = None,
        market_regime: Optional[MarketRegimeState] = None,
        mode_name: str = "legacy_review_mode",
    ) -> tuple[List[FinalSignal], List[AIDecision]]:
        final_signals: List[FinalSignal] = []
        ai_decisions: List[AIDecision] = []
        for symbol, signals in grouped_signals.items():
            by_action: Dict[str, List[StrategySignal]] = defaultdict(list)
            for signal in signals:
                by_action[signal.action].append(signal)
            action_scores: Dict[str, float] = {}
            for action, items in by_action.items():
                total = 0.0
                for item in items:
                    weight = float((strategy_weights or {}).get(item.strategy, 1.0))
                    total += item.score * weight
                action_scores[action] = total / max(len(items), 1)
            dominant_action = max(action_scores.items(), key=lambda item: item[1])[0]
            same_side = by_action[dominant_action]
            if dominant_action == "HOLD":
                continue
            weighted_score = float(action_scores.get(dominant_action, 0.0))
            min_score = self.settings.fusion.min_final_score_to_buy if dominant_action == "BUY" else self.settings.fusion.min_final_score_to_sell
            if weighted_score < min_score:
                continue
            stop_candidates = [item.stop_loss for item in same_side if item.stop_loss is not None]
            take_candidates = [item.take_profit for item in same_side if item.take_profit is not None]

            avg_score = sum(item.score for item in same_side) / len(same_side)
            risk_penalty = 0.0
            if market_regime:
                if market_regime.regime == "HIGH_VOLATILITY":
                    risk_penalty += 0.08
                elif market_regime.regime == "RISK_OFF":
                    risk_penalty += 0.12
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
            extra_context = dict((context_map or {}).get(symbol, {}))
            try:
                ai_decision = self.ai_service.review_signal(
                    symbol=symbol,
                    candidate=candidate,
                    trade_date=trade_date,
                    market_snapshot=extra_context.get("market_snapshot") if isinstance(extra_context, dict) else None,
                    technical_summary=extra_context.get("technical_summary") if isinstance(extra_context, dict) else None,
                    portfolio_context=extra_context.get("portfolio_context") if isinstance(extra_context, dict) else None,
                    risk_constraints=extra_context.get("risk_constraints") if isinstance(extra_context, dict) else None,
                    market_regime=market_regime.model_dump() if market_regime else None,
                )
            except TypeError:
                ai_decision = self.ai_service.review_signal(symbol=symbol, candidate=candidate, trade_date=trade_date)
            ai_decisions.append(ai_decision)
            if not ai_decision.approved or ai_decision.ai_action == "HOLD":
                continue
            position_pct = candidate.position_pct
            if ai_decision.confidence < self.settings.ai.approval_confidence_floor:
                position_pct *= self.settings.ai.low_confidence_scale
            position_pct = max(0.03, position_pct * max(0.5, 1.0 - risk_penalty))

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
                    strategy_name=candidate.strategy,
                    mode_name=mode_name,
                    weighted_score=round(weighted_score, 4),
                    risk_penalty=round(risk_penalty, 4),
                )
            )
        return final_signals, ai_decisions

    def fuse_features(
        self,
        grouped_features: Dict[str, List[StrategyFeature]],
        strategy_weights: Optional[Mapping[str, float]] = None,
        market_regime: Optional[MarketRegimeState] = None,
        portfolio_feedback: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, FeatureFusionScore]:
        results: Dict[str, FeatureFusionScore] = {}
        for symbol, features in grouped_features.items():
            if not features:
                continue
            weighted_total = 0.0
            total_weight = 0.0
            breakdown: Dict[str, float] = {}
            for item in features:
                weight = float((strategy_weights or {}).get(item.strategy_name, 1.0))
                value = item.score * weight
                weighted_total += value
                total_weight += abs(weight)
                breakdown[item.strategy_name] = round(value, 4)
            feature_score = 0.0 if total_weight <= 0 else weighted_total / total_weight
            risk_penalty = 0.0
            if market_regime:
                if market_regime.regime == "HIGH_VOLATILITY":
                    risk_penalty += 0.08
                elif market_regime.regime == "RISK_OFF":
                    risk_penalty += 0.14
                elif market_regime.regime == "TRENDING_DOWN":
                    risk_penalty += 0.05
            if portfolio_feedback:
                drawdown = float(portfolio_feedback.get("drawdown", 0.0) or 0.0)
                total_position_pct = float(portfolio_feedback.get("total_position_pct", 0.0) or 0.0)
                risk_penalty += min(0.18, drawdown * 1.6)
                if total_position_pct >= self.settings.portfolio_feedback.high_position_threshold:
                    risk_penalty += 0.05
            final_score = max(-1.0, min(1.0, feature_score - risk_penalty))
            dominant_direction = "NEUTRAL"
            if final_score >= 0.12:
                dominant_direction = "LONG"
            elif final_score <= -0.12:
                dominant_direction = "SHORT"
            if final_score >= self.settings.fusion.min_final_score_to_buy:
                final_action = "BUY"
            elif final_score <= -self.settings.fusion.min_final_score_to_sell:
                final_action = "SELL"
            elif final_score < 0:
                final_action = "AVOID_NEW_BUY"
            else:
                final_action = "HOLD"
            results[symbol] = FeatureFusionScore(
                symbol=symbol,
                feature_score=round(feature_score, 4),
                dominant_direction=dominant_direction,  # type: ignore[arg-type]
                ai_decision_score=0.0,
                risk_penalty=round(risk_penalty, 4),
                final_score=round(final_score, 4),
                final_action=final_action,  # type: ignore[arg-type]
                feature_breakdown=breakdown,
                summary=f"多策略特征综合分 {final_score:.2f}，主方向 {dominant_direction}",
            )
        return results
