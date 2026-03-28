from __future__ import annotations

from typing import Dict, Iterable, List, Mapping

from .ai_engine_protocol import AIDecisionEngineOutput
from .models import FinalSignal


class DecisionCompareService:
    def compare(
        self,
        legacy_signals: Iterable[FinalSignal],
        engine_decisions: Mapping[str, AIDecisionEngineOutput],
    ) -> Dict[str, object]:
        legacy_map = {signal.symbol: signal for signal in legacy_signals}
        symbols = sorted(set(legacy_map.keys()) | set(engine_decisions.keys()))
        rows: List[Dict[str, object]] = []
        diff_count = 0
        for symbol in symbols:
            legacy = legacy_map.get(symbol)
            engine = engine_decisions.get(symbol)
            legacy_action = legacy.action if legacy else "NONE"
            engine_action = engine.action if engine else "NONE"
            different = legacy_action != engine_action
            if different:
                diff_count += 1
            rows.append(
                {
                    "symbol": symbol,
                    "legacy_action": legacy_action,
                    "legacy_confidence": round(float(legacy.confidence), 4) if legacy else 0.0,
                    "new_action": engine_action,
                    "new_confidence": round(float(engine.confidence), 4) if engine else 0.0,
                    "different": different,
                    "legacy_reason": legacy.ai_reason or legacy.strategy_reason if legacy else "",
                    "new_reason": engine.reason if engine else "",
                }
            )
        return {
            "rows": rows,
            "summary": f"对照模式共比较 {len(symbols)} 只标的，动作差异 {diff_count} 只。",
            "diff_count": diff_count,
            "total": len(symbols),
        }
