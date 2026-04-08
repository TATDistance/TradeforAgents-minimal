from __future__ import annotations

from pathlib import Path

from app.entry_structure_service import EntryStructureService
from app.settings import load_settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_entry_structure_service_blocks_chasing(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = EntryStructureService(settings)

    result = service.evaluate(
        snapshot={"pct_change": 7.2, "latest_price": 33.0},
        technical={"ret_5d": 0.09, "ret_20d": 0.14, "trend_slope_20d": 0.08, "ma20_bias": 0.07, "ma60_bias": 0.12, "macd_hist": 0.02, "rsi_14": 79},
        market_regime={"regime": "TRENDING_UP"},
        position_state={"has_position": False},
    )

    assert result["entry_type"] == "chase_block"
    assert result["allow_buy"] is False


def test_entry_structure_service_marks_probe_entry_on_pullback(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = EntryStructureService(settings)

    result = service.evaluate(
        snapshot={"pct_change": 1.4, "latest_price": 25.0},
        technical={"ret_5d": 0.01, "ret_20d": 0.10, "trend_slope_20d": 0.07, "ma20_bias": 0.012, "ma60_bias": 0.08, "macd_hist": 0.015, "rsi_14": 61},
        market_regime={"regime": "TRENDING_UP"},
        position_state={"has_position": False},
    )

    assert result["entry_type"] == "probe_entry"
    assert result["allow_buy"] is True
    assert result["position_scale"] < 1.0
