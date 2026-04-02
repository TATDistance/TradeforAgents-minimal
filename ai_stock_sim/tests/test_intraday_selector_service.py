from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.intraday_selector_service import IntradaySelectorService
from app.settings import load_settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_intraday_selector_service_returns_new_candidates(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = IntradaySelectorService(settings)

    snapshot = pd.DataFrame(
        [
            {"symbol": "300750", "name": "宁德时代", "amount": 1_000_000_000, "pct_change": 4.6, "turnover_rate": 3.1, "is_st": False, "asset_type": "stock"},
            {"symbol": "688525", "name": "佰维存储", "amount": 900_000_000, "pct_change": 3.2, "turnover_rate": 2.1, "is_st": False, "asset_type": "stock"},
        ]
    )

    result = service.scan(snapshot, current_watchlist=["688525"], current_positions=[], market_regime="TRENDING_UP")

    assert any(item["symbol"] == "300750" for item in result["candidates"])
