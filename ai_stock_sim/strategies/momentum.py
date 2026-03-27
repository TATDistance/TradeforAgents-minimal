from __future__ import annotations

import pandas as pd

from app.models import StrategySignal
from app.settings import Settings

from .common import annualized_volatility, safe_pct_change


def generate_signal(symbol: str, frame: pd.DataFrame, settings: Settings) -> StrategySignal | None:
    if len(frame) < settings.strategy.momentum_lookback + 5:
        return None

    close = frame["close"]
    latest_close = float(close.iloc[-1])
    lookback = settings.strategy.momentum_lookback
    momentum = float(safe_pct_change(close, lookback).iloc[-1] or 0.0)
    volatility = float(annualized_volatility(close, lookback).iloc[-1] or 0.0)
    ma20 = float(close.rolling(20).mean().iloc[-1] or latest_close)
    ma60 = float(close.rolling(60).mean().iloc[-1] or ma20)

    if momentum <= 0 or latest_close < ma20 or ma20 < ma60:
        return None

    score = max(0.0, min(1.0, 0.55 + momentum * 1.8 - volatility * 0.3))
    if score < settings.strategy.momentum_min_score:
        return None

    stop_loss = round(latest_close * (1 - max(0.04, volatility * 0.6)), 3)
    take_profit = round(latest_close * (1 + max(0.06, momentum * 0.8)), 3)
    position_pct = max(0.05, min(0.18, 0.10 + score * 0.08 - volatility * 0.05))
    return StrategySignal(
        symbol=symbol,
        strategy="momentum",
        action="BUY",
        score=round(score, 4),
        signal_price=round(latest_close, 3),
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_pct=round(position_pct, 4),
        reason=f"{lookback}日动量为正，均线多头排列，波动率{volatility:.2f}",
    )
