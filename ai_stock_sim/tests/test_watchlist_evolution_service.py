from __future__ import annotations

from pathlib import Path

from app.settings import load_settings
from app.watchlist_evolution_service import WatchlistEvolutionService


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_watchlist_evolution_keeps_holdings_and_adds_new_candidates(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = WatchlistEvolutionService(settings)

    result = service.evolve(
        {
            "symbols": ["300750", "688525"],
            "generated_at": "2026-04-02T09:30:00",
            "trading_day": "2026-04-02",
        },
        opportunity_pool=[
            {"symbol": "002594", "score": 0.7, "reason": "新发现强势股"},
        ],
        runtime_states={
            "300750": {"last_setup_score": 0.52, "last_execution_score": 0.44, "updated_at": "2026-04-02T09:40:00"},
            "688525": {"last_setup_score": 0.05, "last_execution_score": 0.02, "updated_at": "2026-04-02T08:00:00"},
        },
        holdings=["300750"],
    )

    assert "300750" in result["symbols"]
    assert "002594" in result["symbols"]
    assert "002594" in (result.get("evolution") or {}).get("added", [])


def test_watchlist_evolution_skips_low_quality_candidates(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = WatchlistEvolutionService(settings)

    result = service.evolve(
        {
            "symbols": ["300750"],
            "generated_at": "2026-04-02T09:30:00",
            "trading_day": "2026-04-02",
        },
        opportunity_pool=[
            {"symbol": "002594", "score": 0.72, "reason": "主线龙头", "quality_passed": True, "leader_role": "leader", "quality_score": 0.78},
            {"symbol": "002812", "score": 0.75, "reason": "噪音票", "quality_passed": False, "leader_role": "weak_follower", "quality_score": 0.32},
        ],
        runtime_states={"300750": {"last_setup_score": 0.62, "last_execution_score": 0.55, "updated_at": "2026-04-02T09:40:00"}},
        holdings=[],
    )

    assert "002594" in result["symbols"]
    assert "002812" not in result["symbols"]
