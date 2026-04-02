from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping

from .db import fetch_rows_by_sql, write_adaptive_weight_record
from .settings import Settings, load_settings
from .strategy_evaluation_service import StrategyEvaluationService


class AdaptiveWeightService:
    def __init__(self, settings: Settings | None = None, strategy_evaluation_service: StrategyEvaluationService | None = None) -> None:
        self.settings = settings or load_settings()
        self.strategy_evaluation_service = strategy_evaluation_service or StrategyEvaluationService(self.settings)

    def get_current_weights(self, conn=None) -> Dict[str, object]:
        cache_path = self._cache_path()
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
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
        ai_target = 1.0
        risk_target = 1.0
        if aggregate["win_rate"] > 0.58 and aggregate["avg_return"] > 0:
            ai_target = 1.08
            risk_target = 0.96
        elif aggregate["win_rate"] < 0.42 or aggregate["avg_return"] < -0.005:
            ai_target = 0.95
            risk_target = 1.06
        ai_new = ai_old * (1.0 - rate) + ai_target * rate
        risk_new = risk_old * (1.0 - rate) + risk_target * rate
        if abs(ai_new - ai_old) >= 0.0001:
            adjustments.append(
                {
                    "category": "ai_score_multiplier",
                    "key": "ai_score_multiplier",
                    "old_value": round(ai_old, 4),
                    "target_value": round(ai_target, 4),
                    "new_value": round(ai_new, 4),
                    "reason": "根据整体策略近期表现平滑调整 AI 加分权重",
                }
            )
            write_adaptive_weight_record(
                conn,
                self._build_record("ai_score_multiplier", "ai_score_multiplier", ai_old, ai_target, ai_new, "根据整体策略近期表现平滑调整 AI 加分权重", aggregate),
            )
        if abs(risk_new - risk_old) >= 0.0001:
            adjustments.append(
                {
                    "category": "risk_penalty_multiplier",
                    "key": "risk_penalty_multiplier",
                    "old_value": round(risk_old, 4),
                    "target_value": round(risk_target, 4),
                    "new_value": round(risk_new, 4),
                    "reason": "根据整体策略近期表现平滑调整风险惩罚权重",
                }
            )
            write_adaptive_weight_record(
                conn,
                self._build_record("risk_penalty_multiplier", "risk_penalty_multiplier", risk_old, risk_target, risk_new, "根据整体策略近期表现平滑调整风险惩罚权重", aggregate),
            )

        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "strategy_weights": updated_strategy_weights,
            "ai_score_multiplier": round(ai_new, 4),
            "risk_penalty_multiplier": round(risk_new, 4),
            "adjustments": adjustments,
            "summary": aggregate,
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
