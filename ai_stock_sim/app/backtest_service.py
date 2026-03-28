from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from .market_data_service import MarketDataService
from .settings import Settings, load_settings
from .strategy_engine import STRATEGY_REGISTRY, StrategyEngine
from .vnpy_adapter import VnpyAdapter


class BacktestService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.market_data = MarketDataService(self.settings)
        self.strategy_engine = StrategyEngine(self.settings, self.market_data)
        self.vnpy_adapter = VnpyAdapter(self.settings)

    def run_simple_backtest(self, symbol: str, strategy_name: str = "momentum", asset_type: str = "stock") -> Dict[str, object]:
        frame = self.market_data.fetch_history_daily(symbol=symbol, asset_type=asset_type, limit=240)
        if frame.empty:
            return {"symbol": symbol, "strategy": strategy_name, "total_trades": 0, "return_pct": 0.0, "engine": "local"}
        strategy_func = STRATEGY_REGISTRY.get(strategy_name)
        if strategy_func is None:
            raise KeyError(f"unknown strategy: {strategy_name}")
        cash = 100000.0
        qty = 0
        entry = 0.0
        trades = 0
        for idx in range(70, len(frame)):
            sub = frame.iloc[: idx + 1].reset_index(drop=True)
            signal = strategy_func(symbol, sub, self.settings)
            price = float(sub.iloc[-1]["close"])
            if signal and signal.action == "BUY" and qty == 0:
                qty = int(cash * 0.5 / price / 100) * 100
                if qty > 0:
                    cash -= qty * price
                    entry = price
                    trades += 1
            elif signal and signal.action == "SELL" and qty > 0:
                cash += qty * price
                qty = 0
                trades += 1
            elif qty > 0 and (price >= entry * 1.08 or price <= entry * 0.95):
                cash += qty * price
                qty = 0
                trades += 1
        if qty > 0:
            cash += qty * float(frame.iloc[-1]["close"])
        return {
            "symbol": symbol,
            "strategy": strategy_name,
            "total_trades": trades,
            "return_pct": round((cash - 100000.0) / 100000.0, 4),
            "engine": "local_with_vnpy_hook",
            "vnpy_workspace": str(self.settings.vnpy_workspace),
            "available_strategies": sorted(STRATEGY_REGISTRY.keys()),
        }

    def save_backtest_report(self, report: Dict[str, object]) -> Path:
        output_dir = self.settings.reports_dir / "backtest"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{report['symbol']}_{report['strategy']}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.vnpy_adapter.export_backtest_result(report)
        return path

    def export_vnpy_payload(self, symbol: str, strategy_name: str, mode_name: str = "strategy_only") -> Path:
        params = {
            "strategy": strategy_name,
            "momentum_lookback": self.settings.strategy.momentum_lookback,
            "dual_ma_fast_window": self.settings.strategy.dual_ma_fast_window,
            "dual_ma_slow_window": self.settings.strategy.dual_ma_slow_window,
            "macd_fast_window": self.settings.strategy.macd_fast_window,
            "macd_slow_window": self.settings.strategy.macd_slow_window,
            "macd_signal_window": self.settings.strategy.macd_signal_window,
            "breakout_window": self.settings.strategy.breakout_window,
            "atr_window": self.settings.strategy.atr_window,
            "rsi_low": self.settings.strategy.mean_reversion_rsi_low,
            "trend_pullback_fast_window": self.settings.strategy.trend_pullback_fast_window,
            "trend_pullback_slow_window": self.settings.strategy.trend_pullback_slow_window,
            "trend_pullback_max_distance_pct": self.settings.strategy.trend_pullback_max_distance_pct,
        }
        engine_type = "alpha" if strategy_name in {"trend_pullback"} else "cta"
        return self.vnpy_adapter.export_strategy_payload(
            strategy_name=strategy_name,
            symbol=symbol,
            params=params,
            mode_name=mode_name,
            engine_type=engine_type,
        )
