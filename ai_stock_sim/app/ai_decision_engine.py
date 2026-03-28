from __future__ import annotations

import json
from datetime import date
from typing import Dict, Mapping, Sequence

from .ai_engine_protocol import AIDecisionEngineOutput, normalize_engine_output
from .settings import Settings, load_settings


class AIDecisionEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def decide_batch(
        self,
        contexts: Mapping[str, Mapping[str, object]],
        feature_scores: Mapping[str, Mapping[str, object]],
        trade_date: str | None = None,
    ) -> Dict[str, AIDecisionEngineOutput]:
        decisions: Dict[str, AIDecisionEngineOutput] = {}
        for symbol, context in contexts.items():
            decisions[symbol] = self.decide_symbol(
                symbol=symbol,
                context=context,
                feature_score_payload=feature_scores.get(symbol, {}),
                trade_date=trade_date,
            )
        return decisions

    def decide_symbol(
        self,
        symbol: str,
        context: Mapping[str, object],
        feature_score_payload: Mapping[str, object],
        trade_date: str | None = None,
    ) -> AIDecisionEngineOutput:
        market_regime = dict(context.get("market_regime") or {})
        portfolio_state = dict(context.get("portfolio_state") or {})
        position_state = dict(context.get("position_state") or {})
        risk_constraints = dict(context.get("risk_constraints") or {})
        snapshot = dict(context.get("snapshot") or {})
        technical = dict(context.get("technical_features") or {})
        research = self._load_research_cache(symbol, trade_date or date.today().isoformat())

        regime_name = str(market_regime.get("regime") or self.settings.market_regime.default_regime)
        portfolio_risk_mode = str(portfolio_state.get("risk_mode") or "NORMAL").upper()
        feature_score = float(feature_score_payload.get("feature_score") or 0.0)
        final_score = float(feature_score_payload.get("final_score") or feature_score)
        direction = str(feature_score_payload.get("dominant_direction") or "NEUTRAL")
        warnings = []
        if float(snapshot.get("pct_change") or 0.0) >= self.settings.limit_up_filter_pct:
            warnings.append("已接近涨停，不宜追高")
        if float(snapshot.get("amount") or 0.0) < self.settings.min_turnover:
            warnings.append("成交额偏低")
        if research.get("warning"):
            warnings.append(str(research["warning"]))

        risk_mode = self._resolve_risk_mode(regime_name, portfolio_risk_mode, float(portfolio_state.get("drawdown") or 0.0))
        has_position = bool(position_state.get("has_position"))
        can_sell_qty = int(position_state.get("can_sell_qty") or 0)
        unrealized_pct = float(position_state.get("unrealized_pct") or 0.0)
        hold_days = int(position_state.get("hold_days") or 0)
        allow_new_buy = bool(risk_constraints.get("allow_new_buy", True))
        research_bias = float(research.get("bias_score") or 0.0)
        technical_bonus = self._technical_bonus(technical)
        decision_score = final_score * 0.55 + feature_score * 0.25 + research_bias * 0.12 + technical_bonus * 0.08
        decision_score = max(-1.0, min(1.0, decision_score))

        if risk_mode == "RISK_OFF" and not has_position:
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "AVOID_NEW_BUY",
                    "confidence": min(0.95, 0.62 + abs(decision_score) * 0.2),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": "账户或市场已进入风险关闭模式，暂停新增仓位。",
                    "warnings": warnings,
                    "final_score": round(decision_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        if has_position:
            if can_sell_qty > 0 and (risk_mode == "RISK_OFF" or unrealized_pct <= -0.05 or decision_score <= -0.42):
                return normalize_engine_output(
                    {
                        "symbol": symbol,
                        "action": "SELL",
                        "confidence": min(0.96, 0.66 + abs(decision_score) * 0.22),
                        "risk_mode": risk_mode,
                        "holding_bias": "SHORT_TERM",
                        "reason": "持仓已不符合当前多因子条件，优先退出控制风险。",
                        "warnings": warnings,
                        "final_score": round(decision_score, 4),
                        "feature_score": round(feature_score, 4),
                    },
                    symbol,
                )
            if can_sell_qty > 0 and (
                (unrealized_pct >= 0.04 and risk_mode in {"DEFENSIVE", "RISK_OFF"})
                or (hold_days >= 8 and decision_score <= 0.12)
            ):
                return normalize_engine_output(
                    {
                        "symbol": symbol,
                        "action": "REDUCE",
                        "reduce_pct": 0.5 if unrealized_pct >= 0.06 else 0.3,
                        "confidence": min(0.9, 0.60 + max(unrealized_pct, 0.0) * 2.0),
                        "risk_mode": risk_mode,
                        "holding_bias": "SHORT_TERM",
                        "reason": "已有持仓进入保护利润或控制回撤阶段，建议部分减仓。",
                        "warnings": warnings,
                        "final_score": round(decision_score, 4),
                        "feature_score": round(feature_score, 4),
                    },
                    symbol,
                )
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "HOLD",
                    "confidence": min(0.88, 0.55 + max(decision_score, 0.0) * 0.25),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": "当前持仓与市场状态基本匹配，继续持有观察。",
                    "warnings": warnings,
                    "final_score": round(decision_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        if not allow_new_buy:
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "AVOID_NEW_BUY",
                    "confidence": 0.72,
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": "当前账户约束不允许继续新开仓。",
                    "warnings": warnings,
                    "final_score": round(decision_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        if direction == "LONG" and decision_score >= self.settings.fusion.min_final_score_to_buy:
            base_pct = min(self.settings.max_single_position_pct, 0.06 + decision_score * 0.12)
            if risk_mode == "DEFENSIVE":
                base_pct *= 0.65
            base_pct *= max(0.4, min(1.0, float(portfolio_state.get("cash_pct") or 0.0) + 0.15))
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "BUY",
                    "position_pct": round(max(0.03, min(base_pct, self.settings.max_single_position_pct)), 4),
                    "confidence": min(0.94, 0.58 + decision_score * 0.25),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": "多因子特征、账户状态与市场环境共振，满足新开仓条件。",
                    "warnings": warnings,
                    "final_score": round(decision_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        return normalize_engine_output(
            {
                "symbol": symbol,
                "action": "HOLD" if direction != "SHORT" else "AVOID_NEW_BUY",
                "confidence": min(0.82, 0.5 + abs(decision_score) * 0.18),
                "risk_mode": risk_mode,
                "holding_bias": "SHORT_TERM",
                "reason": "当前没有形成足够强的新开仓优势，继续等待更明确机会。",
                "warnings": warnings,
                "final_score": round(decision_score, 4),
                "feature_score": round(feature_score, 4),
            },
            symbol,
        )

    def _load_research_cache(self, symbol: str, trade_date: str) -> Dict[str, object]:
        if not self.settings.decision_engine.use_decision_json_as_research_cache:
            return {}
        path = self.settings.tradeforagents_results_dir / symbol / trade_date / "decision.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        action = str(payload.get("action") or "").upper()
        bias_score = 0.0
        if action in {"BUY", "买入"}:
            bias_score = 0.25
        elif action in {"SELL", "卖出"}:
            bias_score = -0.25
        return {
            "bias_score": bias_score,
            "confidence": float(payload.get("confidence", 0.5) or 0.5),
            "warning": str(payload.get("warning") or ""),
            "reason": str(payload.get("reason") or payload.get("reasoning") or ""),
        }

    @staticmethod
    def _resolve_risk_mode(regime_name: str, portfolio_risk_mode: str, drawdown: float) -> str:
        if regime_name == "RISK_OFF" or portfolio_risk_mode == "RISK_OFF" or drawdown >= 0.05:
            return "RISK_OFF"
        if regime_name in {"HIGH_VOLATILITY", "TRENDING_DOWN"} or portfolio_risk_mode == "DEFENSIVE" or drawdown >= 0.03:
            return "DEFENSIVE"
        return "NORMAL"

    @staticmethod
    def _technical_bonus(technical: Mapping[str, object]) -> float:
        rsi_value = float(technical.get("rsi_14") or 50.0)
        slope20 = float(technical.get("trend_slope_20d") or 0.0)
        ma20_bias = float(technical.get("ma20_bias") or 0.0)
        macd_hist = float(technical.get("macd_hist") or 0.0)
        bonus = slope20 * 1.4 + ma20_bias * 1.6 + macd_hist * 2.0
        if rsi_value >= 75:
            bonus -= 0.08
        elif rsi_value <= 30:
            bonus += 0.06
        return max(-0.25, min(0.25, bonus))
