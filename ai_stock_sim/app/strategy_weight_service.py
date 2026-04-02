from __future__ import annotations

import json
from typing import Dict, Mapping

from .models import MarketRegimeState
from .settings import Settings, load_settings


class StrategyWeightService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.base_weights: Dict[str, float] = {
            "momentum": 1.0,
            "dual_ma": 1.0,
            "macd_trend": 1.0,
            "mean_reversion": 1.0,
            "breakout": 1.0,
            "trend_pullback": 1.0,
        }

    def resolve_weights(self, regime_state: MarketRegimeState, portfolio_feedback: Mapping[str, object] | None = None) -> Dict[str, float]:
        weights = dict(self.base_weights)
        if not self.settings.strategy_weights.enabled:
            return weights

        regime = regime_state.regime
        if regime == "TRENDING_UP":
            weights["breakout"] *= 1.25
            weights["momentum"] *= 1.15
            weights["trend_pullback"] *= 1.15
            weights["mean_reversion"] *= 0.75
        elif regime == "TRENDING_DOWN":
            weights["mean_reversion"] *= 0.85
            weights["breakout"] *= 0.7
            weights["momentum"] *= 0.8
            weights["dual_ma"] *= 1.05
            weights["macd_trend"] *= 1.05
        elif regime == "HIGH_VOLATILITY":
            for key in weights:
                weights[key] *= 0.85
            weights["breakout"] *= 0.95
            weights["mean_reversion"] *= 0.9
        elif regime == "RISK_OFF":
            weights["breakout"] *= 0.55
            weights["momentum"] *= 0.6
            weights["trend_pullback"] *= 0.65
            weights["dual_ma"] *= 0.95
            weights["macd_trend"] *= 1.05
            weights["mean_reversion"] *= 0.8

        if portfolio_feedback:
            total_position_pct = float(portfolio_feedback.get("total_position_pct", 0.0) or 0.0)
            drawdown = float(portfolio_feedback.get("drawdown", 0.0) or 0.0)
            strategy_scores = portfolio_feedback.get("strategy_scores") or {}
            if total_position_pct >= self.settings.portfolio_feedback.high_position_threshold:
                for key in weights:
                    weights[key] *= 0.9
            if drawdown >= self.settings.portfolio_feedback.drawdown_defensive_threshold:
                for key in weights:
                    weights[key] *= 0.85
            if isinstance(strategy_scores, Mapping):
                for key, score in strategy_scores.items():
                    if key not in weights:
                        continue
                    try:
                        score_value = float(score)
                    except (TypeError, ValueError):
                        continue
                    if score_value < 60:
                        weights[key] *= 0.85
                    elif score_value >= 80:
                        weights[key] *= 1.05
        adaptive = self._load_adaptive_weights()
        for key, value in (adaptive.get("strategy_weights") or {}).items():
            if key in weights:
                weights[key] *= float(value or 1.0)
        return {key: round(value, 4) for key, value in weights.items()}

    def _load_adaptive_weights(self) -> Dict[str, object]:
        path = self.settings.cache_dir / "adaptive_weights.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
