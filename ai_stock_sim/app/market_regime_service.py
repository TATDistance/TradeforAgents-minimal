from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from .models import MarketRegimeState
from .settings import Settings, load_settings


class MarketRegimeService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def detect_market_regime(self, snapshot: pd.DataFrame | None, portfolio_feedback: Mapping[str, float | str] | None = None) -> MarketRegimeState:
        return self.evaluate(snapshot, portfolio_feedback)

    def evaluate(self, snapshot: pd.DataFrame | None, portfolio_feedback: Mapping[str, float | str] | None = None) -> MarketRegimeState:
        if not self.settings.market_regime.enabled:
            return MarketRegimeState(regime=self.settings.market_regime.default_regime, confidence=0.5, reason="市场状态机已关闭", risk_bias="NORMAL")
        if snapshot is None or snapshot.empty:
            return MarketRegimeState(
                regime=self.settings.market_regime.default_regime,
                confidence=0.35,
                reason="快照为空，已降级为默认市场状态",
                risk_bias="NORMAL",
            )

        pct_series = snapshot.get("pct_change", pd.Series(dtype=float)).astype(float)
        amount_series = snapshot.get("amount", pd.Series(dtype=float)).astype(float)
        mean_change = float(pct_series.mean()) if not pct_series.empty else 0.0
        breadth = float((pct_series > 0).mean()) if not pct_series.empty else 0.5
        volatility = float(pct_series.std(ddof=0)) if len(pct_series) > 1 else 0.0
        avg_amount = float(amount_series.mean()) if not amount_series.empty else 0.0
        portfolio_drawdown = float((portfolio_feedback or {}).get("drawdown", 0.0) or 0.0)

        if portfolio_drawdown >= self.settings.portfolio_feedback.drawdown_risk_off_threshold:
            regime = "RISK_OFF"
            risk_bias = "RISK_OFF"
            reason = "账户回撤已达到风险关闭阈值，组合进入风控优先状态"
            confidence = 0.85
        elif volatility >= 0.035:
            regime = "HIGH_VOLATILITY"
            risk_bias = "DEFENSIVE"
            reason = "市场涨跌分布离散度较高，短期波动显著放大"
            confidence = min(0.9, 0.55 + volatility * 3.0)
        elif mean_change >= 0.008 and breadth >= 0.58:
            regime = "TRENDING_UP"
            risk_bias = "NORMAL"
            reason = "市场整体上涨广度较好，短线趋势偏强"
            confidence = min(0.9, 0.55 + mean_change * 10.0)
        elif mean_change <= -0.008 and breadth <= 0.42:
            regime = "TRENDING_DOWN"
            risk_bias = "DEFENSIVE"
            reason = "市场整体下跌广度偏强，趋势承压"
            confidence = min(0.9, 0.55 + abs(mean_change) * 10.0)
        else:
            regime = "RANGE_BOUND"
            risk_bias = "NORMAL"
            reason = "指数与个股分布未形成明显单边趋势，市场更偏震荡"
            confidence = 0.55

        if avg_amount < self.settings.min_turnover:
            confidence = max(0.35, confidence - 0.1)
            reason += "；整体成交额活跃度一般"

        return MarketRegimeState(
            regime=regime,
            confidence=round(confidence, 4),
            reason=reason,
            risk_bias=risk_bias,
            breadth=round(breadth, 4),
            volatility=round(volatility, 4),
        )

    def save_state(self, state: MarketRegimeState) -> Path:
        path = self.settings.cache_dir / "market_regime_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_state(self) -> MarketRegimeState:
        path = self.settings.cache_dir / "market_regime_state.json"
        if not path.exists():
            return MarketRegimeState(regime=self.settings.market_regime.default_regime, confidence=0.35, reason="暂无缓存市场状态", risk_bias="NORMAL")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return MarketRegimeState(regime=self.settings.market_regime.default_regime, confidence=0.35, reason="市场状态缓存损坏，已降级", risk_bias="NORMAL")
        return MarketRegimeState(**payload)
