from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Dict, Mapping, Sequence

import pandas as pd

from .models import StrategyFeature
from .settings import Settings, load_settings


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        resolved = float(value or 0.0)
    except Exception:
        return default
    return resolved if isfinite(resolved) else default


def _positive_feature_score(features: Sequence[StrategyFeature], strategy_name: str) -> float:
    for item in features:
        if item.strategy_name != strategy_name:
            continue
        if str(item.direction) != "LONG":
            return 0.0
        return max(0.0, float(item.score or 0.0))
    return 0.0


class ThemeDetectionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def detect(
        self,
        snapshot: pd.DataFrame,
        *,
        technical_map: Mapping[str, Mapping[str, float]] | None = None,
        feature_map: Mapping[str, Sequence[StrategyFeature]] | None = None,
    ) -> Dict[str, object]:
        now = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
        if snapshot.empty or not self.settings.theme_detection.enabled:
            return {
                "top_themes": [],
                "market_theme_mode": "weak",
                "symbol_themes": {},
                "detected_at": now,
            }

        ranked = snapshot.copy()
        top_amount = max(float(ranked["amount"].max() or 0.0), 1.0)
        technical_map = technical_map or {}
        feature_map = feature_map or {}
        symbol_themes: Dict[str, Dict[str, object]] = {}
        grouped_scores: Dict[str, list[float]] = defaultdict(list)
        grouped_breadth: Dict[str, list[float]] = defaultdict(list)
        grouped_persistence: Dict[str, list[float]] = defaultdict(list)

        for _, row in ranked.iterrows():
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            technical = dict(technical_map.get(symbol) or {})
            features = feature_map.get(symbol, [])
            entry = self._classify_symbol(
                row=row,
                top_amount=top_amount,
                technical=technical,
                features=features,
            )
            symbol_themes[symbol] = entry
            theme_name = str(entry.get("theme") or "非主线")
            if theme_name == "非主线":
                continue
            grouped_scores[theme_name].append(float(entry.get("strength") or 0.0))
            grouped_breadth[theme_name].append(float(entry.get("breadth_hint") or 0.0))
            grouped_persistence[theme_name].append(float(entry.get("persistence_hint") or 0.0))

        total_symbols = max(len(symbol_themes), 1)
        top_themes = []
        for theme_name, scores in grouped_scores.items():
            count = len(scores)
            breadth = count / total_symbols
            breadth_hint = sum(grouped_breadth.get(theme_name, [0.0])) / max(count, 1)
            persistence = sum(grouped_persistence.get(theme_name, [0.0])) / max(count, 1)
            strength = sum(scores) / max(count, 1)
            theme_strength = _clamp01(strength * 0.55 + breadth_hint * 0.20 + persistence * 0.25)
            if theme_strength < float(self.settings.theme_detection.min_theme_strength) and count < int(self.settings.theme_detection.min_symbols_per_theme):
                continue
            top_themes.append(
                {
                    "name": theme_name,
                    "strength": round(theme_strength, 4),
                    "breadth": round(_clamp01(breadth * 2.5), 4),
                    "persistence": round(_clamp01(persistence), 4),
                    "count": count,
                }
            )

        top_themes.sort(
            key=lambda item: (
                float(item.get("strength") or 0.0),
                float(item.get("breadth") or 0.0),
                int(item.get("count") or 0),
            ),
            reverse=True,
        )
        mode = self._resolve_market_theme_mode(top_themes)
        return {
            "top_themes": top_themes[:4],
            "market_theme_mode": mode,
            "symbol_themes": symbol_themes,
            "detected_at": now,
        }

    def _classify_symbol(
        self,
        *,
        row: Mapping[str, object],
        top_amount: float,
        technical: Mapping[str, float],
        features: Sequence[StrategyFeature],
    ) -> Dict[str, object]:
        amount_score = _clamp01(_safe_float(row.get("amount")) / top_amount)
        pct_change = _safe_float(row.get("pct_change"))
        turnover = _safe_float(row.get("turnover_rate"))
        ret20 = _safe_float(technical.get("ret_20d"))
        slope20 = _safe_float(technical.get("trend_slope_20d"))
        ma20_bias = _safe_float(technical.get("ma20_bias"))
        ret5 = _safe_float(technical.get("ret_5d"))
        breakout_score = _positive_feature_score(features, "breakout")
        pullback_score = _positive_feature_score(features, "trend_pullback")
        momentum_score = _positive_feature_score(features, "momentum")

        theme = "非主线"
        reasons: list[str] = []
        strength = 0.0
        if breakout_score >= 0.30 and pct_change >= 2.0:
            theme = "强势突破"
            strength = _clamp01(breakout_score * 0.55 + amount_score * 0.25 + _clamp01(turnover / 8.0) * 0.20)
            reasons.append("放量突破")
        elif momentum_score >= 0.30 and slope20 >= 0.05 and ret20 >= 0.05:
            theme = "趋势主升"
            strength = _clamp01(momentum_score * 0.45 + _clamp01(ret20 / 0.18) * 0.25 + _clamp01(slope20 / 0.12) * 0.20 + amount_score * 0.10)
            reasons.append("趋势延续")
        elif pullback_score >= 0.24 and slope20 >= 0.03 and abs(ma20_bias) <= 0.035:
            theme = "回踩修复"
            strength = _clamp01(pullback_score * 0.45 + _clamp01((0.04 - abs(ma20_bias)) / 0.04) * 0.25 + amount_score * 0.15 + _clamp01(max(ret5, 0.0) / 0.05) * 0.15)
            reasons.append("回踩蓄势")
        elif amount_score >= 0.55 and pct_change > 0.8 and turnover >= 1.2:
            theme = "资金回流"
            strength = _clamp01(amount_score * 0.45 + _clamp01(pct_change / 6.0) * 0.30 + _clamp01(turnover / 8.0) * 0.25)
            reasons.append("资金回流")

        if theme == "非主线":
            reasons.append("未形成清晰主线结构")
        persistence_hint = _clamp01(max(ret20, 0.0) / 0.16) * 0.55 + _clamp01(max(slope20, 0.0) / 0.12) * 0.45
        breadth_hint = _clamp01(amount_score * 0.55 + _clamp01(turnover / 8.0) * 0.45)
        return {
            "theme": theme,
            "strength": round(strength, 4),
            "breadth_hint": round(breadth_hint, 4),
            "persistence_hint": round(_clamp01(persistence_hint), 4),
            "reason": "，".join(reasons),
        }

    @staticmethod
    def _resolve_market_theme_mode(top_themes: Sequence[Mapping[str, object]]) -> str:
        if not top_themes:
            return "weak"
        strongest = top_themes[0]
        strongest_strength = float(strongest.get("strength") or 0.0)
        strongest_breadth = float(strongest.get("breadth") or 0.0)
        if strongest_strength >= 0.72 or strongest_breadth >= 0.55:
            return "concentrated"
        if len(top_themes) >= 2 and float(top_themes[1].get("strength") or 0.0) >= 0.55:
            return "mixed"
        return "weak"
