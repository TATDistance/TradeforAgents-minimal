from __future__ import annotations

from math import isfinite
from typing import Dict, Mapping

import pandas as pd

from .settings import Settings, load_settings


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        resolved = float(value or 0.0)
    except Exception:
        return default
    return resolved if isfinite(resolved) else default


class CandidateQualityService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def evaluate_batch(
        self,
        snapshot: pd.DataFrame,
        *,
        technical_map: Mapping[str, Mapping[str, float]] | None = None,
        theme_report: Mapping[str, object] | None = None,
        leader_map: Mapping[str, Mapping[str, object]] | None = None,
        market_regime: Mapping[str, object] | str | None = None,
    ) -> Dict[str, Dict[str, object]]:
        if snapshot.empty or not self.settings.candidate_quality.enabled:
            return {}

        technical_map = technical_map or {}
        leader_map = leader_map or {}
        symbol_themes = ((theme_report or {}).get("symbol_themes") or {}) if isinstance(theme_report, Mapping) else {}
        regime_name = market_regime.get("regime") if isinstance(market_regime, Mapping) else str(market_regime or "")
        results: Dict[str, Dict[str, object]] = {}
        for _, row in snapshot.iterrows():
            symbol = str(row.get("symbol") or "").strip()
            results[symbol] = self.evaluate_candidate(
                row=row,
                technical=dict(technical_map.get(symbol) or {}),
                theme_info=dict(symbol_themes.get(symbol) or {}),
                leader_info=dict(leader_map.get(symbol) or {}),
                regime_name=regime_name,
            )
        return results

    def evaluate_candidate(
        self,
        *,
        row: Mapping[str, object],
        technical: Mapping[str, float],
        theme_info: Mapping[str, object],
        leader_info: Mapping[str, object],
        regime_name: str,
    ) -> Dict[str, object]:
        symbol = str(row.get("symbol") or "").strip()
        amount = _safe_float(row.get("amount"))
        turnover = _safe_float(row.get("turnover_rate"))
        pct_change = _safe_float(row.get("pct_change"))
        ret20 = _safe_float(technical.get("ret_20d"))
        slope20 = _safe_float(technical.get("trend_slope_20d"))
        ma20_bias = _safe_float(technical.get("ma20_bias"))
        macd_hist = _safe_float(technical.get("macd_hist"))
        rsi14 = _safe_float(technical.get("rsi_14"), 50.0)

        trend_score = _clamp01(
            _clamp01((slope20 + 0.02) / 0.14) * 0.35
            + _clamp01((ret20 + 0.04) / 0.22) * 0.30
            + _clamp01((ma20_bias + 0.05) / 0.14) * 0.20
            + _clamp01((macd_hist + 0.03) / 0.08) * 0.15
        )
        liquidity_score = _clamp01(
            _clamp01(amount / max(float(self.settings.min_turnover), 1.0)) * 0.55
            + _clamp01(turnover / 6.0) * 0.45
        )
        theme_strength = float(theme_info.get("strength") or 0.0)
        leader_role = str(leader_info.get("role") or "non_theme")
        theme_fit = _clamp01(theme_strength * 0.65 + (0.35 if leader_role == "leader" else 0.22 if leader_role == "strong_follower" else 0.08 if leader_role == "weak_follower" else 0.0))

        regime_fit = 0.55
        if regime_name == "TRENDING_UP":
            regime_fit = _clamp01(0.45 + trend_score * 0.55)
        elif regime_name in {"HIGH_VOLATILITY", "RISK_OFF"}:
            regime_fit = _clamp01(0.65 - max(0.0, pct_change - 4.0) / 8.0 - max(0.0, abs(ma20_bias) - 0.05))
        noise_penalty = self._noise_penalty(pct_change=pct_change, ret20=ret20, ma20_bias=ma20_bias, rsi14=rsi14, macd_hist=macd_hist)

        quality_score = _clamp01(trend_score * 0.34 + liquidity_score * 0.24 + theme_fit * 0.22 + regime_fit * 0.20 - noise_penalty * 0.22)
        reasons: list[str] = []
        if theme_strength >= 0.55:
            reasons.append("主线匹配")
        if trend_score >= 0.55:
            reasons.append("趋势清晰")
        if liquidity_score >= 0.45:
            reasons.append("成交质量合格")
        if quality_score < float(self.settings.candidate_quality.min_quality_score):
            reasons.append("综合质量不足")
        if trend_score < float(self.settings.candidate_quality.min_trend_score):
            reasons.append("弱趋势")
        if liquidity_score < float(self.settings.candidate_quality.min_liquidity_score):
            reasons.append("成交承接不足")
        if noise_penalty > float(self.settings.candidate_quality.max_noise_penalty):
            reasons.append("高波动噪音")
        if regime_name in {"HIGH_VOLATILITY", "RISK_OFF"} and pct_change > 6.0:
            reasons.append("当前风险模式不适合追高")

        passed = True
        if quality_score < float(self.settings.candidate_quality.min_quality_score):
            passed = False
        if trend_score < float(self.settings.candidate_quality.min_trend_score):
            passed = False
        if liquidity_score < float(self.settings.candidate_quality.min_liquidity_score):
            passed = False
        if noise_penalty > float(self.settings.candidate_quality.max_noise_penalty):
            passed = False

        return {
            "symbol": symbol,
            "quality_score": round(quality_score, 4),
            "trend_score": round(trend_score, 4),
            "liquidity_score": round(liquidity_score, 4),
            "theme_fit_score": round(theme_fit, 4),
            "noise_penalty": round(noise_penalty, 4),
            "passed": passed,
            "filter_reasons": reasons[:4],
        }

    @staticmethod
    def _noise_penalty(*, pct_change: float, ret20: float, ma20_bias: float, rsi14: float, macd_hist: float) -> float:
        overheat = _clamp01(max(0.0, pct_change - 6.0) / 4.0)
        stretched = _clamp01(max(0.0, abs(ma20_bias) - 0.05) / 0.08)
        weak_follow = _clamp01(max(0.0, 0.03 - ret20) / 0.08) if pct_change > 5.0 else 0.0
        momentum_conflict = 0.25 if rsi14 >= 78.0 and macd_hist <= 0 else 0.0
        return _clamp01(overheat * 0.35 + stretched * 0.30 + weak_follow * 0.20 + momentum_conflict)
