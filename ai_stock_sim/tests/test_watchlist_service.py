from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.settings import load_settings
from app.watchlist_service import get_active_watchlist, is_watchlist_stale, load_default_watchlist


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_watchlist_service_prefers_today_auto_selector(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    _write_text(project_root / "config" / "symbols.yaml", "watchlist:\n  stocks: [600036]\n  etfs: []\n")
    today = datetime.now().date().isoformat()
    _write_text(project_root.parent / "ai_trade_system" / "reports" / f"auto_watchlist_{today}.txt", "300750\n688525\n")
    settings = load_settings(project_root)

    payload = get_active_watchlist(settings)

    assert payload["source"] == "auto_selector_today"
    assert payload["symbols"] == ["300750", "688525"]
    assert payload["stale"] is False


def test_watchlist_service_falls_back_to_recent_candidates(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    _write_text(project_root / "config" / "symbols.yaml", "watchlist:\n  stocks: [600036]\n  etfs: []\n")
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
    report_path = project_root.parent / "ai_trade_system" / "reports" / f"auto_watchlist_{yesterday}.txt"
    _write_text(report_path, "300750\n")
    settings = load_settings(project_root)

    payload = get_active_watchlist(settings)

    assert payload["source"] == "recent_candidates"
    assert payload["symbols"] == ["300750"]
    assert is_watchlist_stale(payload, settings=settings) is True


def test_load_default_watchlist_reads_symbols_yaml(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    _write_text(
        project_root / "config" / "symbols.yaml",
        "watchlist:\n  stocks: [600036, 300750]\n  etfs: [510300]\n",
    )
    settings = load_settings(project_root)
    assert load_default_watchlist(settings) == ["600036", "300750", "510300"]
