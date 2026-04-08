from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.models import StrategyFeature
from app.settings import load_settings
from app.theme_detection_service import ThemeDetectionService


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_theme_detection_service_identifies_top_themes(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = ThemeDetectionService(settings)

    snapshot = pd.DataFrame(
        [
            {"symbol": "300750", "name": "宁德时代", "amount": 1_200_000_000, "pct_change": 5.8, "turnover_rate": 3.5},
            {"symbol": "300308", "name": "中际旭创", "amount": 1_000_000_000, "pct_change": 4.9, "turnover_rate": 3.2},
            {"symbol": "600036", "name": "招商银行", "amount": 380_000_000, "pct_change": 0.6, "turnover_rate": 0.8},
        ]
    )
    technical_map = {
        "300750": {"ret_5d": 0.08, "ret_20d": 0.16, "trend_slope_20d": 0.11, "ma20_bias": 0.06},
        "300308": {"ret_5d": 0.07, "ret_20d": 0.14, "trend_slope_20d": 0.10, "ma20_bias": 0.05},
        "600036": {"ret_5d": 0.01, "ret_20d": 0.02, "trend_slope_20d": 0.01, "ma20_bias": 0.01},
    }
    feature_map = {
        "300750": [StrategyFeature(symbol="300750", strategy_name="breakout", score=0.72, direction="LONG", strength=0.72)],
        "300308": [StrategyFeature(symbol="300308", strategy_name="breakout", score=0.64, direction="LONG", strength=0.64)],
        "600036": [StrategyFeature(symbol="600036", strategy_name="momentum", score=0.08, direction="NEUTRAL", strength=0.08)],
    }

    result = service.detect(snapshot, technical_map=technical_map, feature_map=feature_map)

    assert result["market_theme_mode"] in {"concentrated", "mixed"}
    assert result["top_themes"]
    assert result["top_themes"][0]["name"] == "强势突破"
    assert result["symbol_themes"]["300750"]["theme"] == "强势突破"
    assert result["symbol_themes"]["600036"]["theme"] == "非主线"
