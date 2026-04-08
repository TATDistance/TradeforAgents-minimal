from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.leader_selection_service import LeaderSelectionService
from app.settings import load_settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_leader_selection_service_marks_theme_leader(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = LeaderSelectionService(settings)

    snapshot = pd.DataFrame(
        [
            {"symbol": "300750", "amount": 1_200_000_000, "pct_change": 6.0, "turnover_rate": 3.8},
            {"symbol": "300308", "amount": 850_000_000, "pct_change": 4.2, "turnover_rate": 2.2},
            {"symbol": "600036", "amount": 300_000_000, "pct_change": 0.4, "turnover_rate": 0.7},
        ]
    )
    theme_report = {
        "symbol_themes": {
            "300750": {"theme": "强势突破", "strength": 0.82},
            "300308": {"theme": "强势突破", "strength": 0.73},
            "600036": {"theme": "非主线", "strength": 0.0},
        }
    }
    technical_map = {
        "300750": {"trend_slope_20d": 0.12, "ret_20d": 0.18},
        "300308": {"trend_slope_20d": 0.07, "ret_20d": 0.11},
        "600036": {"trend_slope_20d": 0.01, "ret_20d": 0.02},
    }

    result = service.classify(snapshot, theme_report=theme_report, technical_map=technical_map)

    assert result["300750"]["role"] == "leader"
    assert result["300308"]["role"] in {"strong_follower", "weak_follower"}
    assert result["600036"]["role"] == "non_theme"
