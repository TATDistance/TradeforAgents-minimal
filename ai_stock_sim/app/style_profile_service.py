from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .db import fetch_rows_by_sql, write_style_profile
from .models import StyleProfileState
from .settings import Settings, load_settings


class StyleProfileService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def determine_style(
        self,
        market_regime: Mapping[str, object],
        portfolio_feedback: Mapping[str, object] | None = None,
        adaptive_weights: Mapping[str, object] | None = None,
    ) -> StyleProfileState:
        regime = str(market_regime.get("regime") or self.settings.market_regime.default_regime)
        risk_bias = str(market_regime.get("risk_bias") or "NORMAL").upper()
        drawdown = float((portfolio_feedback or {}).get("drawdown") or 0.0)
        ai_multiplier = float((adaptive_weights or {}).get("ai_score_multiplier") or 1.0)
        if regime in {"HIGH_VOLATILITY", "RISK_OFF"} or risk_bias == "RISK_OFF":
            return StyleProfileState(
                style="short_term",
                holding_preference="short",
                aggressiveness="low" if drawdown > 0.03 else "medium",
                market_regime=regime,
                reason="当前市场波动较大，更适合偏短线、快进快出的执行风格。",
                metadata_json=json.dumps({"risk_bias": risk_bias, "ai_multiplier": ai_multiplier}, ensure_ascii=False),
            )
        if regime in {"TRENDING_UP", "TRENDING_DOWN"}:
            return StyleProfileState(
                style="trend_following",
                holding_preference="long",
                aggressiveness="medium" if ai_multiplier <= 1.0 else "high",
                market_regime=regime,
                reason="当前市场更偏趋势演绎，AI 倾向拉长持有周期并顺势跟随。",
                metadata_json=json.dumps({"risk_bias": risk_bias, "ai_multiplier": ai_multiplier}, ensure_ascii=False),
            )
        return StyleProfileState(
            style="balanced",
            holding_preference="medium",
            aggressiveness="medium",
            market_regime=regime,
            reason="市场尚未形成强趋势，AI 维持中性平衡风格。",
            metadata_json=json.dumps({"risk_bias": risk_bias, "ai_multiplier": ai_multiplier}, ensure_ascii=False),
        )

    def save(self, conn, profile: StyleProfileState) -> int:
        cache_path = self._cache_path()
        cache_path.write_text(json.dumps(profile.model_dump(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return write_style_profile(conn, profile)

    def load(self) -> StyleProfileState:
        cache_path = self._cache_path()
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                return StyleProfileState(**payload)
            except Exception:
                pass
        return StyleProfileState(style="balanced", holding_preference="medium", aggressiveness="medium", reason="暂无风格缓存", market_regime="")

    def history(self, conn, limit: int = 50) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                "SELECT * FROM style_profile_history ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            )
        ]

    def _cache_path(self) -> Path:
        return self.settings.cache_dir / "style_profile_state.json"
