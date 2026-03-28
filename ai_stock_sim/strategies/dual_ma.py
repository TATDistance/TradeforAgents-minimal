from __future__ import annotations

import pandas as pd

from app.models import StrategySignal
from app.settings import Settings


def generate_signal(symbol: str, frame: pd.DataFrame, settings: Settings) -> StrategySignal | None:
    fast_window = settings.strategy.dual_ma_fast_window
    slow_window = settings.strategy.dual_ma_slow_window
    if len(frame) < slow_window + 5:
        return None

    close = frame["close"]
    fast_ma = close.rolling(fast_window).mean()
    slow_ma = close.rolling(slow_window).mean()
    latest_close = float(close.iloc[-1])
    prev_fast = float(fast_ma.iloc[-2] or latest_close)
    prev_slow = float(slow_ma.iloc[-2] or latest_close)
    latest_fast = float(fast_ma.iloc[-1] or latest_close)
    latest_slow = float(slow_ma.iloc[-1] or latest_close)

    crossed_up = prev_fast <= prev_slow and latest_fast > latest_slow
    crossed_down = prev_fast >= prev_slow and latest_fast < latest_slow
    spread = abs(latest_fast - latest_slow) / max(latest_slow, 0.01)

    if crossed_up and latest_close >= latest_slow:
        score = max(0.0, min(1.0, 0.56 + spread * 8.0))
        return StrategySignal(
            symbol=symbol,
            strategy="dual_ma",
            action="BUY",
            score=round(score, 4),
            signal_price=round(latest_close, 3),
            stop_loss=round(min(latest_slow, latest_close * 0.96), 3),
            take_profit=round(latest_close * (1 + max(0.06, spread * 4.0)), 3),
            position_pct=round(max(0.06, min(0.16, 0.08 + score * 0.07)), 4),
            reason=f"{fast_window}/{slow_window} 日均线金叉，趋势开始转强",
        )

    if crossed_down and latest_close <= latest_slow:
        score = max(0.0, min(1.0, 0.54 + spread * 7.0))
        return StrategySignal(
            symbol=symbol,
            strategy="dual_ma",
            action="SELL",
            score=round(score, 4),
            signal_price=round(latest_close, 3),
            stop_loss=None,
            take_profit=None,
            position_pct=1.0,
            reason=f"{fast_window}/{slow_window} 日均线死叉，趋势转弱",
        )
    return None
