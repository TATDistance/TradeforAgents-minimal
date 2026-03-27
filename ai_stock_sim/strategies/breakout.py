from __future__ import annotations

import pandas as pd

from app.models import StrategySignal
from app.settings import Settings

from .common import atr, donchian_high


def generate_signal(symbol: str, frame: pd.DataFrame, settings: Settings) -> StrategySignal | None:
    window = settings.strategy.breakout_window
    if len(frame) < max(window, settings.strategy.atr_window) + 5:
        return None

    latest = frame.iloc[-1]
    prev_high = float(donchian_high(frame.iloc[:-1], window=window).iloc[-1] or 0.0)
    current_atr = float(atr(frame, window=settings.strategy.atr_window).iloc[-1] or 0.0)
    latest_close = float(latest["close"])

    if prev_high <= 0 or latest_close <= prev_high:
        return None

    breakout_strength = (latest_close - prev_high) / prev_high
    score = max(0.0, min(1.0, 0.58 + breakout_strength * 8.0))
    stop_loss = round(latest_close - max(current_atr * 1.5, latest_close * 0.04), 3)
    take_profit = round(latest_close + max(current_atr * 3.0, latest_close * 0.08), 3)
    position_pct = max(0.05, min(0.18, 0.08 + score * 0.08))

    return StrategySignal(
        symbol=symbol,
        strategy="breakout",
        action="BUY",
        score=round(score, 4),
        signal_price=round(latest_close, 3),
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_pct=round(position_pct, 4),
        reason=f"{window}日新高突破，ATR={current_atr:.3f}，趋势延续概率较高",
    )
