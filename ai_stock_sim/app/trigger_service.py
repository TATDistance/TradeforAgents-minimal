from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Sequence

from .settings import Settings, load_settings
from .symbol_runtime_state import SymbolRuntimeStateStore


@dataclass
class TriggerDecision:
    symbol: str
    event_types: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    priority: int = 0


class TriggerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def detect(
        self,
        *,
        symbols: Sequence[str],
        snapshot_rows: Mapping[str, Mapping[str, object]],
        feature_scores: Mapping[str, Mapping[str, object]],
        market_regime: str,
        portfolio_feedback: Mapping[str, object],
        phase_name: str,
        state_store: SymbolRuntimeStateStore,
    ) -> List[TriggerDecision]:
        decisions: List[TriggerDecision] = []
        now = datetime.now()
        positions = {
            str(item.get("symbol")): int(item.get("qty") or 0)
            for item in (portfolio_feedback.get("positions_detail") or [])
            if isinstance(item, Mapping)
        }
        cash_pct = float(portfolio_feedback.get("cash_pct", 0.0) or 0.0)
        for symbol in symbols:
            snapshot = dict(snapshot_rows.get(symbol) or {})
            fusion = dict(feature_scores.get(symbol) or {})
            previous = state_store.get(symbol)
            reasons: List[str] = []
            event_types: List[str] = []
            priority = 0
            if previous is None:
                reasons.append("首次进入实时决策池")
                event_types.append("PRICE_UPDATED")
                priority += 5
            price = float(snapshot.get("latest_price") or 0.0)
            pct_change = float(snapshot.get("pct_change") or 0.0)
            amount = float(snapshot.get("amount") or 0.0)
            feature_score = float(fusion.get("feature_score") or 0.0)
            if previous is not None:
                if self._crossed_price_threshold(previous.last_price, price):
                    reasons.append("价格变化超过触发阈值")
                    event_types.append("PRICE_UPDATED")
                    priority += 4
                if abs(pct_change - previous.last_pct_change) >= self.settings.trigger.pct_change_delta_threshold:
                    reasons.append("涨跌幅变化超过阈值")
                    event_types.append("PRICE_UPDATED")
                    priority += 3
                if self._crossed_amount_threshold(previous.last_amount, amount):
                    reasons.append("成交额变化超过阈值")
                    event_types.append("PRICE_UPDATED")
                    priority += 2
                has_feature_state = any(
                    abs(value) > 0
                    for value in (previous.last_feature_score, previous.last_setup_score, previous.last_execution_score, previous.last_ai_score)
                )
                if has_feature_state and abs(feature_score - previous.last_feature_score) >= self.settings.trigger.feature_score_delta_threshold:
                    reasons.append("特征分发生明显变化")
                    event_types.append("FEATURE_CHANGED")
                    priority += 4
                if previous.last_market_regime and previous.last_market_regime != market_regime:
                    reasons.append(f"市场状态切换为 {market_regime}")
                    event_types.append("MARKET_REGIME_CHANGED")
                    priority += 5
                if previous.last_phase and previous.last_phase != phase_name:
                    reasons.append(f"交易阶段切换为 {phase_name}")
                    event_types.append("PHASE_CHANGED")
                    priority += 5
                previous_qty = int(previous.last_position_qty or 0)
                current_qty = positions.get(symbol, 0)
                if current_qty != previous_qty:
                    reasons.append("持仓数量发生变化")
                    event_types.append("POSITION_CHANGED")
                    priority += 4
                if previous.last_cash_pct > 0 and abs(cash_pct - previous.last_cash_pct) >= self.settings.trigger.portfolio_state_delta_threshold:
                    reasons.append("账户现金比例变化较大")
                    event_types.append("PORTFOLIO_STATE_CHANGED")
                    priority += 2
                if self._is_stale(previous.last_trigger_at, now):
                    reasons.append("触发状态过久，执行一次刷新决策")
                    event_types.append("FEATURE_CHANGED")
                    priority = max(priority, 1)

            if not reasons:
                state_store.update_market(
                    symbol,
                    price=price,
                    pct_change=pct_change,
                    amount=amount,
                    phase=phase_name,
                    market_regime=market_regime,
                )
                continue

            if previous is not None and not self._cooldown_expired(previous.last_trigger_at, now) and not self._has_strong_reason(event_types):
                state_store.update_market(
                    symbol,
                    price=price,
                    pct_change=pct_change,
                    amount=amount,
                    phase=phase_name,
                    market_regime=market_regime,
                )
                continue

            state_store.update_market(
                symbol,
                price=price,
                pct_change=pct_change,
                amount=amount,
                phase=phase_name,
                market_regime=market_regime,
            )
            decisions.append(
                TriggerDecision(
                    symbol=symbol,
                    event_types=list(dict.fromkeys(event_types)),
                    reasons=reasons,
                    priority=priority,
                )
            )
        decisions.sort(key=lambda item: (-item.priority, item.symbol))
        return decisions

    def _crossed_price_threshold(self, previous: float, current: float) -> bool:
        if previous <= 0 or current <= 0:
            return False
        return abs(current - previous) / previous >= self.settings.trigger.price_change_threshold_pct

    def _crossed_amount_threshold(self, previous: float, current: float) -> bool:
        if previous <= 0 or current <= 0:
            return False
        return abs(current - previous) / previous >= self.settings.trigger.amount_delta_threshold

    def _cooldown_expired(self, last_trigger_at: str | None, now: datetime) -> bool:
        if not last_trigger_at:
            return True
        try:
            previous = datetime.fromisoformat(last_trigger_at)
        except Exception:
            return True
        return (now - previous).total_seconds() >= self.settings.trigger.cooldown_seconds

    def _is_stale(self, last_trigger_at: str | None, now: datetime) -> bool:
        if not last_trigger_at:
            return False
        try:
            previous = datetime.fromisoformat(last_trigger_at)
        except Exception:
            return False
        return (now - previous).total_seconds() >= self.settings.trigger.stale_refresh_seconds

    @staticmethod
    def _has_strong_reason(event_types: Iterable[str]) -> bool:
        strong = {"MARKET_REGIME_CHANGED", "PHASE_CHANGED", "POSITION_CHANGED", "PRICE_UPDATED"}
        return any(event_type in strong for event_type in event_types)
