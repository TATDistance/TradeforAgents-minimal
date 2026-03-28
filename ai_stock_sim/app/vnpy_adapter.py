from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .settings import Settings, load_settings


class VnpyAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def export_strategy_payload(
        self,
        strategy_name: str,
        symbol: str,
        params: Mapping[str, Any],
        mode_name: str = "strategy_only",
    ) -> Path:
        output_dir = self.settings.vnpy_workspace / "exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "mode_name": mode_name,
            "params": dict(params),
            "project_root": str(self.settings.project_root),
        }
        path = output_dir / f"{symbol}_{strategy_name}_{mode_name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def export_backtest_result(self, result: Mapping[str, Any]) -> Path:
        output_dir = self.settings.reports_dir / "backtest"
        output_dir.mkdir(parents=True, exist_ok=True)
        symbol = str(result.get("symbol") or "unknown")
        strategy = str(result.get("strategy") or "unknown")
        path = output_dir / f"{symbol}_{strategy}_vnpy_adapter.json"
        path.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path
