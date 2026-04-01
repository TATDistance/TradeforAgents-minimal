from __future__ import annotations

from typing import List

import pandas as pd

from .models import StrategyDirection, StrategyFeature
from .settings import Settings, load_settings
from strategies.common import annualized_volatility, atr, bollinger_bands, donchian_high, donchian_low, macd, rsi, safe_pct_change


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _direction_from_score(score: float, threshold: float = 0.12) -> StrategyDirection:
    if score >= threshold:
        return "LONG"
    if score <= -threshold:
        return "SHORT"
    return "NEUTRAL"


class FeatureService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def build_for_symbol(self, symbol: str, frame: pd.DataFrame) -> List[StrategyFeature]:
        if frame.empty or "close" not in frame.columns:
            return []
        latest = frame.iloc[-1]
        close = frame["close"].astype(float)
        latest_close = float(latest["close"])
        ma10 = float(close.rolling(10).mean().iloc[-1] or latest_close)
        ma20 = float(close.rolling(20).mean().iloc[-1] or latest_close)
        ma30 = float(close.rolling(30).mean().iloc[-1] or latest_close)
        ma60 = float(close.rolling(60).mean().iloc[-1] or ma30)
        ret5 = float(safe_pct_change(close, 5).iloc[-1] or 0.0)
        ret20 = float(safe_pct_change(close, 20).iloc[-1] or 0.0)
        ret60 = float(safe_pct_change(close, 60).iloc[-1] or 0.0)
        vol20 = float(annualized_volatility(close, 20).iloc[-1] or 0.0)
        rsi14 = float(rsi(close, 14).iloc[-1] or 50.0)
        dif, dea, hist = macd(
            close,
            fast=self.settings.strategy.macd_fast_window,
            slow=self.settings.strategy.macd_slow_window,
            signal=self.settings.strategy.macd_signal_window,
        )
        macd_dif = float(dif.iloc[-1] or 0.0)
        macd_dea = float(dea.iloc[-1] or 0.0)
        macd_hist = float(hist.iloc[-1] or 0.0)
        upper, mid, lower = bollinger_bands(close, window=self.settings.strategy.mean_reversion_boll_window, width=2.0)
        lower_band = float(lower.iloc[-1] or latest_close)
        upper_band = float(upper.iloc[-1] or latest_close)
        mid_band = float(mid.iloc[-1] or latest_close)
        atr14 = float(atr(frame, window=self.settings.strategy.atr_window).iloc[-1] or 0.0)
        dc_high = float(donchian_high(frame, window=self.settings.strategy.breakout_window).iloc[-1] or latest_close)
        dc_low = float(donchian_low(frame, window=self.settings.strategy.breakout_window).iloc[-1] or latest_close)

        features: List[StrategyFeature] = []
        features.append(self._momentum_feature(symbol, latest_close, ma20, ma60, ret5, ret20, ret60, vol20))
        features.append(self._dual_ma_feature(symbol, close, latest_close))
        features.append(self._macd_feature(symbol, latest_close, ma20, macd_dif, macd_dea, macd_hist))
        features.append(self._mean_reversion_feature(symbol, latest_close, lower_band, upper_band, mid_band, rsi14))
        features.append(self._breakout_feature(symbol, latest_close, dc_high, dc_low, atr14))
        features.append(self._trend_pullback_feature(symbol, latest_close, ma20, ma60))
        return features

    def _momentum_feature(
        self,
        symbol: str,
        latest_close: float,
        ma20: float,
        ma60: float,
        ret5: float,
        ret20: float,
        ret60: float,
        vol20: float,
    ) -> StrategyFeature:
        ma_bias = 0.0 if ma60 <= 0 else (ma20 - ma60) / ma60
        raw_score = ret20 * 5.5 + ret5 * 1.5 + ret60 * 1.5 + ma_bias * 4.0 - vol20 * 0.35
        score = _clamp(raw_score)
        if latest_close < ma20 and score > 0:
            score *= 0.65
        direction = _direction_from_score(score)
        reason = f"20日动量 {ret20:.2%}，20/60 日均线差 {ma_bias:.2%}，波动率 {vol20:.2f}"
        return StrategyFeature(
            symbol=symbol,
            strategy_name="momentum",
            score=round(score, 4),
            direction=direction,
            strength=round(abs(score), 4),
            reason=reason,
            features={
                "ret_5d": round(ret5, 6),
                "ret_20d": round(ret20, 6),
                "ret_60d": round(ret60, 6),
                "volatility": round(vol20, 6),
                "ma_bias_20_60": round(ma_bias, 6),
            },
        )

    def _dual_ma_feature(self, symbol: str, close: pd.Series, latest_close: float) -> StrategyFeature:
        fast_window = self.settings.strategy.dual_ma_fast_window
        slow_window = self.settings.strategy.dual_ma_slow_window
        fast_ma = close.rolling(fast_window).mean()
        slow_ma = close.rolling(slow_window).mean()
        latest_fast = float(fast_ma.iloc[-1] or latest_close)
        latest_slow = float(slow_ma.iloc[-1] or latest_close)
        if len(fast_ma) >= 2:
            prev_fast = float(fast_ma.iloc[-2] or latest_fast)
        else:
            prev_fast = latest_fast
        if len(slow_ma) >= 2:
            prev_slow = float(slow_ma.iloc[-2] or latest_slow)
        else:
            prev_slow = latest_slow
        spread = 0.0 if latest_slow <= 0 else (latest_fast - latest_slow) / latest_slow
        cross_bonus = 0.25 if prev_fast <= prev_slow and latest_fast > latest_slow else -0.25 if prev_fast >= prev_slow and latest_fast < latest_slow else 0.0
        score = _clamp(spread * 10.0 + cross_bonus)
        return StrategyFeature(
            symbol=symbol,
            strategy_name="dual_ma",
            score=round(score, 4),
            direction=_direction_from_score(score),
            strength=round(abs(score), 4),
            reason=f"{fast_window}/{slow_window} 日均线差 {spread:.2%}，近期交叉偏向 {'上行' if score > 0 else '下行' if score < 0 else '中性'}",
            features={
                "fast_ma": round(latest_fast, 6),
                "slow_ma": round(latest_slow, 6),
                "ma_spread": round(spread, 6),
                "cross_bonus": round(cross_bonus, 6),
            },
        )

    def _macd_feature(
        self,
        symbol: str,
        latest_close: float,
        ma20: float,
        macd_dif: float,
        macd_dea: float,
        macd_hist: float,
    ) -> StrategyFeature:
        price_bias = 0.0 if ma20 <= 0 else (latest_close - ma20) / ma20
        score = _clamp((macd_dif - macd_dea) * 4.0 + macd_hist * 8.0 + price_bias * 2.0)
        return StrategyFeature(
            symbol=symbol,
            strategy_name="macd_trend",
            score=round(score, 4),
            direction=_direction_from_score(score),
            strength=round(abs(score), 4),
            reason=f"MACD DIF {macd_dif:.3f} / DEA {macd_dea:.3f} / 柱体 {macd_hist:.3f}",
            features={
                "macd_dif": round(macd_dif, 6),
                "macd_dea": round(macd_dea, 6),
                "macd_hist": round(macd_hist, 6),
                "price_ma20_bias": round(price_bias, 6),
            },
        )

    def _mean_reversion_feature(
        self,
        symbol: str,
        latest_close: float,
        lower_band: float,
        upper_band: float,
        mid_band: float,
        rsi14: float,
    ) -> StrategyFeature:
        rebound_room = 0.0 if latest_close <= 0 else (mid_band - latest_close) / latest_close
        overheat = 0.0 if latest_close <= 0 else (latest_close - mid_band) / latest_close
        score = _clamp(rebound_room * 5.0 + (35.0 - rsi14) * 0.02 - max(0.0, overheat) * 3.0)
        if latest_close > upper_band * 0.995 and rsi14 > 70:
            score = -max(abs(score), 0.35)
        return StrategyFeature(
            symbol=symbol,
            strategy_name="mean_reversion",
            score=round(score, 4),
            direction=_direction_from_score(score),
            strength=round(abs(score), 4),
            reason=f"RSI {rsi14:.1f}，距布林中轨空间 {rebound_room:.2%}",
            features={
                "rsi_14": round(rsi14, 6),
                "lower_band": round(lower_band, 6),
                "upper_band": round(upper_band, 6),
                "mid_band": round(mid_band, 6),
                "rebound_room": round(rebound_room, 6),
            },
        )

    def _breakout_feature(self, symbol: str, latest_close: float, dc_high: float, dc_low: float, atr14: float) -> StrategyFeature:
        breakout_up = 0.0 if dc_high <= 0 else (latest_close - dc_high) / dc_high
        breakout_down = 0.0 if dc_low <= 0 else (dc_low - latest_close) / dc_low
        raw = breakout_up * 12.0 - breakout_down * 10.0 + (atr14 / max(latest_close, 0.01)) * 0.5
        score = _clamp(raw)
        return StrategyFeature(
            symbol=symbol,
            strategy_name="breakout",
            score=round(score, 4),
            direction=_direction_from_score(score),
            strength=round(abs(score), 4),
            reason=f"突破高点偏离 {breakout_up:.2%}，跌破低点偏离 {breakout_down:.2%}",
            features={
                "donchian_high": round(dc_high, 6),
                "donchian_low": round(dc_low, 6),
                "breakout_up_pct": round(breakout_up, 6),
                "breakout_down_pct": round(breakout_down, 6),
                "atr_14": round(atr14, 6),
            },
        )

    def _trend_pullback_feature(self, symbol: str, latest_close: float, ma20: float, ma60: float) -> StrategyFeature:
        trend_strength = 0.0 if ma60 <= 0 else (ma20 - ma60) / ma60
        distance = 0.0 if ma20 <= 0 else (latest_close - ma20) / ma20
        score = _clamp(trend_strength * 6.0 + (0.02 - abs(distance)) * 12.0)
        if latest_close < ma60:
            score = -max(abs(score), 0.25)
        return StrategyFeature(
            symbol=symbol,
            strategy_name="trend_pullback",
            score=round(score, 4),
            direction=_direction_from_score(score),
            strength=round(abs(score), 4),
            reason=f"趋势强度 {trend_strength:.2%}，相对 20 日均线距离 {distance:.2%}",
            features={
                "trend_strength": round(trend_strength, 6),
                "pullback_distance": round(distance, 6),
                "ma20": round(ma20, 6),
                "ma60": round(ma60, 6),
            },
        )
