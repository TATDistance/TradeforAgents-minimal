from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping

from .db import fetch_rows_by_sql, write_adaptive_weight_record
from .realtime_ai_review_tracking_service import RealtimeAIReviewTrackingService
from .settings import Settings, load_settings
from .strategy_evaluation_service import StrategyEvaluationService


class AdaptiveWeightService:
    def __init__(self, settings: Settings | None = None, strategy_evaluation_service: StrategyEvaluationService | None = None) -> None:
        self.settings = settings or load_settings()
        self.strategy_evaluation_service = strategy_evaluation_service or StrategyEvaluationService(self.settings)
        self.realtime_ai_review_tracking_service = RealtimeAIReviewTrackingService(self.settings)

    def get_current_weights(self, conn=None) -> Dict[str, object]:
        cache_path = self._cache_path()
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and "ai_review_feedback" not in payload:
                    payload["ai_review_feedback"] = self._default_review_feedback()
                return payload
            except Exception:
                pass
        strategy_weights = {
            "momentum": 1.0,
            "dual_ma": 1.0,
            "macd_trend": 1.0,
            "mean_reversion": 1.0,
            "breakout": 1.0,
            "trend_pullback": 1.0,
        }
        return {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "strategy_weights": strategy_weights,
            "ai_score_multiplier": 1.0,
            "risk_penalty_multiplier": 1.0,
            "adjustments": [],
            "ai_review_feedback": self._default_review_feedback(),
        }

    def update_strategy_weights(self, conn) -> Dict[str, object]:
        current = self.get_current_weights(conn)
        performance = self.strategy_evaluation_service.evaluate_strategy_performance(
            conn,
            window_days=int(self.settings.adaptive.evaluation_window_days or 5),
        )
        updated_strategy_weights = dict(current.get("strategy_weights") or {})
        adjustments: List[Dict[str, object]] = []
        rate = float(self.settings.adaptive.weight_adjustment_rate or 0.1)
        min_trades = int(self.settings.adaptive.min_trades_for_adjustment or 10)
        for strategy_name, metrics in performance.items():
            old_value = float(updated_strategy_weights.get(strategy_name, 1.0))
            trades = int(metrics.get("trades") or 0)
            win_rate = float(metrics.get("win_rate") or 0.0)
            avg_return = float(metrics.get("avg_return") or 0.0)
            adjusted_value = old_value
            reason = "样本不足，保持原权重"
            if trades >= min_trades:
                if win_rate < 0.40 or avg_return < -0.01:
                    adjusted_value = old_value * 0.90
                    reason = "连续表现偏弱，降低策略权重"
                elif win_rate > 0.60 and avg_return > 0:
                    adjusted_value = old_value * 1.10
                    reason = "近期表现稳定，提升策略权重"
                else:
                    adjusted_value = old_value
                    reason = "表现中性，维持当前策略权重"
            new_value = old_value * (1.0 - rate) + adjusted_value * rate
            updated_strategy_weights[strategy_name] = round(new_value, 4)
            if abs(new_value - old_value) >= 0.0001:
                adjustments.append(
                    {
                        "category": "strategy_weight",
                        "key": strategy_name,
                        "old_value": round(old_value, 4),
                        "target_value": round(adjusted_value, 4),
                        "new_value": round(new_value, 4),
                        "reason": reason,
                    }
                )
                write_adaptive_weight_record(
                    conn,
                    record=self._build_record("strategy_weight", strategy_name, old_value, adjusted_value, new_value, reason, metrics),
                )

        ai_old = float(current.get("ai_score_multiplier") or 1.0)
        risk_old = float(current.get("risk_penalty_multiplier") or 1.0)
        aggregate = self._aggregate_performance(performance)
        review_feedback = self.realtime_ai_review_tracking_service.build_learning_feedback(
            conn,
            limit=max(60, int(self.settings.adaptive.evaluation_window_days or 5) * 30),
        )
        ai_target = 1.0
        risk_target = 1.0
        if aggregate["win_rate"] > 0.58 and aggregate["avg_return"] > 0:
            ai_target = 1.08
            risk_target = 0.96
        elif aggregate["win_rate"] < 0.42 or aggregate["avg_return"] < -0.005:
            ai_target = 0.95
            risk_target = 1.06
        ai_target = self._clamp_multiplier(ai_target + float(review_feedback.get("ai_multiplier_bias") or 0.0), floor=0.9, ceil=1.15)
        risk_target = self._clamp_multiplier(risk_target + float(review_feedback.get("risk_multiplier_bias") or 0.0), floor=0.92, ceil=1.15)
        ai_new = ai_old * (1.0 - rate) + ai_target * rate
        risk_new = risk_old * (1.0 - rate) + risk_target * rate
        if abs(ai_new - ai_old) >= 0.0001:
            ai_reason = self._compose_multiplier_reason(
                base_reason="根据整体策略近期表现平滑调整 AI 加分权重",
                review_feedback=review_feedback,
                bias_key="ai_multiplier_bias",
            )
            adjustments.append(
                {
                    "category": "ai_score_multiplier",
                    "key": "ai_score_multiplier",
                    "old_value": round(ai_old, 4),
                    "target_value": round(ai_target, 4),
                    "new_value": round(ai_new, 4),
                    "reason": ai_reason,
                }
            )
            write_adaptive_weight_record(
                conn,
                self._build_record("ai_score_multiplier", "ai_score_multiplier", ai_old, ai_target, ai_new, ai_reason, {**aggregate, "ai_review_feedback": review_feedback}),
            )
        if abs(risk_new - risk_old) >= 0.0001:
            risk_reason = self._compose_multiplier_reason(
                base_reason="根据整体策略近期表现平滑调整风险惩罚权重",
                review_feedback=review_feedback,
                bias_key="risk_multiplier_bias",
            )
            adjustments.append(
                {
                    "category": "risk_penalty_multiplier",
                    "key": "risk_penalty_multiplier",
                    "old_value": round(risk_old, 4),
                    "target_value": round(risk_target, 4),
                    "new_value": round(risk_new, 4),
                    "reason": risk_reason,
                }
            )
            write_adaptive_weight_record(
                conn,
                self._build_record("risk_penalty_multiplier", "risk_penalty_multiplier", risk_old, risk_target, risk_new, risk_reason, {**aggregate, "ai_review_feedback": review_feedback}),
            )

        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "strategy_weights": updated_strategy_weights,
            "ai_score_multiplier": round(ai_new, 4),
            "risk_penalty_multiplier": round(risk_new, 4),
            "adjustments": adjustments,
            "summary": aggregate,
            "ai_review_feedback": review_feedback,
        }
        self._cache_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def history(self, conn, limit: int = 120) -> List[Dict[str, object]]:
        return [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                "SELECT * FROM adaptive_weight_history ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            )
        ]

    def _cache_path(self) -> Path:
        return self.settings.cache_dir / "adaptive_weights.json"

    @staticmethod
    def _clamp_multiplier(value: float, *, floor: float, ceil: float) -> float:
        return max(floor, min(ceil, value))

    @staticmethod
    def _aggregate_performance(performance: Mapping[str, Mapping[str, object]]) -> Dict[str, float]:
        if not performance:
            return {"win_rate": 0.0, "avg_return": 0.0, "trades": 0.0}
        items = list(performance.values())
        return {
            "win_rate": sum(float(item.get("win_rate") or 0.0) for item in items) / len(items),
            "avg_return": sum(float(item.get("avg_return") or 0.0) for item in items) / len(items),
            "trades": sum(float(item.get("trades") or 0.0) for item in items),
        }

    @staticmethod
    def _default_review_feedback() -> Dict[str, object]:
        return {
            "evaluated_count": 0,
            "positive_close_count": 0,
            "avg_benefit_close": 0.0,
            "avg_benefit_next_close": 0.0,
            "positive_rate": 0.0,
            "role_stats": {},
            "top_regime": "",
            "ai_multiplier_bias": 0.0,
            "risk_multiplier_bias": 0.0,
            "suggestions": [],
        }

    @staticmethod
    def _compose_multiplier_reason(
        *,
        base_reason: str,
        review_feedback: Mapping[str, object],
        bias_key: str,
    ) -> str:
        sample_count = int(review_feedback.get("evaluated_count") or 0)
        bias = float(review_feedback.get(bias_key) or 0.0)
        if sample_count <= 0 or abs(bias) < 0.0001:
            return base_reason
        direction = "增强" if bias > 0 else "收敛"
        return f"{base_reason}；结合最近 {sample_count} 条实时终审收益反馈，进一步{direction}该项倍率。"

    @staticmethod
    def _build_record(category: str, key_name: str, old_value: float, target_value: float, new_value: float, reason: str, metadata: Mapping[str, object]):
        from .models import AdaptiveWeightRecord

        return AdaptiveWeightRecord(
            category=category,
            key_name=key_name,
            old_value=round(old_value, 6),
            target_value=round(target_value, 6),
            new_value=round(new_value, 6),
            reason=reason,
            metadata_json=json.dumps(dict(metadata), ensure_ascii=False),
        )
