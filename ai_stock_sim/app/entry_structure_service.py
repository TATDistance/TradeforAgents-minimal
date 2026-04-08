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


class EntryStructureService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def evaluate(
        self,
        *,
        snapshot: Mapping[str, object],
        technical: Mapping[str, object],
        market_regime: Mapping[str, object] | None = None,
        position_state: Mapping[str, object] | None = None,
    ) -> Dict[str, object]:
        if not self.settings.entry_structure.enabled:
            return {
                "entry_type": "watch_point",
                "entry_quality_score": 0.0,
                "allow_buy": True,
                "entry_reason": "结构化买点未启用",
                "position_scale": 1.0,
            }

        position_state = position_state or {}
        has_position = bool(position_state.get("has_position"))
        pct_change = self._normalize_pct_change(snapshot.get("pct_change"))
        ret5 = _safe_float(technical.get("ret_5d"))
        ret20 = _safe_float(technical.get("ret_20d"))
        slope20 = _safe_float(technical.get("trend_slope_20d"))
        ma20_bias = _safe_float(technical.get("ma20_bias"))
        ma60_bias = _safe_float(technical.get("ma60_bias"))
        macd_hist = _safe_float(technical.get("macd_hist"))
        rsi14 = _safe_float(technical.get("rsi_14"), 50.0)
        regime_name = str((market_regime or {}).get("regime") or "")

        chase_stretch = pct_change >= float(self.settings.entry_structure.max_chase_pct)
        ma20_stretch = ma20_bias >= float(self.settings.entry_structure.max_ma20_extension_pct)
        overheat = rsi14 >= 76.0 and pct_change >= 0.035
        if self.settings.entry_structure.chase_block_enabled and (chase_stretch or ma20_stretch or overheat):
            return {
                "entry_type": "chase_block",
                "entry_quality_score": round(_clamp01(0.18 + max(0.0, 0.08 - abs(ma20_bias)) * 4.0), 4),
                "allow_buy": False,
                "entry_reason": "当前价格位置偏高，属于追高区，不适合直接买入。",
                "position_scale": 0.0,
            }

        trend_support = _clamp01(max(slope20, 0.0) / 0.12) * 0.40 + _clamp01(max(ret20, 0.0) / 0.18) * 0.30 + _clamp01(max(ma60_bias, 0.0) / 0.12) * 0.15 + _clamp01((macd_hist + 0.01) / 0.05) * 0.15
        pullback_quality = _clamp01((0.04 - abs(ma20_bias)) / 0.04)
        reaccel_quality = _clamp01(max(ret5, 0.0) / 0.06)
        regime_bonus = 0.06 if regime_name == "TRENDING_UP" else -0.04 if regime_name in {"HIGH_VOLATILITY", "RISK_OFF"} else 0.0
        quality_score = _clamp01(trend_support * 0.55 + pullback_quality * 0.25 + reaccel_quality * 0.20 + regime_bonus)

        if has_position and quality_score >= 0.72 and slope20 >= 0.05 and -0.01 <= ma20_bias <= 0.03 and ret5 >= 0.01:
            return {
                "entry_type": "add_entry",
                "entry_quality_score": round(quality_score, 4),
                "allow_buy": True,
                "entry_reason": "趋势延续且回踩后再企稳，适合在已有仓位上加仓。",
                "position_scale": 1.0,
            }

        if trend_support >= 0.38 and -0.025 <= ma20_bias <= 0.025 and ret5 >= -0.01:
            return {
                "entry_type": "probe_entry",
                "entry_quality_score": round(max(0.55, quality_score), 4),
                "allow_buy": True,
                "entry_reason": "趋势未坏且位置不过热，适合小仓位试仓。",
                "position_scale": 0.55,
            }

        allow_watch = trend_support >= 0.24 and ma20_bias <= 0.04
        return {
            "entry_type": "watch_point",
            "entry_quality_score": round(min(0.54, quality_score), 4),
            "allow_buy": not self.settings.entry_structure.require_pullback_confirmation and allow_watch,
            "entry_reason": "有观察价值，但买点结构还不够清晰，先继续观察。",
            "position_scale": 0.0 if self.settings.entry_structure.require_pullback_confirmation else 0.35,
        }

    @staticmethod
    def _normalize_pct_change(value: object) -> float:
        raw = _safe_float(value)
        return raw / 100.0 if abs(raw) >= 1.0 else raw
