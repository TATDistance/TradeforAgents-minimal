from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .settings import Settings, load_settings


VN_ENGINE_MAP = {
    "momentum": ("cta", "MomentumCtaStrategy"),
    "dual_ma": ("cta", "DualMaCtaStrategy"),
    "macd_trend": ("cta", "MacdTrendCtaStrategy"),
    "mean_reversion": ("cta", "MeanReversionCtaStrategy"),
    "breakout": ("cta", "BreakoutCtaStrategy"),
    "trend_pullback": ("alpha", "TrendPullbackAlphaStrategy"),
}


class VnpyAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def export_strategy_payload(
        self,
        strategy_name: str,
        symbol: str,
        params: Mapping[str, Any],
        mode_name: str = "strategy_only",
        engine_type: str | None = None,
    ) -> Path:
        output_dir = self.settings.vnpy_workspace / "exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        inferred_engine, class_name = VN_ENGINE_MAP.get(strategy_name, ("cta", "GenericBridgeStrategy"))
        engine = engine_type or inferred_engine
        payload = {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "mode_name": mode_name,
            "engine_type": engine,
            "vnpy_class_name": class_name,
            "params": dict(params),
            "project_root": str(self.settings.project_root),
        }
        path = output_dir / f"{symbol}_{strategy_name}_{mode_name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._export_native_strategy_stub(strategy_name=strategy_name, engine_type=engine, class_name=class_name)
        return path

    def export_backtest_result(self, result: Mapping[str, Any]) -> Path:
        output_dir = self.settings.reports_dir / "backtest"
        output_dir.mkdir(parents=True, exist_ok=True)
        symbol = str(result.get("symbol") or "unknown")
        strategy = str(result.get("strategy") or "unknown")
        path = output_dir / f"{symbol}_{strategy}_vnpy_adapter.json"
        path.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def _export_native_strategy_stub(self, strategy_name: str, engine_type: str, class_name: str) -> Path:
        output_dir = self.settings.vnpy_workspace / "generated_strategies"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{strategy_name}_{engine_type}_bridge.py"
        if engine_type == "alpha":
            content = f'''"""Generated bridge stub for vn.py Alpha backtesting."""

class {class_name}:
    author = "TradeforAgents-minimal"
    parameters = ["window", "hold_days"]
    variables = ["score"]

    def __init__(self, *args, **kwargs):
        self.score = 0.0

    def on_bars(self, bars):
        """Map exported factor payloads into vn.py Alpha workflow here."""
        return None
'''
        else:
            content = f'''"""Generated bridge stub for vn.py CTA backtesting."""

class {class_name}:
    author = "TradeforAgents-minimal"
    parameters = ["window", "atr_window"]
    variables = ["signal_price"]

    def __init__(self, *args, **kwargs):
        self.signal_price = 0.0

    def on_bar(self, bar):
        """Replace this stub with a real vn.py CTATemplate implementation."""
        return None
'''
        path.write_text(content, encoding="utf-8")
        return path
