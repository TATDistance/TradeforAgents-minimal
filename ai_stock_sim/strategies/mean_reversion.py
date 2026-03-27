from __future__ import annotations

import pandas as pd

from app.models import StrategySignal
from app.settings import Settings

from .common import bollinger_bands, rsi


def generate_signal(symbol: str, frame: pd.DataFrame, settings: Settings) -> StrategySignal | None:
    window = settings.strategy.mean_reversion_boll_window
    if len(frame) < max(window, 20) + 5:
        return None

    close = frame["close"]
    latest_close = float(close.iloc[-1])
    upper, mid, lower = bollinger_bands(close, window=window, width=2.0)
    current_rsi = float(rsi(close, window=14).iloc[-1] or 50.0)
    lower_band = float(lower.iloc[-1] or latest_close)
    mid_band = float(mid.iloc[-1] or latest_close)

    if latest_close > lower_band * 1.02 or current_rsi > settings.strategy.mean_reversion_rsi_low:
        return None

    rebound_room = max(0.0, (mid_band - latest_close) / max(latest_close, 0.01))
    score = max(0.0, min(1.0, 0.50 + rebound_room * 3.0 + (35 - current_rsi) * 0.01))
    stop_loss = round(min(latest_close * 0.96, lower_band * 0.985), 3)
    take_profit = round(max(mid_band, latest_close * 1.05), 3)
    position_pct = max(0.05, min(0.12, 0.06 + score * 0.05))

    return StrategySignal(
        symbol=symbol,
        strategy="mean_reversion",
        action="BUY",
        score=round(score, 4),
        signal_price=round(latest_close, 3),
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_pct=round(position_pct, 4),
        reason=f"RSI={current_rsi:.1f} 且价格靠近布林下轨，符合超跌反弹条件",
    )
