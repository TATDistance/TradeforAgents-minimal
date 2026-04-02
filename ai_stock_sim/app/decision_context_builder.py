from __future__ import annotations

from typing import Dict, Mapping, Sequence

import pandas as pd

from .models import ExecutionGateState, MarketPhaseState, MarketRegimeState, StrategyFeature
from .settings import Settings, load_settings
from strategies.common import atr, macd, rsi, safe_pct_change


class DecisionContextBuilder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def build_for_symbol(
        self,
        symbol: str,
        snapshot: Mapping[str, object] | None,
        strategy_features: Sequence[StrategyFeature],
        frame: pd.DataFrame | None,
        market_regime: MarketRegimeState,
        portfolio_feedback: Mapping[str, object],
        phase_state: MarketPhaseState,
        execution_gate: ExecutionGateState,
        adaptive_weights: Mapping[str, object] | None = None,
        style_profile: Mapping[str, object] | None = None,
    ) -> Dict[str, object]:
        position_state = self._resolve_position_state(symbol, portfolio_feedback)
        technical_features = self._technical_features(frame)
        return {
            "symbol": symbol,
            "snapshot": dict(snapshot or {}),
            "strategy_features": {
                item.strategy_name: {
                    "score": item.score,
                    "direction": item.direction,
                    "strength": item.strength,
                    "reason": item.reason,
                    "features": item.features,
                }
                for item in strategy_features
            },
            "technical_features": technical_features,
            "market_regime": market_regime.model_dump(),
            "market_phase": phase_state.model_dump(),
            "execution_gate": execution_gate.model_dump(),
            "adaptive_weights": dict(adaptive_weights or {}),
            "style_profile": dict(style_profile or {}),
            "portfolio_state": {
                "equity": float(portfolio_feedback.get("equity", 0.0) or 0.0),
                "cash": float(portfolio_feedback.get("cash", 0.0) or 0.0),
                "cash_pct": float(portfolio_feedback.get("cash_pct", 0.0) or 0.0),
                "total_position_pct": float(portfolio_feedback.get("total_position_pct", 0.0) or 0.0),
                "drawdown": float(portfolio_feedback.get("drawdown", 0.0) or 0.0),
                "today_open_ratio": float(portfolio_feedback.get("today_open_ratio", 0.0) or 0.0),
                "risk_mode": str(portfolio_feedback.get("risk_mode", "NORMAL")),
            },
            "position_state": position_state,
            "risk_constraints": {
                "max_single_position_pct": self.settings.max_single_position_pct,
                "max_daily_open_position_pct": self.settings.max_daily_open_position_pct,
                "max_drawdown_pct": self.settings.max_drawdown_pct,
                "allow_new_buy": execution_gate.can_open_position and position_state.get("allow_new_buy", True),
                "allow_reduce": execution_gate.can_reduce_position,
                "allow_sell": execution_gate.can_reduce_position and int(position_state.get("can_sell_qty", 0)) > 0,
                "allow_execute_fill": execution_gate.can_execute_fill,
            },
        }

    def build_batch(
        self,
        symbols: Sequence[str],
        snapshot_map: Mapping[str, Mapping[str, object]],
        feature_map: Mapping[str, Sequence[StrategyFeature]],
        frame_map: Mapping[str, pd.DataFrame],
        market_regime: MarketRegimeState,
        portfolio_feedback: Mapping[str, object],
        phase_state: MarketPhaseState,
        execution_gate: ExecutionGateState,
        adaptive_weights: Mapping[str, object] | None = None,
        style_profile: Mapping[str, object] | None = None,
    ) -> Dict[str, Dict[str, object]]:
        return {
            symbol: self.build_for_symbol(
                symbol=symbol,
                snapshot=snapshot_map.get(symbol),
                strategy_features=feature_map.get(symbol, []),
                frame=frame_map.get(symbol),
                market_regime=market_regime,
                portfolio_feedback=portfolio_feedback,
                phase_state=phase_state,
                execution_gate=execution_gate,
                adaptive_weights=adaptive_weights,
                style_profile=style_profile,
            )
            for symbol in symbols
        }

    def _resolve_position_state(self, symbol: str, portfolio_feedback: Mapping[str, object]) -> Dict[str, object]:
        positions = portfolio_feedback.get("positions_detail") or []
        current = next((item for item in positions if isinstance(item, Mapping) and str(item.get("symbol")) == symbol), {})
        if not isinstance(current, Mapping):
            current = {}
        return {
            "has_position": bool(current),
            "qty": int(current.get("qty", 0) or 0),
            "avg_cost": float(current.get("avg_cost", 0.0) or 0.0),
            "last_price": float(current.get("last_price", 0.0) or 0.0),
            "market_value": float(current.get("market_value", 0.0) or 0.0),
            "unrealized_pnl": float(current.get("unrealized_pnl", 0.0) or 0.0),
            "unrealized_pct": float(current.get("unrealized_pct", 0.0) or 0.0),
            "can_sell_qty": int(current.get("can_sell_qty", 0) or 0),
            "hold_days": int(current.get("hold_days", 0) or 0),
            "allow_new_buy": float(portfolio_feedback.get("drawdown", 0.0) or 0.0) < self.settings.max_drawdown_pct,
        }

    @staticmethod
    def _technical_features(frame: pd.DataFrame | None) -> Dict[str, float]:
        if frame is None or frame.empty or "close" not in frame.columns:
            return {}
        close = frame["close"].astype(float)
        latest_close = float(close.iloc[-1])
        ma20 = float(close.rolling(20).mean().iloc[-1] or latest_close)
        ma60 = float(close.rolling(60).mean().iloc[-1] or latest_close)
        ret5 = float(safe_pct_change(close, 5).iloc[-1] or 0.0)
        ret20 = float(safe_pct_change(close, 20).iloc[-1] or 0.0)
        dif, dea, hist = macd(close)
        atr14 = float(atr(frame, window=14).iloc[-1] or 0.0)
        slope20 = 0.0
        if len(close) >= 20:
            base = float(close.iloc[-20] or latest_close)
            slope20 = 0.0 if base <= 0 else (latest_close - base) / base
        return {
            "latest_close": round(latest_close, 6),
            "ret_5d": round(ret5, 6),
            "ret_20d": round(ret20, 6),
            "rsi_14": round(float(rsi(close, 14).iloc[-1] or 50.0), 6),
            "macd_dif": round(float(dif.iloc[-1] or 0.0), 6),
            "macd_dea": round(float(dea.iloc[-1] or 0.0), 6),
            "macd_hist": round(float(hist.iloc[-1] or 0.0), 6),
            "ma20_bias": round(0.0 if ma20 <= 0 else (latest_close - ma20) / ma20, 6),
            "ma60_bias": round(0.0 if ma60 <= 0 else (latest_close - ma60) / ma60, 6),
            "atr_14": round(atr14, 6),
            "trend_slope_20d": round(slope20, 6),
        }
