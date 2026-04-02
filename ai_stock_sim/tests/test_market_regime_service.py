from __future__ import annotations

import pandas as pd

from app.market_regime_service import MarketRegimeService
from app.settings import load_settings


def test_market_regime_service_detects_trending_up() -> None:
    service = MarketRegimeService(load_settings())
    snapshot = pd.DataFrame(
        [
            {"pct_change": 0.02, "amount": 100_000_000},
            {"pct_change": 0.018, "amount": 120_000_000},
            {"pct_change": 0.012, "amount": 130_000_000},
            {"pct_change": 0.015, "amount": 90_000_000},
        ]
    )
    result = service.detect_market_regime(snapshot, {"drawdown": 0.0})
    assert result.regime == "TRENDING_UP"
    assert result.confidence > 0.5
