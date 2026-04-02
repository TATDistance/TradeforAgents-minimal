from __future__ import annotations

from dataclasses import dataclass

from .settings import Settings, load_settings


@dataclass(frozen=True)
class WatchlistPolicy:
    scan_interval_minutes: int
    max_watchlist_size: int
    max_new_symbols_per_scan: int
    max_remove_symbols_per_scan: int
    min_score_to_add: float
    min_score_to_keep: float
    grace_period_minutes: int

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "WatchlistPolicy":
        resolved_settings = settings or load_settings()
        config = resolved_settings.watchlist_evolution
        return cls(
            scan_interval_minutes=max(5, int(config.scan_interval_minutes or 30)),
            max_watchlist_size=max(5, int(config.max_watchlist_size or 30)),
            max_new_symbols_per_scan=max(1, int(config.max_new_symbols_per_scan or 10)),
            max_remove_symbols_per_scan=max(1, int(config.max_remove_symbols_per_scan or 5)),
            min_score_to_add=float(config.min_score_to_add or 0.55),
            min_score_to_keep=float(config.min_score_to_keep or 0.30),
            grace_period_minutes=max(15, int(config.grace_period_minutes or 60)),
        )
