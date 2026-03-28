from __future__ import annotations

from dataclasses import dataclass

from .settings import Settings, load_settings


LEGACY_MODE = "legacy_review_mode"
AI_ENGINE_MODE = "ai_decision_engine_mode"
COMPARE_MODE = "compare_mode"


@dataclass
class DecisionModeState:
    requested_mode: str
    effective_mode: str
    run_legacy: bool
    run_engine: bool
    execute_mode: str


class DecisionModeRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def resolve(self) -> DecisionModeState:
        requested = str(self.settings.decision_engine.mode or AI_ENGINE_MODE)
        if requested not in {LEGACY_MODE, AI_ENGINE_MODE, COMPARE_MODE}:
            requested = AI_ENGINE_MODE
        if requested == COMPARE_MODE and not self.settings.compare_mode.enabled:
            requested = AI_ENGINE_MODE
        if requested == LEGACY_MODE:
            return DecisionModeState(requested_mode=requested, effective_mode=LEGACY_MODE, run_legacy=True, run_engine=False, execute_mode=LEGACY_MODE)
        if requested == COMPARE_MODE:
            return DecisionModeState(requested_mode=requested, effective_mode=COMPARE_MODE, run_legacy=True, run_engine=True, execute_mode=AI_ENGINE_MODE)
        return DecisionModeState(requested_mode=requested, effective_mode=AI_ENGINE_MODE, run_legacy=False, run_engine=True, execute_mode=AI_ENGINE_MODE)

    def fallback_on_failure(self, current: DecisionModeState) -> DecisionModeState:
        if not self.settings.decision_engine.fallback_to_legacy_mode_on_failure:
            return current
        return DecisionModeState(
            requested_mode=current.requested_mode,
            effective_mode=LEGACY_MODE,
            run_legacy=True,
            run_engine=False,
            execute_mode=LEGACY_MODE,
        )
