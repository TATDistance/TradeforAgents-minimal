from __future__ import annotations

from pathlib import Path

from app.opportunity_pool_service import OpportunityPoolService
from app.settings import load_settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_opportunity_pool_service_keeps_active_items(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = OpportunityPoolService(settings)

    service.update(
        [
            {"symbol": "300750", "score": 0.72, "reason": "盘中放量"},
            {"symbol": "002594", "score": 0.68, "reason": "趋势强化"},
        ]
    )
    active = service.get_active()

    assert [item["symbol"] for item in active][:2] == ["300750", "002594"]
