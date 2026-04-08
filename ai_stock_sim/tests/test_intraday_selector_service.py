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
    history = pd.DataFrame(
        [
            {"trade_date": "2026-03-20", "open": 10, "close": 10.1, "high": 10.2, "low": 9.9, "volume": 1000, "amount": 10100},
            {"trade_date": "2026-03-21", "open": 10.1, "close": 10.3, "high": 10.4, "low": 10.0, "volume": 1100, "amount": 11330},
            {"trade_date": "2026-03-24", "open": 10.3, "close": 10.6, "high": 10.7, "low": 10.2, "volume": 1300, "amount": 13780},
            {"trade_date": "2026-03-25", "open": 10.6, "close": 10.9, "high": 11.0, "low": 10.5, "volume": 1500, "amount": 16350},
            {"trade_date": "2026-03-26", "open": 10.9, "close": 11.1, "high": 11.2, "low": 10.8, "volume": 1600, "amount": 17760},
            {"trade_date": "2026-03-27", "open": 11.1, "close": 11.4, "high": 11.5, "low": 11.0, "volume": 1700, "amount": 19380},
        ]
    )
    service.market_data.fetch_history_daily = lambda *args, **kwargs: history.copy()

    snapshot = pd.DataFrame(
        [
            {"symbol": "300750", "name": "宁德时代", "amount": 1_000_000_000, "pct_change": 4.6, "turnover_rate": 3.1, "is_st": False, "asset_type": "stock"},
            {"symbol": "688525", "name": "佰维存储", "amount": 900_000_000, "pct_change": 3.2, "turnover_rate": 2.1, "is_st": False, "asset_type": "stock"},
        ]
    )

    result = service.scan(snapshot, current_watchlist=["688525"], current_positions=[], market_regime="TRENDING_UP")

    assert any(item["symbol"] == "300750" for item in result["candidates"])


def test_intraday_selector_service_enriches_candidates_with_theme_fields(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = IntradaySelectorService(settings)

    history = pd.DataFrame(
        [
            {"trade_date": "2026-03-20", "open": 10, "close": 10.2, "high": 10.3, "low": 9.9, "volume": 1000, "amount": 10200},
            {"trade_date": "2026-03-21", "open": 10.2, "close": 10.4, "high": 10.5, "low": 10.1, "volume": 1100, "amount": 11440},
            {"trade_date": "2026-03-24", "open": 10.4, "close": 10.9, "high": 11.0, "low": 10.3, "volume": 1400, "amount": 15260},
            {"trade_date": "2026-03-25", "open": 10.9, "close": 11.2, "high": 11.3, "low": 10.8, "volume": 1500, "amount": 16800},
            {"trade_date": "2026-03-26", "open": 11.2, "close": 11.5, "high": 11.6, "low": 11.1, "volume": 1600, "amount": 18400},
            {"trade_date": "2026-03-27", "open": 11.5, "close": 11.9, "high": 12.0, "low": 11.4, "volume": 1700, "amount": 20230},
        ]
    )

    service.market_data.fetch_history_daily = lambda *args, **kwargs: history.copy()
    snapshot = pd.DataFrame(
        [
            {"symbol": "300750", "name": "宁德时代", "amount": 1_100_000_000, "pct_change": 5.2, "turnover_rate": 3.0, "is_st": False, "asset_type": "stock"},
        ]
    )

    result = service.scan(snapshot, current_watchlist=[], current_positions=[], market_regime="TRENDING_UP")

    assert result["market_theme_mode"] in {"concentrated", "mixed", "weak"}
    assert result["candidates"]
    candidate = result["candidates"][0]
    assert "theme" in candidate
    assert "leader_role" in candidate
    assert "quality_score" in candidate
