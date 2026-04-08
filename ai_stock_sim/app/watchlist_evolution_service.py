from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Mapping, Sequence

from .settings import Settings, load_settings
from .watchlist_policy import WatchlistPolicy
from .watchlist_service import WatchlistPayload


class WatchlistEvolutionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.policy = WatchlistPolicy.from_settings(self.settings)

    def evolve(
        self,
        current_watchlist: WatchlistPayload,
        *,
        opportunity_pool: Sequence[Mapping[str, object]],
        runtime_states: Mapping[str, Mapping[str, object]],
        ai_decisions: Mapping[str, Mapping[str, object]] | None = None,
        holdings: Sequence[str],
        reference_time: datetime | None = None,
    ) -> Dict[str, object]:
        now = reference_time or datetime.now()
        current_symbols = [str(symbol).strip() for symbol in list(current_watchlist.get("symbols") or []) if str(symbol).strip()]
        holding_symbols = [str(symbol).strip() for symbol in holdings if str(symbol).strip()]
        ai_decisions = ai_decisions or {}
        current_set = set(current_symbols)
        keep_priority: Dict[str, float] = {}
        reasons: Dict[str, str] = {}

        def score_of(symbol: str) -> tuple[float, float]:
            state = dict(runtime_states.get(symbol) or {})
            decision = dict(ai_decisions.get(symbol) or {})
            execution = float(decision.get("execution_score") or state.get("last_execution_score") or 0.0)
            setup = float(decision.get("setup_score") or state.get("last_setup_score") or 0.0)
            return setup, execution

        for symbol in set(current_symbols + holding_symbols):
            setup_score, execution_score = score_of(symbol)
            state = dict(runtime_states.get(symbol) or {})
            last_trigger = str(state.get("last_trigger_at") or "")
            recent_action = bool(last_trigger)
            priority = execution_score * 1.6 + setup_score
            if symbol in holding_symbols:
                priority += 2.0
                reasons[symbol] = "当前持仓，强制保留在监控池"
            elif execution_score >= self.policy.min_score_to_add:
                priority += 1.0
                reasons[symbol] = "execution_score 较高，继续重点跟踪"
            elif setup_score >= self.policy.min_score_to_keep:
                priority += 0.5
                reasons[symbol] = "setup_score 仍高于保留阈值"
            elif recent_action:
                priority += 0.4
                reasons[symbol] = "最近刚触发过动作或事件，继续观察"
            else:
                reasons[symbol] = "当前维持在观察池，等待进一步确认"
            keep_priority[symbol] = priority

        added: List[str] = []
        for item in opportunity_pool:
            symbol = str(item.get("symbol") or "").strip()
            if not symbol or symbol in current_set:
                continue
            score = float(item.get("score") or 0.0)
            quality_passed = bool(item.get("quality_passed", True))
            quality_score = float(item.get("quality_score") or 0.0)
            leader_role = str(item.get("leader_role") or "")
            theme_name = str(item.get("theme") or "")
            if not quality_passed:
                continue
            if self.settings.leader_filter.enabled and self.settings.leader_filter.suppress_weak_followers and leader_role in {"weak_follower", "non_theme"}:
                continue
            if score < self.policy.min_score_to_add:
                continue
            if len(added) >= self.policy.max_new_symbols_per_scan:
                break
            current_symbols.append(symbol)
            current_set.add(symbol)
            role_bonus = 0.25 if leader_role == "leader" else 0.12 if leader_role == "strong_follower" else 0.0
            theme_bonus = 0.1 if theme_name and theme_name != "非主线" else 0.0
            keep_priority[symbol] = max(keep_priority.get(symbol, 0.0), score + quality_score * 0.6 + 1.0 + role_bonus + theme_bonus)
            reasons[symbol] = str(item.get("reason") or "盘中动态扫描发现强势新机会，加入监控池")
            added.append(symbol)

        removable: List[str] = []
        for symbol in current_symbols:
            if symbol in holding_symbols:
                continue
            if symbol in added:
                continue
            setup_score, execution_score = score_of(symbol)
            if execution_score >= self.policy.min_score_to_keep or setup_score >= self.policy.min_score_to_keep:
                continue
            state = dict(runtime_states.get(symbol) or {})
            updated_at = str(state.get("updated_at") or current_watchlist.get("generated_at") or "")
            if updated_at:
                try:
                    if datetime.fromisoformat(updated_at) > now - timedelta(minutes=self.policy.grace_period_minutes):
                        continue
                except Exception:
                    pass
            removable.append(symbol)
            reasons.setdefault(symbol, "长期低分且无持仓，准备移出监控池")

        removable.sort(key=lambda symbol: keep_priority.get(symbol, 0.0))
        removed = removable[: self.policy.max_remove_symbols_per_scan]
        final_symbols = [symbol for symbol in current_symbols if symbol not in removed]
        final_symbols.sort(key=lambda symbol: keep_priority.get(symbol, 0.0), reverse=True)
        final_symbols = final_symbols[: self.policy.max_watchlist_size]
        for symbol in holding_symbols:
            if symbol not in final_symbols:
                final_symbols.append(symbol)
                reasons[symbol] = "当前持仓，强制回补到监控池"

        result: WatchlistPayload = {
            "symbols": final_symbols,
            "source": "watchlist_evolution",
            "generated_at": now.isoformat(timespec="seconds"),
            "valid_until": str(current_watchlist.get("valid_until") or ""),
            "trading_day": str(current_watchlist.get("trading_day") or now.date().isoformat()),
            "stale": False,
            "evolution": {
                "added": added,
                "removed": removed,
                "kept": [symbol for symbol in final_symbols if symbol not in added],
                "reason_summary": {symbol: reasons.get(symbol, "") for symbol in set(added + removed + final_symbols)},
                "updated_at": now.isoformat(timespec="seconds"),
            },
        }
        return result
