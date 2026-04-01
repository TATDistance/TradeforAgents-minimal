from __future__ import annotations

from typing import Dict, Mapping, Sequence

from .event_bus import EventBus, RuntimeEvent
from .settings import Settings, load_settings
from .symbol_runtime_state import SymbolRuntimeStateStore
from .trigger_service import TriggerDecision, TriggerService


EVENT_TYPE_BY_REASON = {
    "PRICE_UPDATED": "PRICE_UPDATED",
    "FEATURE_CHANGED": "FEATURE_CHANGED",
    "MARKET_REGIME_CHANGED": "MARKET_REGIME_CHANGED",
    "POSITION_CHANGED": "POSITION_CHANGED",
    "PORTFOLIO_STATE_CHANGED": "PORTFOLIO_STATE_CHANGED",
    "PHASE_CHANGED": "PHASE_CHANGED",
}


class RealtimeEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        event_bus: EventBus | None = None,
        trigger_service: TriggerService | None = None,
        state_store: SymbolRuntimeStateStore | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.event_bus = event_bus or EventBus()
        self.trigger_service = trigger_service or TriggerService(self.settings)
        self.state_store = state_store or SymbolRuntimeStateStore()

    def select_symbols_for_cycle(
        self,
        *,
        symbols: Sequence[str],
        snapshot_rows: Mapping[str, Mapping[str, object]],
        feature_scores: Mapping[str, Mapping[str, object]],
        market_regime: str,
        portfolio_feedback: Mapping[str, object],
        phase_name: str,
    ) -> Dict[str, object]:
        trigger_decisions = self.trigger_service.detect(
            symbols=symbols,
            snapshot_rows=snapshot_rows,
            feature_scores=feature_scores,
            market_regime=market_regime,
            portfolio_feedback=portfolio_feedback,
            phase_name=phase_name,
            state_store=self.state_store,
        )
        for decision in trigger_decisions:
            for event_type in decision.event_types:
                self.event_bus.publish(
                    EVENT_TYPE_BY_REASON.get(event_type, event_type),
                    {
                        "symbol": decision.symbol,
                        "reasons": decision.reasons,
                        "priority": decision.priority,
                    },
                )
            self.state_store.mark_trigger(decision.symbol, decision.reasons)
        drained = self.event_bus.drain_events()
        changed_symbols = []
        seen = set()
        for event in drained:
            symbol = str(event.payload.get("symbol") or "")
            if symbol and symbol not in seen:
                changed_symbols.append(symbol)
                seen.add(symbol)
        return {
            "trigger_decisions": [
                {
                    "symbol": item.symbol,
                    "event_types": item.event_types,
                    "reasons": item.reasons,
                    "priority": item.priority,
                }
                for item in trigger_decisions
            ],
            "events": [self._serialize_event(event) for event in drained],
            "changed_symbols": changed_symbols,
            "runtime_states": self.state_store.export(),
        }

    @staticmethod
    def _serialize_event(event: RuntimeEvent) -> Dict[str, object]:
        return {
            "event_type": event.event_type,
            "payload": dict(event.payload),
            "ts": event.ts,
        }
