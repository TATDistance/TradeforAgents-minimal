from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional


@dataclass
class PriceBar:
    symbol: str
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float


def midpoint(price_min: Optional[float], price_max: Optional[float]) -> Optional[float]:
    if price_min is None and price_max is None:
        return None
    if price_min is None:
        return price_max
    if price_max is None:
        return price_min
    return round((float(price_min) + float(price_max)) / 2.0, 3)


class CsvBarStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def load_daily_bars(self, ticker: str) -> List[PriceBar]:
        path = self.root / "{0}.csv".format(ticker)
        if not path.exists():
            return []

        bars = []
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bars.append(
                    PriceBar(
                        symbol=ticker,
                        trade_date=row["trade_date"],
                        open_price=float(row["open"]),
                        high_price=float(row["high"]),
                        low_price=float(row["low"]),
                        close_price=float(row["close"]),
                        volume=float(row.get("volume", 0) or 0),
                    )
                )
        return bars


class ResultBarStore:
    def __init__(self, results_root: Path) -> None:
        self.root = Path(results_root)

    @lru_cache(maxsize=512)
    def load_daily_bars(self, ticker: str) -> List[PriceBar]:
        ticker_root = self.root / str(ticker)
        if not ticker_root.exists():
            return []

        bars = {}
        for date_dir in sorted(ticker_root.iterdir()):
            snapshot_path = date_dir / "reports" / "market_snapshot.json"
            if not snapshot_path.exists():
                continue

            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                latest = payload.get("latest") or {}
                trade_date = str(latest.get("date") or payload.get("as_of_date") or date_dir.name)
                open_price = float(latest["open"])
                high_price = float(latest["high"])
                low_price = float(latest["low"])
                close_price = float(latest["close"])
                volume = float(latest.get("volume", 0) or 0)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

            bars[trade_date] = PriceBar(
                symbol=str(payload.get("symbol") or ticker),
                trade_date=trade_date,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
            )

        return [bars[key] for key in sorted(bars)]

    def get_next_bar(self, ticker: str, after_date: str) -> Optional[PriceBar]:
        for bar in self.load_daily_bars(ticker):
            if bar.trade_date > after_date:
                return bar
        return None

    def get_previous_bar(self, ticker: str, before_date: str) -> Optional[PriceBar]:
        previous = None
        for bar in self.load_daily_bars(ticker):
            if bar.trade_date >= before_date:
                break
            previous = bar
        return previous

    def latest_bar_on_or_before(self, ticker: str, trade_date: str) -> Optional[PriceBar]:
        latest = None
        for bar in self.load_daily_bars(ticker):
            if bar.trade_date > trade_date:
                break
            latest = bar
        return latest


def akshare_note() -> str:
    return (
        "AKShare is not wired into the MVP runtime yet. "
        "Use this module as the adapter point for daily bar ingestion."
    )
