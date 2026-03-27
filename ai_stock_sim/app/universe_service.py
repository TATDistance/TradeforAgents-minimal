from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from .market_data_service import MarketDataService
from .settings import Settings, SymbolConfig, load_settings, load_symbol_config


@dataclass
class UniverseResult:
    snapshot: pd.DataFrame
    selected_symbols: List[str]
    warnings: List[str]
    data_source: str


class UniverseService:
    def __init__(self, settings: Settings | None = None, symbols: SymbolConfig | None = None) -> None:
        self.settings = settings or load_settings()
        self.symbols = symbols or load_symbol_config(self.settings.project_root)
        self.market_data = MarketDataService(self.settings)

    def build_universe(self) -> UniverseResult:
        warnings: List[str] = []
        snapshot = self.market_data.fetch_realtime_snapshot(
            limit=self.settings.scan_limit,
            include_etf=self.symbols.include_etfs,
        )
        if snapshot.empty:
            return UniverseResult(snapshot=snapshot, selected_symbols=[], warnings=["实时快照为空"], data_source="unknown")

        filtered = snapshot.copy()
        if self.symbols.blacklist:
            filtered = filtered[~filtered["symbol"].isin(self.symbols.blacklist)]
        filtered = filtered[filtered["amount"] >= self.settings.min_turnover]
        filtered = filtered[~filtered["is_st"]]

        candidates: List[str] = []
        for _, row in filtered.iterrows():
            symbol = str(row["symbol"])
            asset_type = str(row.get("asset_type") or "stock")
            history = self.market_data.fetch_history_daily(symbol, asset_type=asset_type, limit=max(self.settings.min_listing_days + 10, 150))
            if len(history) < self.settings.min_listing_days:
                continue
            candidates.append(symbol)
            if len(candidates) >= self.settings.strategy_candidate_limit:
                break

        for symbol in self.symbols.stock_watchlist + self.symbols.etf_watchlist:
            if symbol not in candidates and symbol not in self.symbols.blacklist:
                candidates.append(symbol)

        data_source = "eastmoney_live"
        if not candidates:
            warnings.append("过滤后无候选标的")
        return UniverseResult(
            snapshot=snapshot,
            selected_symbols=candidates[: self.settings.strategy_candidate_limit],
            warnings=warnings,
            data_source=data_source,
        )

    @staticmethod
    def empty_result(reason: str) -> UniverseResult:
        return UniverseResult(
            snapshot=pd.DataFrame(),
            selected_symbols=[],
            warnings=[f"当前处于 {reason}，已跳过实时股票池更新"],
            data_source="market_closed",
        )
