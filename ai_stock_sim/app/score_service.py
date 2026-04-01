from __future__ import annotations

from typing import Dict, Mapping

from .settings import Settings, load_settings


def _clamp_score(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


class ScoreService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def compute_scores(
        self,
        *,
        symbol: str,
        feature_score: float,
        dominant_direction: str,
        ai_score: float,
        market_risk_penalty: float,
        portfolio_risk_penalty: float,
        phase_name: str,
        execution_gate: Mapping[str, object],
        portfolio_state: Mapping[str, object],
        position_state: Mapping[str, object],
        risk_mode: str,
    ) -> Dict[str, object]:
        setup_base = float(feature_score or 0.0) + float(ai_score or 0.0)
        setup_score = _clamp_score(setup_base - float(market_risk_penalty or 0.0) - float(portfolio_risk_penalty or 0.0))

        has_position = bool(position_state.get("has_position"))
        can_open = bool(execution_gate.get("can_open_position"))
        can_reduce = bool(execution_gate.get("can_reduce_position"))
        can_execute = bool(execution_gate.get("can_execute_fill"))
        phase_penalty = 0.0
        gate_penalty = 0.0

        if dominant_direction == "LONG" and not can_open:
            phase_penalty += 0.16
        if dominant_direction == "SHORT" and has_position and not can_reduce:
            phase_penalty += 0.12
        if not can_execute:
            gate_penalty += 0.08
        if risk_mode == "DEFENSIVE":
            gate_penalty += 0.04
        elif risk_mode == "RISK_OFF":
            gate_penalty += 0.10

        drawdown = float(portfolio_state.get("drawdown", 0.0) or 0.0)
        position_ratio = float(portfolio_state.get("total_position_pct", 0.0) or 0.0)
        if drawdown >= self.settings.portfolio_feedback.drawdown_defensive_threshold:
            gate_penalty += min(0.08, drawdown)
        if position_ratio >= self.settings.portfolio_feedback.high_position_threshold:
            gate_penalty += 0.05

        execution_score = _clamp_score(setup_score - phase_penalty - gate_penalty)
        watch_ready = setup_score >= self.settings.scoring.min_setup_score_to_watch
        executable_buy = dominant_direction == "LONG" and execution_score >= self.settings.scoring.min_execution_score_to_buy
        executable_reduce = has_position and execution_score <= -self.settings.scoring.min_execution_score_to_reduce

        explain_parts = []
        if watch_ready:
            explain_parts.append("多因子特征足以继续观察")
        else:
            explain_parts.append("当前特征强度仍偏弱")
        if dominant_direction == "LONG" and not can_open:
            explain_parts.append("当前阶段或权限不支持新开仓")
        if dominant_direction == "SHORT" and has_position and not can_reduce:
            explain_parts.append("当前阶段不支持减仓/卖出")
        if risk_mode in {"DEFENSIVE", "RISK_OFF"}:
            explain_parts.append(f"当前风险模式为 {risk_mode}")

        return {
            "symbol": symbol,
            "setup_score": round(setup_score, 4),
            "execution_score": round(execution_score, 4),
            "feature_score": round(float(feature_score or 0.0), 4),
            "ai_score": round(float(ai_score or 0.0), 4),
            "market_risk_penalty": round(float(market_risk_penalty or 0.0), 4),
            "portfolio_risk_penalty": round(float(portfolio_risk_penalty or 0.0), 4),
            "phase_penalty": round(phase_penalty, 4),
            "gate_penalty": round(gate_penalty, 4),
            "watch_ready": watch_ready,
            "executable_buy": executable_buy,
            "executable_reduce": executable_reduce,
            "explain": "；".join(explain_parts),
            "phase_name": phase_name,
        }
