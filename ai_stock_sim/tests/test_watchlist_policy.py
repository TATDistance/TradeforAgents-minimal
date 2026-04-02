from __future__ import annotations

from app.settings import load_settings
from app.watchlist_policy import WatchlistPolicy


def test_watchlist_policy_reads_thresholds() -> None:
    policy = WatchlistPolicy.from_settings(load_settings())
    assert policy.scan_interval_minutes >= 5
    assert policy.max_watchlist_size >= 5
    assert policy.min_score_to_add > policy.min_score_to_keep
