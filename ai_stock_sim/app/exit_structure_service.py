from __future__ import annotations

from math import isfinite
from typing import Dict, Mapping

from .settings import Settings, load_settings


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        resolved = float(value or 0.0)
    except Exception:
        return default
    return resolved if isfinite(resolved) else default


class ExitStructureService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def evaluate(
        self,
        *,
        technical: Mapping[str, object],
        position_state: Mapping[str, object],
        execution_score: float,
        risk_mode: str,
    ) -> Dict[str, object]:
        if not self.settings.exit_structure.enabled:
            return {
                "exit_type": "hold_on_structure",
                "exit_quality_score": 0.0,
                "suggested_action": "HOLD",
                "reduce_pct": 0.0,
                "exit_reason": "结构化卖点未启用",
            }

        unrealized_pct = _safe_float(position_state.get("unrealized_pct"))
        hold_days = int(position_state.get("hold_days") or 0)
        can_sell_qty = int(position_state.get("can_sell_qty") or 0)
        if can_sell_qty <= 0:
            return {
                "exit_type": "hold_on_structure",
                "exit_quality_score": 0.0,
                "suggested_action": "HOLD",
                "reduce_pct": 0.0,
                "exit_reason": "当前暂无可卖仓位",
            }

        slope20 = _safe_float(technical.get("trend_slope_20d"))
        ma20_bias = _safe_float(technical.get("ma20_bias"))
        ma60_bias = _safe_float(technical.get("ma60_bias"))
        macd_hist = _safe_float(technical.get("macd_hist"))
        rsi14 = _safe_float(technical.get("rsi_14"), 50.0)

        weakening_score = _clamp01(max(0.0, -slope20) / 0.08) * 0.35 + _clamp01(max(0.0, -ma20_bias) / 0.08) * 0.25 + _clamp01(max(0.0, -macd_hist) / 0.05) * 0.20 + _clamp01(max(0.0, -execution_score) / 0.6) * 0.20
        structure_break = (
            slope20 <= float(self.settings.exit_structure.break_sell_threshold)
            or ma20_bias <= -0.055
            or (ma60_bias <= -0.03 and macd_hist <= -0.02)
        )
        supportive = slope20 >= -0.01 and ma20_bias >= -0.025 and macd_hist >= -0.015

        if risk_mode == "RISK_OFF":
            return {
                "exit_type": "sell_on_break",
                "exit_quality_score": round(max(0.75, weakening_score), 4),
                "suggested_action": "SELL",
                "reduce_pct": 1.0,
                "exit_reason": "当前风险模式已转入风险关闭，优先退出已有仓位。",
            }

        if structure_break and (
            not self.settings.exit_structure.structure_break_required_for_full_sell or unrealized_pct <= -0.03 or execution_score <= -0.20
        ):
            return {
                "exit_type": "sell_on_break",
                "exit_quality_score": round(max(0.72, weakening_score), 4),
                "suggested_action": "SELL",
                "reduce_pct": 1.0,
                "exit_reason": "趋势结构已明显破坏，优先清仓而不是继续拖延。",
            }

        if unrealized_pct >= 0.08 and (rsi14 >= 72.0 or weakening_score >= 0.48 or hold_days >= 8):
            return {
                "exit_type": "take_profit_partial",
                "exit_quality_score": round(max(0.62, weakening_score), 4),
                "suggested_action": "REDUCE",
                "reduce_pct": 0.3 if supportive else 0.5,
                "exit_reason": "盈利单进入高位波动区，先分批兑现，避免整单卖飞或利润回撤。",
            }

        if weakening_score >= 0.45 or execution_score <= float(self.settings.exit_structure.weakening_reduce_threshold):
            return {
                "exit_type": "reduce_on_weakening",
                "exit_quality_score": round(max(0.58, weakening_score), 4),
                "suggested_action": "REDUCE" if self.settings.exit_structure.prefer_reduce_before_sell else "SELL",
                "reduce_pct": 0.3 if supportive else 0.5,
                "exit_reason": "趋势减弱但结构未完全破坏，先减仓更合适。",
            }

        if unrealized_pct <= -0.05 and supportive and execution_score > -0.18:
            return {
                "exit_type": "hold_on_structure",
                "exit_quality_score": round(max(0.52, 1.0 - weakening_score), 4),
                "suggested_action": "HOLD",
                "reduce_pct": 0.0,
                "exit_reason": "虽有回撤，但结构尚未明显走坏，不宜机械止损。",
            }

        return {
            "exit_type": "hold_on_structure",
            "exit_quality_score": round(max(0.48, 1.0 - weakening_score), 4),
            "suggested_action": "HOLD",
            "reduce_pct": 0.0,
            "exit_reason": "结构未坏，继续持有观察。",
        }
