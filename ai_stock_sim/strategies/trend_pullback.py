from __future__ import annotations

import pandas as pd

from app.models import StrategySignal
from app.settings import Settings


def generate_signal(symbol: str, frame: pd.DataFrame, settings: Settings) -> StrategySignal | None:
    fast_window = settings.strategy.trend_pullback_fast_window
    slow_window = settings.strategy.trend_pullback_slow_window
    if len(frame) < slow_window + 5:
        return None

    close = frame["close"]
    latest_close = float(close.iloc[-1])
    fast_ma = float(close.rolling(fast_window).mean().iloc[-1] or latest_close)
    slow_ma = float(close.rolling(slow_window).mean().iloc[-1] or fast_ma)
    distance = (latest_close - fast_ma) / max(fast_ma, 0.01)
    trend_strength = (fast_ma - slow_ma) / max(slow_ma, 0.01)
    max_distance = settings.strategy.trend_pullback_max_distance_pct

    if latest_close < slow_ma or fast_ma < slow_ma or distance < -max_distance or distance > 0.01:
        return None

    score = max(0.0, min(1.0, 0.54 + trend_strength * 6.0 + (max_distance - abs(distance)) * 4.0))
    return StrategySignal(
        symbol=symbol,
        strategy="trend_pullback",
        action="BUY",
        score=round(score, 4),
        signal_price=round(latest_close, 3),
        stop_loss=round(min(slow_ma, latest_close * 0.955), 3),
        take_profit=round(latest_close * (1 + max(0.06, trend_strength * 3.0)), 3),
        position_pct=round(max(0.05, min(0.15, 0.07 + score * 0.06)), 4),
        reason=f"上升趋势中回踩 {fast_window} 日均线，距均线 {distance:.2%}",
    )
