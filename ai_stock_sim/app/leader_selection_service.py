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


class LeaderSelectionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def classify(
        self,
        snapshot: pd.DataFrame,
        *,
        theme_report: Mapping[str, object],
        technical_map: Mapping[str, Mapping[str, float]] | None = None,
        feature_map: Mapping[str, Sequence[StrategyFeature]] | None = None,
    ) -> Dict[str, Dict[str, object]]:
        if snapshot.empty or not self.settings.leader_filter.enabled:
            return {}

        technical_map = technical_map or {}
        symbol_themes = (theme_report.get("symbol_themes") or {}) if isinstance(theme_report, Mapping) else {}
        grouped: Dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for _, row in snapshot.iterrows():
            symbol = str(row.get("symbol") or "").strip()
            theme_name = str((symbol_themes.get(symbol) or {}).get("theme") or "非主线")
            grouped[theme_name].append(dict(row))

        results: Dict[str, Dict[str, object]] = {}
        for theme_name, members in grouped.items():
            if theme_name == "非主线":
                for row in members:
                    symbol = str(row.get("symbol") or "").strip()
                    results[symbol] = {
                        "symbol": symbol,
                        "theme": theme_name,
                        "leader_rank_score": 0.0,
                        "role": "non_theme",
                        "reason": "不属于当前强主线",
                    }
                continue
            amount_max = max(_safe_float(item.get("amount")) for item in members) or 1.0
            pct_max = max(_safe_float(item.get("pct_change")) for item in members) or 1.0
            turnover_max = max(_safe_float(item.get("turnover_rate")) for item in members) or 1.0
            for row in members:
                symbol = str(row.get("symbol") or "").strip()
                technical = dict(technical_map.get(symbol) or {})
                slope20 = _safe_float(technical.get("trend_slope_20d"))
                ret20 = _safe_float(technical.get("ret_20d"))
                amount_score = _clamp01(_safe_float(row.get("amount")) / amount_max)
                pct_score = _clamp01(_safe_float(row.get("pct_change")) / max(pct_max, 1.0))
                turnover_score = _clamp01(_safe_float(row.get("turnover_rate")) / max(turnover_max, 1.0))
                persistence = _clamp01(max(slope20, 0.0) / 0.12) * 0.55 + _clamp01(max(ret20, 0.0) / 0.18) * 0.45
                rank_score = _clamp01(amount_score * 0.32 + pct_score * 0.28 + turnover_score * 0.15 + persistence * 0.25)
                role = "leader"
                if rank_score < 0.78:
                    role = "strong_follower"
                if rank_score < 0.58:
                    role = "weak_follower"
                if rank_score < 0.36:
                    role = "non_theme"
                reason_bits = []
                if amount_score >= 0.8:
                    reason_bits.append("成交额靠前")
                if pct_score >= 0.8:
                    reason_bits.append("涨幅领先")
                if persistence >= 0.55:
                    reason_bits.append("趋势延续性强")
                results[symbol] = {
                    "symbol": symbol,
                    "theme": theme_name,
                    "leader_rank_score": round(rank_score, 4),
                    "role": role,
                    "reason": "，".join(reason_bits[:3]) or "主题内表现一般",
                }
        return results
