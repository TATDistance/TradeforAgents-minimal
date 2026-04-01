from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class SymbolRuntimeState:
    symbol: str
    last_price: float = 0.0
    last_pct_change: float = 0.0
    last_amount: float = 0.0
    last_feature_score: float = 0.0
    last_setup_score: float = 0.0
    last_execution_score: float = 0.0
    last_ai_score: float = 0.0
    last_ai_action: str = "HOLD"
    last_trigger_at: Optional[str] = None
    last_trigger_reasons: List[str] = field(default_factory=list)
    last_market_regime: str = ""
    last_phase: str = ""
    last_position_qty: int = 0
    last_cash_pct: float = 0.0
    updated_at: Optional[str] = None

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


class SymbolRuntimeStateStore:
    def __init__(self) -> None:
        self._states: Dict[str, SymbolRuntimeState] = {}

    def get(self, symbol: str) -> Optional[SymbolRuntimeState]:
        return self._states.get(symbol)

    def ensure(self, symbol: str) -> SymbolRuntimeState:
        state = self._states.get(symbol)
        if state is None:
            state = SymbolRuntimeState(symbol=symbol)
            self._states[symbol] = state
        return state

    def update_market(self, symbol: str, *, price: float, pct_change: float, amount: float, phase: str, market_regime: str) -> SymbolRuntimeState:
        state = self.ensure(symbol)
        state.last_price = float(price or 0.0)
        state.last_pct_change = float(pct_change or 0.0)
        state.last_amount = float(amount or 0.0)
        state.last_phase = phase
        state.last_market_regime = market_regime
        state.touch()
        return state

    def update_scores(
        self,
        symbol: str,
        *,
        feature_score: float,
        setup_score: float,
        execution_score: float,
        ai_score: float,
        ai_action: str,
        position_qty: int,
        cash_pct: float,
    ) -> SymbolRuntimeState:
        state = self.ensure(symbol)
        state.last_feature_score = float(feature_score or 0.0)
        state.last_setup_score = float(setup_score or 0.0)
        state.last_execution_score = float(execution_score or 0.0)
        state.last_ai_score = float(ai_score or 0.0)
        state.last_ai_action = ai_action
        state.last_position_qty = int(position_qty or 0)
        state.last_cash_pct = float(cash_pct or 0.0)
        state.touch()
        return state

    def mark_trigger(self, symbol: str, reasons: List[str]) -> SymbolRuntimeState:
        state = self.ensure(symbol)
        state.last_trigger_at = datetime.now().isoformat(timespec="seconds")
        state.last_trigger_reasons = list(reasons)
        state.touch()
        return state

    def export(self) -> Dict[str, Dict[str, object]]:
        return {symbol: state.as_dict() for symbol, state in self._states.items()}
