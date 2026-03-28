from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .settings import Settings, load_settings


@dataclass
class StrategyScore:
    strategy_name: str
    score_total: float
    score_return: float
    score_risk: float
    score_stability: float
    score_execution: float
    grade: str
    status: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "strategy_name": self.strategy_name,
            "score_total": self.score_total,
            "score_return": self.score_return,
            "score_risk": self.score_risk,
            "score_stability": self.score_stability,
            "score_execution": self.score_execution,
            "grade": self.grade,
            "status": self.status,
        }


class ScoringService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def score_strategy(self, strategy_name: str, metrics: Mapping[str, float | int]) -> StrategyScore:
        score_return = self._score_return(metrics)
        score_risk = self._score_risk(metrics)
        score_stability = self._score_stability(metrics)
        score_execution = self._score_execution(metrics)

        total = (
            score_return * self.settings.scoring.weight_return
            + score_risk * self.settings.scoring.weight_risk
            + score_stability * self.settings.scoring.weight_stability
            + score_execution * self.settings.scoring.weight_execution
        )
        total = max(0.0, min(100.0, round(total, 2)))
        grade = self._grade(total)
        status = self._status(total, float(metrics.get("max_drawdown", 0.0) or 0.0))
        return StrategyScore(
            strategy_name=strategy_name,
            score_total=total,
            score_return=round(score_return, 2),
            score_risk=round(score_risk, 2),
            score_stability=round(score_stability, 2),
            score_execution=round(score_execution, 2),
            grade=grade,
            status=status,
        )

    @staticmethod
    def _clip_score(value: float) -> float:
        return max(0.0, min(100.0, value))

    def _score_return(self, metrics: Mapping[str, float | int]) -> float:
        total_return = float(metrics.get("total_return", 0.0) or 0.0)
        expectancy = float(metrics.get("expectancy", 0.0) or 0.0)
        monthly_return = float(metrics.get("monthly_return", total_return) or 0.0)
        total_component = self._clip_score(50.0 + total_return * 250.0)
        expectancy_component = self._clip_score(50.0 + expectancy * 5.0)
        monthly_component = self._clip_score(50.0 + monthly_return * 220.0)
        return total_component * 0.45 + expectancy_component * 0.25 + monthly_component * 0.30

    def _score_risk(self, metrics: Mapping[str, float | int]) -> float:
        max_drawdown = float(metrics.get("max_drawdown", 0.0) or 0.0)
        current_drawdown = float(metrics.get("current_drawdown", 0.0) or 0.0)
        risk_events = float(metrics.get("risk_events", 0.0) or 0.0)
        base = 100.0
        base -= min(60.0, max_drawdown * 400.0)
        base -= min(25.0, current_drawdown * 250.0)
        base -= min(15.0, risk_events * 3.0)
        return self._clip_score(base)

    def _score_stability(self, metrics: Mapping[str, float | int]) -> float:
        monthly_positive_ratio = float(metrics.get("monthly_positive_ratio", 0.0) or 0.0)
        volatility_penalty = float(metrics.get("return_volatility", 0.0) or 0.0)
        longest_loss_streak = float(metrics.get("longest_loss_streak", 0.0) or 0.0)
        base = monthly_positive_ratio * 70.0
        base += max(0.0, 20.0 - volatility_penalty * 100.0)
        base += max(0.0, 10.0 - longest_loss_streak * 2.0)
        return self._clip_score(base)

    def _score_execution(self, metrics: Mapping[str, float | int]) -> float:
        pnl_ratio = float(metrics.get("pnl_ratio", 0.0) or 0.0)
        profit_factor = float(metrics.get("profit_factor", 0.0) or 0.0)
        hit_rate = float(metrics.get("signal_hit_rate", metrics.get("win_rate", 0.0)) or 0.0)
        pnl_component = self._clip_score(min(100.0, pnl_ratio * 30.0))
        factor_component = self._clip_score(min(100.0, profit_factor * 35.0))
        hit_component = self._clip_score(hit_rate * 100.0)
        return pnl_component * 0.30 + factor_component * 0.35 + hit_component * 0.35

    @staticmethod
    def _grade(total: float) -> str:
        if total >= 85:
            return "A"
        if total >= 75:
            return "B+"
        if total >= 65:
            return "B"
        if total >= 50:
            return "C"
        return "D"

    @staticmethod
    def _status(total: float, max_drawdown: float) -> str:
        if max_drawdown >= 0.12:
            return "REVIEW_RISK"
        if total >= 75:
            return "KEEP_RUNNING"
        if total >= 60:
            return "OBSERVE"
        return "PAUSE"
