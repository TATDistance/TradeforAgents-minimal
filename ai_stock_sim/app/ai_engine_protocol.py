from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


DecisionEngineAction = Literal[
    "BUY",
    "SELL",
    "REDUCE",
    "HOLD",
    "AVOID_NEW_BUY",
    "WATCH_NEXT_DAY",
    "PREPARE_BUY",
    "PREPARE_REDUCE",
    "HOLD_FOR_TOMORROW",
]


class AIDecisionEngineOutput(BaseModel):
    symbol: str
    action: DecisionEngineAction
    position_pct: float = 0.0
    reduce_pct: Optional[float] = None
    confidence: float = 0.5
    risk_mode: Literal["NORMAL", "DEFENSIVE", "RISK_OFF"] = "NORMAL"
    holding_bias: str = "SHORT_TERM"
    reason: str = ""
    warnings: List[str] = Field(default_factory=list)
    final_score: float = 0.0
    feature_score: float = 0.0
    source_mode: str = "ai_decision_engine_mode"
    extra: Dict[str, Any] = Field(default_factory=dict)


def normalize_engine_output(payload: Dict[str, Any], symbol: str, fallback_reason: str = "") -> AIDecisionEngineOutput:
    action = str(payload.get("action") or "HOLD").upper()
    if action not in {"BUY", "SELL", "REDUCE", "HOLD", "AVOID_NEW_BUY", "WATCH_NEXT_DAY", "PREPARE_BUY", "PREPARE_REDUCE", "HOLD_FOR_TOMORROW"}:
        action = "HOLD"
    risk_mode = str(payload.get("risk_mode") or "NORMAL").upper()
    if risk_mode not in {"NORMAL", "DEFENSIVE", "RISK_OFF"}:
        risk_mode = "NORMAL"
    warnings = payload.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    return AIDecisionEngineOutput(
        symbol=symbol,
        action=action,  # type: ignore[arg-type]
        position_pct=max(0.0, min(1.0, float(payload.get("position_pct") or 0.0))),
        reduce_pct=max(0.0, min(1.0, float(payload.get("reduce_pct") or 0.0))) if payload.get("reduce_pct") is not None else None,
        confidence=max(0.0, min(1.0, float(payload.get("confidence") or 0.5))),
        risk_mode=risk_mode,  # type: ignore[arg-type]
        holding_bias=str(payload.get("holding_bias") or "SHORT_TERM"),
        reason=str(payload.get("reason") or fallback_reason or "已按结构化默认规则解析"),
        warnings=[str(item) for item in warnings],
        final_score=float(payload.get("final_score") or 0.0),
        feature_score=float(payload.get("feature_score") or 0.0),
        source_mode=str(payload.get("source_mode") or "ai_decision_engine_mode"),
        extra=dict(payload.get("extra") or {}),
    )
