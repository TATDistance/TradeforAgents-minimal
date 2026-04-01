from __future__ import annotations

from pathlib import Path

from app.settings import load_settings
from app.watchlist_sync_service import load_runtime_watchlist, sync_watchlist_to_runtime


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_watchlist_sync_service_writes_runtime_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)

    synced = sync_watchlist_to_runtime(
        {
            "symbols": ["300750", "510300"],
            "source": "auto_selector_today",
            "generated_at": "2026-04-01T09:30:00",
            "valid_until": "2026-04-02T09:00:00",
            "trading_day": "2026-04-01",
        },
        settings,
    )
    loaded = load_runtime_watchlist(settings)

    assert synced["symbols"] == ["300750", "510300"]
    assert loaded["source"] == "auto_selector_today"
    assert loaded["symbols"] == ["300750", "510300"]
