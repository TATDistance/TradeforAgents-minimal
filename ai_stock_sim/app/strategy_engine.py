from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd

from .models import StrategySignal
from .settings import Settings, load_settings
from .market_data_service import MarketDataService
from strategies import breakout, dual_ma, macd_trend, mean_reversion, momentum, trend_pullback


STRATEGY_REGISTRY = {
    "momentum": momentum.generate_signal,
    "dual_ma": dual_ma.generate_signal,
    "macd_trend": macd_trend.generate_signal,
    "mean_reversion": mean_reversion.generate_signal,
    "breakout": breakout.generate_signal,
    "trend_pullback": trend_pullback.generate_signal,
}


class StrategyEngine:
    def __init__(self, settings: Settings | None = None, market_data: MarketDataService | None = None) -> None:
        self.settings = settings or load_settings()
        self.market_data = market_data or MarketDataService(self.settings)

    def load_bars(self, symbol: str, asset_type: str = "stock", limit: int = 240) -> pd.DataFrame:
        return self.market_data.fetch_history_daily(symbol=symbol, asset_type=asset_type, limit=limit)

    def run_for_symbol(self, symbol: str, asset_type: str = "stock") -> List[StrategySignal]:
        frame = self.load_bars(symbol, asset_type=asset_type)
        if frame.empty:
            return []
        signals = [generator(symbol, frame, self.settings) for generator in STRATEGY_REGISTRY.values()]
        return [signal for signal in signals if signal is not None]

    def run_single_strategy(self, symbol: str, strategy_name: str, asset_type: str = "stock") -> StrategySignal | None:
        frame = self.load_bars(symbol, asset_type=asset_type)
        if frame.empty:
            return None
        generator = STRATEGY_REGISTRY.get(strategy_name)
        if generator is None:
            raise KeyError(f"unknown strategy: {strategy_name}")
        return generator(symbol, frame, self.settings)

    def run_batch(self, symbols: Iterable[str], asset_type_map: Dict[str, str] | None = None) -> Dict[str, List[StrategySignal]]:
        results: Dict[str, List[StrategySignal]] = {}
        asset_type_map = asset_type_map or {}
        for symbol in symbols:
            results[symbol] = self.run_for_symbol(symbol, asset_type=asset_type_map.get(symbol, "stock"))
        return results
