from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.candidate_quality_service import CandidateQualityService
from app.settings import load_settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_candidate_quality_service_filters_weak_and_noisy_candidates(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = CandidateQualityService(settings)

    snapshot = pd.DataFrame(
        [
            {"symbol": "300750", "amount": 980_000_000, "pct_change": 2.6, "turnover_rate": 2.5},
            {"symbol": "002812", "amount": 55_000_000, "pct_change": 8.8, "turnover_rate": 0.6},
        ]
    )
    technical_map = {
        "300750": {"ret_20d": 0.12, "trend_slope_20d": 0.08, "ma20_bias": 0.03, "macd_hist": 0.02, "rsi_14": 63},
        "002812": {"ret_20d": 0.01, "trend_slope_20d": -0.01, "ma20_bias": 0.10, "macd_hist": -0.01, "rsi_14": 82},
    }
    theme_report = {
        "symbol_themes": {
            "300750": {"theme": "趋势主升", "strength": 0.75},
            "002812": {"theme": "非主线", "strength": 0.0},
        }
    }
    leader_map = {
        "300750": {"role": "leader", "leader_rank_score": 0.82},
        "002812": {"role": "non_theme", "leader_rank_score": 0.18},
    }

    result = service.evaluate_batch(
        snapshot,
        technical_map=technical_map,
        theme_report=theme_report,
        leader_map=leader_map,
        market_regime="TRENDING_UP",
    )

    assert result["300750"]["passed"] is True
    assert result["300750"]["quality_score"] >= 0.5
    assert result["002812"]["passed"] is False
    assert "高波动噪音" in result["002812"]["filter_reasons"] or "综合质量不足" in result["002812"]["filter_reasons"]
