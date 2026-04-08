from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Mapping, Sequence

import pandas as pd

from .candidate_quality_service import CandidateQualityService
from .decision_context_builder import DecisionContextBuilder
from .leader_selection_service import LeaderSelectionService
from .market_data_service import MarketDataService
from .settings import Settings, load_settings
from .strategy_engine import StrategyEngine
from .theme_detection_service import ThemeDetectionService
from .watchlist_policy import WatchlistPolicy


class IntradaySelectorService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        market_data: MarketDataService | None = None,
        strategy_engine: StrategyEngine | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.market_data = market_data or MarketDataService(self.settings)
        self.strategy_engine = strategy_engine or StrategyEngine(self.settings, self.market_data)
        self.policy = WatchlistPolicy.from_settings(self.settings)
        self.theme_detection = ThemeDetectionService(self.settings)
        self.leader_selection = LeaderSelectionService(self.settings)
        self.candidate_quality = CandidateQualityService(self.settings)

    def scan(
        self,
        snapshot: pd.DataFrame,
        *,
        current_watchlist: Sequence[str],
        current_positions: Sequence[str],
        market_regime: Mapping[str, object] | str,
    ) -> Dict[str, object]:
        now = datetime.now().isoformat(timespec="seconds")
        if snapshot.empty:
            return {"scan_time": now, "candidates": [], "reason": "实时快照为空"}

        excluded = {str(symbol).strip() for symbol in list(current_watchlist) + list(current_positions) if str(symbol).strip()}
        ranked = snapshot.copy()
        ranked = ranked[~ranked["symbol"].astype(str).isin(excluded)]
        ranked = ranked[ranked["amount"] >= self.settings.min_turnover]
        ranked = ranked[~ranked["is_st"]]
        if ranked.empty:
            return {"scan_time": now, "candidates": [], "reason": "当前无可加入监控池的新股票"}

        ranked = ranked.sort_values(["amount", "pct_change"], ascending=[False, False]).head(max(self.policy.max_watchlist_size * 2, 40))
        top_amount = max(float(ranked["amount"].max() or 0.0), 1.0)
        regime_name = market_regime.get("regime") if isinstance(market_regime, Mapping) else str(market_regime)
        feature_map: Dict[str, object] = {}
        technical_map: Dict[str, Dict[str, float]] = {}
        history_map: Dict[str, pd.DataFrame] = {}
        for _, row in ranked.iterrows():
            symbol = str(row["symbol"])
            asset_type = str(row.get("asset_type") or "stock")
            try:
                frame = self.market_data.fetch_history_daily(symbol=symbol, asset_type=asset_type, limit=160)
            except Exception:
                frame = pd.DataFrame()
            history_map[symbol] = frame
            if frame.empty:
                feature_map[symbol] = []
                technical_map[symbol] = {}
                continue
            feature_map[symbol] = self.strategy_engine.run_features_for_symbol_on_frame(symbol, frame)
            technical_map[symbol] = DecisionContextBuilder._technical_features(frame)
        theme_report = self.theme_detection.detect(ranked, technical_map=technical_map, feature_map=feature_map)
        leader_map = self.leader_selection.classify(ranked, theme_report=theme_report, technical_map=technical_map, feature_map=feature_map)
        quality_map = self.candidate_quality.evaluate_batch(
            ranked,
            technical_map=technical_map,
            theme_report=theme_report,
            leader_map=leader_map,
            market_regime=market_regime,
        )
        candidates: List[Dict[str, object]] = []
        for _, row in ranked.iterrows():
            symbol = str(row["symbol"])
            asset_type = str(row.get("asset_type") or "stock")
            amount_score = min(1.0, float(row.get("amount") or 0.0) / top_amount)
            pct_change = float(row.get("pct_change") or 0.0)
            pct_component = max(0.0, min(1.0, pct_change / 8.0))
            turnover_component = max(0.0, min(1.0, float(row.get("turnover_rate") or 0.0) / 8.0))
            frame = history_map.get(symbol, pd.DataFrame())
            feature_bonus = 0.0
            reason_bits: List[str] = []
            if not frame.empty:
                features = feature_map.get(symbol, [])
                positive_scores = [max(0.0, float(item.score or 0.0)) for item in features if str(item.direction) == "LONG"]
                feature_bonus = (sum(positive_scores) / len(positive_scores)) if positive_scores else 0.0
                strongest = max(features, key=lambda item: float(item.score or 0.0), default=None)
                if strongest is not None and strongest.score > 0:
                    reason_bits.append(f"{strongest.strategy_name} 转强")
            theme_info = dict((theme_report.get("symbol_themes") or {}).get(symbol) or {})
            leader_info = dict(leader_map.get(symbol) or {})
            quality_info = dict(quality_map.get(symbol) or {})
            quality_score = float(quality_info.get("quality_score") or 0.0)
            if self.settings.candidate_quality.enabled and not bool(quality_info.get("passed", False)):
                continue
            if (
                self.settings.leader_filter.enabled
                and self.settings.leader_filter.suppress_weak_followers
                and str(leader_info.get("role") or "") in {"weak_follower", "non_theme"}
                and float(theme_info.get("strength") or 0.0) < float(self.settings.theme_detection.min_theme_strength)
            ):
                continue
            regime_bonus = 0.08 if regime_name == "TRENDING_UP" else (-0.08 if regime_name in {"HIGH_VOLATILITY", "RISK_OFF"} else 0.0)
            theme_strength = float(theme_info.get("strength") or 0.0)
            leader_rank = float(leader_info.get("leader_rank_score") or 0.0)
            score = max(
                0.0,
                min(
                    1.0,
                    pct_component * 0.18
                    + amount_score * 0.18
                    + turnover_component * 0.10
                    + feature_bonus * 0.26
                    + theme_strength * 0.10
                    + leader_rank * 0.08
                    + quality_score * 0.10
                    + regime_bonus,
                ),
            )
            if score < self.policy.min_score_to_add * 0.72:
                continue
            if pct_change > 0:
                reason_bits.append(f"盘中涨幅 {pct_change:.2f}%")
            if float(row.get("amount") or 0.0) >= top_amount * 0.6:
                reason_bits.append("成交额排名靠前")
            theme_name = str(theme_info.get("theme") or "")
            if theme_name and theme_name != "非主线":
                reason_bits.append(f"主线:{theme_name}")
            role = str(leader_info.get("role") or "")
            if role:
                reason_bits.append(f"角色:{role}")
            for item in list(quality_info.get("filter_reasons") or [])[:2]:
                reason_bits.append(str(item))
            candidates.append(
                {
                    "symbol": symbol,
                    "name": str(row.get("name") or symbol),
                    "score": round(score, 4),
                    "source": "intraday_scan",
                    "discovered_at": now,
                    "reason": "，".join(reason_bits[:3]) or "盘中动态扫描发现强势新机会",
                    "theme": theme_name or "非主线",
                    "theme_strength": round(theme_strength, 4),
                    "leader_role": role or "non_theme",
                    "leader_rank_score": round(leader_rank, 4),
                    "quality_score": round(quality_score, 4),
                    "quality_passed": bool(quality_info.get("passed", False)),
                    "filter_reasons": list(quality_info.get("filter_reasons") or []),
                }
            )
        candidates.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("symbol") or "")), reverse=True)
        return {
            "scan_time": now,
            "candidates": candidates[: self.policy.max_new_symbols_per_scan],
            "reason": "盘中动态扫描完成",
            "market_theme_mode": str(theme_report.get("market_theme_mode") or "weak"),
            "top_themes": list(theme_report.get("top_themes") or []),
        }
