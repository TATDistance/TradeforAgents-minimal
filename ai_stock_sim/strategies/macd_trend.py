from __future__ import annotations

import pandas as pd

from app.models import StrategySignal
from app.settings import Settings

from .common import macd


def generate_signal(symbol: str, frame: pd.DataFrame, settings: Settings) -> StrategySignal | None:
    fast = settings.strategy.macd_fast_window
    slow = settings.strategy.macd_slow_window
    signal_window = settings.strategy.macd_signal_window
    if len(frame) < slow + signal_window + 5:
        return None

    close = frame["close"]
    latest_close = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1] or latest_close)
    dif, dea, hist = macd(close, fast=fast, slow=slow, signal=signal_window)

    latest_dif = float(dif.iloc[-1] or 0.0)
    latest_dea = float(dea.iloc[-1] or 0.0)
    latest_hist = float(hist.iloc[-1] or 0.0)
    prev_hist = float(hist.iloc[-2] or 0.0)

    if latest_dif > latest_dea and latest_hist > prev_hist and latest_close >= ma20:
        score = max(0.0, min(1.0, 0.57 + latest_hist * 6.0 + max(0.0, latest_dif) * 0.4))
        return StrategySignal(
            symbol=symbol,
            strategy="macd_trend",
            action="BUY",
            score=round(score, 4),
            signal_price=round(latest_close, 3),
            stop_loss=round(min(ma20, latest_close * 0.95), 3),
            take_profit=round(latest_close * 1.09, 3),
            position_pct=round(max(0.06, min(0.17, 0.08 + score * 0.07)), 4),
            reason=f"MACD 金叉且柱体放大，DIF={latest_dif:.3f}，DEA={latest_dea:.3f}",
        )

    if latest_dif < latest_dea and latest_hist < prev_hist and latest_close <= ma20:
        score = max(0.0, min(1.0, 0.55 + abs(latest_hist) * 6.0))
        return StrategySignal(
            symbol=symbol,
            strategy="macd_trend",
            action="SELL",
            score=round(score, 4),
            signal_price=round(latest_close, 3),
            stop_loss=None,
            take_profit=None,
            position_pct=1.0,
            reason=f"MACD 死叉且柱体走弱，DIF={latest_dif:.3f}，DEA={latest_dea:.3f}",
        )
    return None
