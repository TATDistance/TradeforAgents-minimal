from __future__ import annotations

import pandas as pd

from app.feature_service import FeatureService
from app.settings import load_settings


def _sample_frame() -> pd.DataFrame:
    close_values = [10 + idx * 0.08 for idx in range(120)]
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=120, freq="B"),
            "open": close_values,
            "high": [value * 1.01 for value in close_values],
            "low": [value * 0.99 for value in close_values],
            "close": close_values,
            "volume": [1_000_000 + idx * 1_000 for idx in range(120)],
            "amount": [80_000_000 + idx * 50_000 for idx in range(120)],
        }
    )


def test_feature_service_builds_six_strategy_features() -> None:
    service = FeatureService(load_settings())
    features = service.build_for_symbol("600036", _sample_frame())
    assert len(features) == 6
    assert {item.strategy_name for item in features} == {
        "momentum",
        "dual_ma",
        "macd_trend",
        "mean_reversion",
        "breakout",
        "trend_pullback",
    }
    assert all(-1.0 <= item.score <= 1.0 for item in features)
