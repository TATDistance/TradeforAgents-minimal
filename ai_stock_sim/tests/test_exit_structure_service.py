from __future__ import annotations

from pathlib import Path

from app.exit_structure_service import ExitStructureService
from app.settings import load_settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_exit_structure_service_marks_structure_break_sell(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = ExitStructureService(settings)

    result = service.evaluate(
        technical={"trend_slope_20d": -0.07, "ma20_bias": -0.08, "ma60_bias": -0.04, "macd_hist": -0.03, "rsi_14": 37},
        position_state={"can_sell_qty": 1000, "unrealized_pct": -0.09, "hold_days": 5},
        execution_score=-0.34,
        risk_mode="DEFENSIVE",
    )

    assert result["exit_type"] == "sell_on_break"
    assert result["suggested_action"] == "SELL"


def test_exit_structure_service_prefers_partial_take_profit(tmp_path: Path) -> None:
    project_root = tmp_path / "ai_stock_sim"
    _write_text(project_root / "config" / "settings.yaml", "")
    settings = load_settings(project_root)
    service = ExitStructureService(settings)

    result = service.evaluate(
        technical={"trend_slope_20d": 0.02, "ma20_bias": 0.015, "ma60_bias": 0.06, "macd_hist": 0.002, "rsi_14": 74},
        position_state={"can_sell_qty": 1000, "unrealized_pct": 0.12, "hold_days": 10},
        execution_score=-0.05,
        risk_mode="NORMAL",
    )

    assert result["exit_type"] == "take_profit_partial"
    assert result["suggested_action"] == "REDUCE"
