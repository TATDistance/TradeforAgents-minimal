from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pandas as pd


def safe_pct_change(series: pd.Series, periods: int) -> pd.Series:
    return series.pct_change(periods=periods).replace([np.inf, -np.inf], np.nan)


def annualized_volatility(series: pd.Series, window: int = 20) -> pd.Series:
    returns = series.pct_change().fillna(0.0)
    return returns.rolling(window).std(ddof=0) * math.sqrt(252)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    dif = fast_ema - slow_ema
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = dif - dea
    return dif, dea, hist


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def bollinger_bands(series: pd.Series, window: int = 20, width: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    upper = mid + width * std
    lower = mid - width * std
    return upper, mid, lower


def true_range(frame: pd.DataFrame) -> pd.Series:
    prev_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    return true_range(frame).rolling(window).mean()


def donchian_high(frame: pd.DataFrame, window: int = 20) -> pd.Series:
    return frame["high"].rolling(window).max()


def donchian_low(frame: pd.DataFrame, window: int = 20) -> pd.Series:
    return frame["low"].rolling(window).min()
