from __future__ import annotations

import pandas as pd

from app.market_regime_service import MarketRegimeService
from app.settings import load_settings


def test_market_regime_falls_back_when_snapshot_empty():
    service = MarketRegimeService(load_settings())
    state = service.evaluate(pd.DataFrame(), {"drawdown": 0.0})
    assert state.regime == "RANGE_BOUND"
    assert state.confidence <= 0.5


def test_market_regime_detects_trending_up():
    service = MarketRegimeService(load_settings())
    frame = pd.DataFrame(
        [
            {"symbol": "600036", "pct_change": 0.015, "amount": 1.2e8},
            {"symbol": "600031", "pct_change": 0.012, "amount": 1.1e8},
            {"symbol": "300750", "pct_change": 0.01, "amount": 1.3e8},
            {"symbol": "002594", "pct_change": 0.009, "amount": 1.0e8},
        ]
    )
    state = service.evaluate(frame, {"drawdown": 0.0})
    assert state.regime == "TRENDING_UP"
