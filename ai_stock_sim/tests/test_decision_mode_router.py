from __future__ import annotations

from app.decision_mode_router import AI_ENGINE_MODE, COMPARE_MODE, DecisionModeRouter, LEGACY_MODE
from app.settings import load_settings


def test_decision_mode_router_resolves_compare_mode() -> None:
    settings = load_settings()
    settings.decision_engine.mode = COMPARE_MODE
    router = DecisionModeRouter(settings)
    state = router.resolve()
    assert state.run_legacy is True
    assert state.run_engine is True
    assert state.execute_mode == AI_ENGINE_MODE


def test_decision_mode_router_fallbacks_to_legacy() -> None:
    settings = load_settings()
    settings.decision_engine.mode = AI_ENGINE_MODE
    router = DecisionModeRouter(settings)
    state = router.fallback_on_failure(router.resolve())
    assert state.effective_mode == LEGACY_MODE
    assert state.run_legacy is True
