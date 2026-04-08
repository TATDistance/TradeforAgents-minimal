from __future__ import annotations

import json
from datetime import date
from typing import Dict, Mapping, Sequence

from .ai_engine_protocol import AIDecisionEngineOutput, normalize_engine_output
from .entry_structure_service import EntryStructureService
from .exit_structure_service import ExitStructureService
from .score_service import ScoreService
from .settings import Settings, load_settings, resolve_max_single_position_pct


class AIDecisionEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.score_service = ScoreService(self.settings)
        self.entry_structure_service = EntryStructureService(self.settings)
        self.exit_structure_service = ExitStructureService(self.settings)

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
        market_phase = dict(context.get("market_phase") or {})
        execution_gate = dict(context.get("execution_gate") or {})
        adaptive_weights = dict(context.get("adaptive_weights") or {})
        style_profile = dict(context.get("style_profile") or {})
        research = self._load_research_cache(symbol, trade_date or date.today().isoformat())

        regime_name = str(market_regime.get("regime") or self.settings.market_regime.default_regime)
        portfolio_risk_mode = str(portfolio_state.get("risk_mode") or "NORMAL").upper()
        feature_score = float(feature_score_payload.get("feature_score") or 0.0)
        final_score = float(feature_score_payload.get("final_score") or feature_score)
        direction = str(feature_score_payload.get("dominant_direction") or "NEUTRAL")
        warnings = []
        snapshot_pct_change = self._normalize_pct_change(snapshot.get("pct_change"))
        if snapshot_pct_change >= self.settings.limit_up_filter_pct:
            warnings.append("已接近涨停，不宜追高")
        if float(snapshot.get("amount") or 0.0) < self.settings.min_turnover:
            warnings.append("成交额偏低")
        if research.get("warning"):
            warnings.append(str(research["warning"]))
        capital_profile = self._resolve_capital_profile(portfolio_state=portfolio_state, snapshot=snapshot)
        if capital_profile["is_small_account"] and capital_profile["lot_ratio"] >= capital_profile["affordable_lot_pct"]:
            warnings.append(
                "小资金账户买一手约占总资产 {0:.1f}%".format(float(capital_profile["lot_ratio"]) * 100.0)
            )
        max_single_position_pct = float(
            risk_constraints.get("max_single_position_pct")
            or resolve_max_single_position_pct(self.settings, float(portfolio_state.get("equity") or 0.0))
        )

        risk_mode = self._resolve_risk_mode(regime_name, portfolio_risk_mode, float(portfolio_state.get("drawdown") or 0.0))
        has_position = bool(position_state.get("has_position"))
        can_sell_qty = int(position_state.get("can_sell_qty") or 0)
        unrealized_pct = float(position_state.get("unrealized_pct") or 0.0)
        hold_days = int(position_state.get("hold_days") or 0)
        allow_new_buy = bool(risk_constraints.get("allow_new_buy", True))
        allow_execute_fill = bool(execution_gate.get("can_execute_fill", False))
        phase_name = str(market_phase.get("phase") or "NON_TRADING_DAY")
        entry_structure = dict(
            context.get("entry_structure")
            or self.entry_structure_service.evaluate(
                snapshot=snapshot,
                technical=technical,
                market_regime=market_regime,
                position_state=position_state,
            )
        )
        research_bias = float(research.get("bias_score") or 0.0)
        ai_score = self._compute_ai_score(
            direction=direction,
            feature_score=feature_score,
            final_score=final_score,
            research_bias=research_bias,
            market_regime=market_regime,
            portfolio_state=portfolio_state,
            position_state=position_state,
            snapshot=snapshot,
            technical=technical,
            allow_new_buy=allow_new_buy,
            adaptive_weights=adaptive_weights,
            style_profile=style_profile,
            capital_profile=capital_profile,
            entry_structure=entry_structure,
        )
        setup_bundle = self.score_service.compute_scores(
            symbol=symbol,
            feature_score=feature_score,
            dominant_direction=direction,
            ai_score=ai_score,
            market_risk_penalty=float(feature_score_payload.get("market_risk_penalty") or 0.0),
            portfolio_risk_penalty=float(feature_score_payload.get("portfolio_risk_penalty") or 0.0),
            phase_name=phase_name,
            execution_gate=execution_gate,
            portfolio_state=portfolio_state,
            position_state=position_state,
            risk_mode=risk_mode,
            risk_penalty_multiplier=float(adaptive_weights.get("risk_penalty_multiplier") or 1.0),
        )
        setup_score = float(setup_bundle.get("setup_score") or 0.0)
        execution_score = float(setup_bundle.get("execution_score") or 0.0)
        phase_penalty = float(setup_bundle.get("phase_penalty") or 0.0)
        gate_penalty = float(setup_bundle.get("gate_penalty") or 0.0)
        market_risk_penalty = float(setup_bundle.get("market_risk_penalty") or 0.0)
        portfolio_risk_penalty = float(setup_bundle.get("portfolio_risk_penalty") or 0.0)
        exit_structure = dict(
            context.get("exit_structure")
            or self.exit_structure_service.evaluate(
                technical=technical,
                position_state=position_state,
                execution_score=execution_score,
                risk_mode=risk_mode,
            )
        )
        entry_type = str(entry_structure.get("entry_type") or "watch_point")
        entry_quality_score = float(entry_structure.get("entry_quality_score") or 0.0)
        entry_reason = str(entry_structure.get("entry_reason") or "")
        if entry_type == "chase_block":
            warnings.append("结构化买点判定为禁追高")
        elif entry_type == "watch_point" and direction == "LONG":
            warnings.append("当前仅满足观察点，买点尚未确认")

        if not allow_execute_fill:
            return self._build_non_executable_decision(
                symbol=symbol,
                has_position=has_position,
                can_sell_qty=can_sell_qty,
                direction=direction,
                setup_score=setup_score,
                execution_score=execution_score,
                feature_score=feature_score,
                ai_score=ai_score,
                risk_mode=risk_mode,
                warnings=warnings,
                allow_new_buy=allow_new_buy,
                phase_name=phase_name,
                market_risk_penalty=market_risk_penalty,
                portfolio_risk_penalty=portfolio_risk_penalty,
                phase_penalty=phase_penalty,
                gate_penalty=gate_penalty,
                capital_profile=capital_profile,
                entry_structure=entry_structure,
            )

        if risk_mode == "RISK_OFF" and not has_position:
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "AVOID_NEW_BUY",
                    "confidence": min(0.95, 0.62 + abs(execution_score) * 0.2),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": "账户或市场已进入风险关闭模式，暂停新增仓位。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        if has_position:
            position_exit = self._build_position_exit_decision(
                symbol=symbol,
                risk_mode=risk_mode,
                can_sell_qty=can_sell_qty,
                unrealized_pct=unrealized_pct,
                execution_score=execution_score,
                setup_score=setup_score,
                feature_score=feature_score,
                ai_score=ai_score,
                market_risk_penalty=market_risk_penalty,
                portfolio_risk_penalty=portfolio_risk_penalty,
                phase_penalty=phase_penalty,
                gate_penalty=gate_penalty,
                technical=technical,
                warnings=warnings,
                exit_structure=exit_structure,
            )
            if position_exit:
                return normalize_engine_output(position_exit, symbol)
            if can_sell_qty > 0 and (
                (unrealized_pct >= 0.04 and risk_mode in {"DEFENSIVE", "RISK_OFF"})
                or (hold_days >= 8 and execution_score <= self.settings.scoring.min_execution_score_to_reduce * 0.3)
                or execution_score <= -self.settings.scoring.min_execution_score_to_reduce
            ):
                return normalize_engine_output(
                    {
                        "symbol": symbol,
                        "action": "REDUCE",
                        "reduce_pct": 0.5 if unrealized_pct >= 0.06 else 0.3,
                        "confidence": min(0.9, 0.60 + max(unrealized_pct, 0.0) * 2.0),
                        "ai_score": round(ai_score, 4),
                        "setup_score": round(setup_score, 4),
                        "execution_score": round(execution_score, 4),
                        "market_risk_penalty": round(market_risk_penalty, 4),
                        "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                        "phase_penalty": round(phase_penalty, 4),
                        "gate_penalty": round(gate_penalty, 4),
                        "risk_mode": risk_mode,
                        "holding_bias": "SHORT_TERM",
                        "reason": str(exit_structure.get("exit_reason") or "已有持仓进入保护利润或控制回撤阶段，建议部分减仓。"),
                        "warnings": warnings,
                        "final_score": round(execution_score, 4),
                        "feature_score": round(feature_score, 4),
                        "extra": {
                            "exit_type": str(exit_structure.get("exit_type") or "reduce_on_weakening"),
                            "exit_quality_score": float(exit_structure.get("exit_quality_score") or 0.0),
                        },
                    },
                    symbol,
                )
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "HOLD",
                    "confidence": min(0.88, 0.55 + max(setup_score, 0.0) * 0.25),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": str(exit_structure.get("exit_reason") or "当前持仓与市场状态基本匹配，继续持有观察。"),
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                    "extra": {
                        "exit_type": str(exit_structure.get("exit_type") or "hold_on_structure"),
                        "exit_quality_score": float(exit_structure.get("exit_quality_score") or 0.0),
                    },
                },
                symbol,
            )

        if not allow_new_buy:
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "AVOID_NEW_BUY",
                    "confidence": 0.72,
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": "当前账户约束不允许继续新开仓。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        buy_threshold = self.settings.scoring.min_execution_score_to_buy + float(capital_profile["buy_threshold_bonus"])
        watch_threshold = self.settings.scoring.min_setup_score_to_watch + float(capital_profile["watch_threshold_bonus"])
        if entry_type == "watch_point":
            buy_threshold += 0.08
        elif entry_type == "chase_block":
            buy_threshold += 0.20

        if (
            direction == "LONG"
            and capital_profile["is_small_account"]
            and float(capital_profile["lot_ratio"]) >= float(capital_profile["block_lot_pct"])
        ):
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "WATCH_NEXT_DAY",
                    "confidence": min(0.84, 0.54 + max(setup_score, 0.0) * 0.2),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": entry_reason or "该标的一手资金占用对小资金账户过高，先观察更适合小本金参与的机会。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                    "extra": {
                        "entry_type": entry_type,
                        "entry_quality_score": entry_quality_score,
                    },
                },
                symbol,
            )

        if direction == "LONG" and bool(entry_structure.get("allow_buy", False)) and execution_score >= buy_threshold:
            base_pct = min(max_single_position_pct, 0.06 + execution_score * 0.12)
            if risk_mode == "DEFENSIVE":
                base_pct *= 0.65
            base_pct *= max(0.4, min(1.0, float(portfolio_state.get("cash_pct") or 0.0) + 0.15))
            if capital_profile["is_small_account"]:
                base_pct *= float(capital_profile["position_scale"])
                lot_ratio = float(capital_profile["lot_ratio"] or 0.0)
                if 0.0 < lot_ratio <= max_single_position_pct:
                    base_pct = max(base_pct, min(max_single_position_pct, lot_ratio * 1.02))
            base_pct *= max(0.35, min(1.0, float(entry_structure.get("position_scale") or 1.0)))
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "BUY",
                    "position_pct": round(max(0.03, min(base_pct, max_single_position_pct)), 4),
                    "confidence": min(0.94, 0.58 + execution_score * 0.25),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": entry_reason or "多因子特征、账户状态与市场环境共振，满足新开仓条件。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                    "extra": {
                        "entry_type": entry_type,
                        "entry_quality_score": entry_quality_score,
                    },
                },
                symbol,
            )

        neutral_action = "WATCH_NEXT_DAY" if setup_score >= watch_threshold else "AVOID_NEW_BUY" if direction == "SHORT" else "HOLD"
        return normalize_engine_output(
            {
                "symbol": symbol,
                "action": neutral_action,
                "confidence": min(0.82, 0.5 + abs(setup_score) * 0.18),
                "ai_score": round(ai_score, 4),
                "setup_score": round(setup_score, 4),
                "execution_score": round(execution_score, 4),
                "market_risk_penalty": round(market_risk_penalty, 4),
                "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                "phase_penalty": round(phase_penalty, 4),
                "gate_penalty": round(gate_penalty, 4),
                "risk_mode": risk_mode,
                "holding_bias": "SHORT_TERM",
                "reason": entry_reason or str(setup_bundle.get("explain") or "当前没有形成足够强的新开仓优势，继续等待更明确机会。"),
                "warnings": warnings,
                "final_score": round(execution_score, 4),
                "feature_score": round(feature_score, 4),
                "extra": {
                    "entry_type": entry_type,
                    "entry_quality_score": entry_quality_score,
                    "exit_type": str(exit_structure.get("exit_type") or ""),
                },
            },
            symbol,
        )

    @staticmethod
    def _normalize_pct_change(value: object) -> float:
        try:
            raw = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if abs(raw) >= 1.0:
            return raw / 100.0
        return raw

    def _build_non_executable_decision(
        self,
        symbol: str,
        has_position: bool,
        can_sell_qty: int,
        direction: str,
        setup_score: float,
        execution_score: float,
        feature_score: float,
        ai_score: float,
        risk_mode: str,
        warnings: list[str],
        allow_new_buy: bool,
        phase_name: str,
        market_risk_penalty: float,
        portfolio_risk_penalty: float,
        phase_penalty: float,
        gate_penalty: float,
        capital_profile: Mapping[str, float | bool] | None = None,
        entry_structure: Mapping[str, object] | None = None,
    ) -> AIDecisionEngineOutput:
        allow_prepare_actions = not (phase_name == "POST_CLOSE" and not self.settings.market_session.allow_post_close_paper_execution)
        resolved_capital_profile = dict(capital_profile or {})
        resolved_entry_structure = dict(entry_structure or {})
        watch_threshold = self.settings.scoring.min_setup_score_to_watch + float(
            resolved_capital_profile.get("watch_threshold_bonus") or 0.0
        )
        if has_position:
            if allow_prepare_actions and can_sell_qty > 0 and (risk_mode == "RISK_OFF" or execution_score <= -self.settings.scoring.min_execution_score_to_reduce):
                return normalize_engine_output(
                    {
                        "symbol": symbol,
                        "action": "PREPARE_REDUCE",
                        "reduce_pct": 1.0,
                        "confidence": min(0.94, 0.62 + abs(execution_score) * 0.2),
                        "ai_score": round(ai_score, 4),
                        "setup_score": round(setup_score, 4),
                        "execution_score": round(execution_score, 4),
                        "market_risk_penalty": round(market_risk_penalty, 4),
                        "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                        "phase_penalty": round(phase_penalty, 4),
                        "gate_penalty": round(gate_penalty, 4),
                        "risk_mode": risk_mode,
                        "holding_bias": "SHORT_TERM",
                        "reason": f"当前处于 {phase_name}，先保留次一可成交阶段的减仓/卖出意图。",
                        "warnings": warnings,
                        "final_score": round(execution_score, 4),
                        "feature_score": round(feature_score, 4),
                    },
                    symbol,
                )
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "HOLD_FOR_TOMORROW",
                    "confidence": min(0.86, 0.52 + abs(setup_score) * 0.18),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": f"当前处于 {phase_name}，持仓先进入观察与次日决策模式。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

        if (
            allow_prepare_actions
            and allow_new_buy
            and direction == "LONG"
            and bool(resolved_entry_structure.get("allow_buy", False))
            and setup_score >= watch_threshold
            and not (
                bool(resolved_capital_profile.get("is_small_account"))
                and float(resolved_capital_profile.get("lot_ratio") or 0.0)
                >= float(resolved_capital_profile.get("block_lot_pct") or 1.0)
            )
        ):
            base_pct = min(max_single_position_pct, 0.06 + max(execution_score, setup_score) * 0.12)
            if risk_mode == "DEFENSIVE":
                base_pct *= 0.65
            if resolved_capital_profile.get("is_small_account"):
                base_pct *= float(resolved_capital_profile.get("position_scale") or 1.0)
                lot_ratio = float(resolved_capital_profile.get("lot_ratio") or 0.0)
                if 0.0 < lot_ratio <= max_single_position_pct:
                    base_pct = max(base_pct, min(max_single_position_pct, lot_ratio * 1.02))
            base_pct *= max(0.35, min(1.0, float(resolved_entry_structure.get("position_scale") or 1.0)))
            return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "PREPARE_BUY",
                    "position_pct": round(max(0.03, min(base_pct, max_single_position_pct)), 4),
                    "confidence": min(0.92, 0.58 + setup_score * 0.2),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": str(resolved_entry_structure.get("entry_reason") or f"当前处于 {phase_name}，先记录次一可成交阶段的买入意图。"),
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                    "extra": {
                        "entry_type": str(resolved_entry_structure.get("entry_type") or "watch_point"),
                        "entry_quality_score": float(resolved_entry_structure.get("entry_quality_score") or 0.0),
                    },
                },
                symbol,
            )

        return normalize_engine_output(
                {
                    "symbol": symbol,
                    "action": "WATCH_NEXT_DAY",
                    "confidence": min(0.82, 0.5 + abs(setup_score) * 0.16),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": f"当前处于 {phase_name}，继续观察，等待下一可成交阶段。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                },
                symbol,
            )

    def _compute_ai_score(
        self,
        *,
        direction: str,
        feature_score: float,
        final_score: float,
        research_bias: float,
        market_regime: Mapping[str, object],
        portfolio_state: Mapping[str, object],
        position_state: Mapping[str, object],
        snapshot: Mapping[str, object],
        technical: Mapping[str, object],
        allow_new_buy: bool,
        adaptive_weights: Mapping[str, object],
        style_profile: Mapping[str, object],
        capital_profile: Mapping[str, float | bool],
        entry_structure: Mapping[str, object],
    ) -> float:
        score = 0.0
        regime = str(market_regime.get("regime") or "")
        risk_bias = str(market_regime.get("risk_bias") or "")
        ai_multiplier = float(adaptive_weights.get("ai_score_multiplier") or 1.0)
        style_name = str(style_profile.get("style") or "balanced")
        if direction == "LONG":
            score += 0.05
        elif direction == "SHORT":
            score -= 0.05
        score += research_bias * 0.6
        score += max(-0.08, min(0.08, feature_score * 0.22))
        score += self._technical_bonus(technical)

        pct_change = self._normalize_pct_change(snapshot.get("pct_change"))
        if direction == "LONG":
            if -0.02 <= pct_change <= 0.035:
                score += 0.04
            elif pct_change >= 0.06:
                score -= 0.05
            entry_type = str(entry_structure.get("entry_type") or "")
            if entry_type == "probe_entry":
                score += 0.03
            elif entry_type == "watch_point":
                score -= 0.02
            elif entry_type == "chase_block":
                score -= 0.08
        if float(snapshot.get("amount") or 0.0) >= self.settings.min_turnover * 2:
            score += 0.02

        if regime == "TRENDING_UP":
            score += 0.05 if direction == "LONG" else -0.03
        elif regime == "TRENDING_DOWN":
            score += -0.05 if direction == "LONG" else 0.05
        elif regime == "HIGH_VOLATILITY":
            score -= 0.04
        elif regime == "RISK_OFF":
            score -= 0.10

        if style_name == "trend_following":
            score += 0.03 if direction == "LONG" and regime == "TRENDING_UP" else 0.0
        elif style_name == "short_term":
            score += 0.02 if -0.015 <= pct_change <= 0.03 else -0.01
        elif style_name == "balanced":
            score += 0.0

        if risk_bias == "DEFENSIVE":
            score -= 0.03
        cash_pct = float(portfolio_state.get("cash_pct", 0.0) or 0.0)
        drawdown = float(portfolio_state.get("drawdown", 0.0) or 0.0)
        if not allow_new_buy and not bool(position_state.get("has_position")):
            score -= 0.04
        if cash_pct < 0.18 and direction == "LONG":
            score -= 0.04
        if drawdown >= self.settings.portfolio_feedback.drawdown_defensive_threshold:
            score -= 0.03

        if bool(position_state.get("has_position")):
            unrealized_pct = float(position_state.get("unrealized_pct", 0.0) or 0.0)
            if final_score < 0 and unrealized_pct < 0:
                score -= 0.05
            elif final_score > 0 and unrealized_pct > 0:
                score += 0.03
        if direction == "LONG" and bool(capital_profile.get("is_small_account")):
            lot_ratio = float(capital_profile.get("lot_ratio") or 0.0)
            affordable_lot_pct = float(capital_profile.get("affordable_lot_pct") or 0.0)
            block_lot_pct = float(capital_profile.get("block_lot_pct") or 0.0)
            if lot_ratio >= block_lot_pct:
                score -= 0.08
            elif lot_ratio > affordable_lot_pct:
                score -= min(0.06, (lot_ratio - affordable_lot_pct) * 0.6)
            elif 0.0 < lot_ratio <= affordable_lot_pct * 0.7:
                score += 0.02
        score *= ai_multiplier
        return max(-0.25, min(0.25, score))

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

    def _resolve_capital_profile(
        self,
        *,
        portfolio_state: Mapping[str, object],
        snapshot: Mapping[str, object],
    ) -> Dict[str, float | bool]:
        equity = max(0.0, float(portfolio_state.get("equity") or 0.0))
        latest_price = max(0.0, float(snapshot.get("latest_price") or snapshot.get("close") or 0.0))
        one_lot_cost = latest_price * 100.0
        lot_ratio = 0.0 if equity <= 0 or one_lot_cost <= 0 else one_lot_cost / equity
        is_small_account = equity > 0 and equity <= float(self.settings.capital_profile.small_account_equity_threshold)
        return {
            "equity": equity,
            "one_lot_cost": one_lot_cost,
            "lot_ratio": lot_ratio,
            "is_small_account": is_small_account,
            "buy_threshold_bonus": self.settings.capital_profile.small_account_buy_threshold_bonus if is_small_account else 0.0,
            "watch_threshold_bonus": self.settings.capital_profile.small_account_watch_threshold_bonus if is_small_account else 0.0,
            "affordable_lot_pct": float(self.settings.capital_profile.small_account_affordable_lot_pct),
            "block_lot_pct": float(self.settings.capital_profile.small_account_block_lot_pct),
            "position_scale": float(self.settings.capital_profile.small_account_position_scale if is_small_account else 1.0),
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

    def _build_position_exit_decision(
        self,
        *,
        symbol: str,
        risk_mode: str,
        can_sell_qty: int,
        unrealized_pct: float,
        execution_score: float,
        setup_score: float,
        feature_score: float,
        ai_score: float,
        market_risk_penalty: float,
        portfolio_risk_penalty: float,
        phase_penalty: float,
        gate_penalty: float,
        technical: Mapping[str, object],
        warnings: Sequence[str],
        exit_structure: Mapping[str, object] | None = None,
    ) -> Dict[str, object] | None:
        if can_sell_qty <= 0:
            return None
        resolved_exit_structure = dict(exit_structure or {})
        suggested_action = str(resolved_exit_structure.get("suggested_action") or "")
        exit_type = str(resolved_exit_structure.get("exit_type") or "")
        exit_reason = str(resolved_exit_structure.get("exit_reason") or "")
        exit_quality_score = float(resolved_exit_structure.get("exit_quality_score") or 0.0)
        reduce_pct = float(resolved_exit_structure.get("reduce_pct") or 0.3)
        min_reduce_score = float(self.settings.scoring.min_execution_score_to_reduce)
        trend_score = self._technical_bonus(technical)
        slope20 = float(technical.get("trend_slope_20d") or 0.0)
        ma20_bias = float(technical.get("ma20_bias") or 0.0)
        macd_hist = float(technical.get("macd_hist") or 0.0)
        structure_broken = slope20 <= -0.03 or ma20_bias <= -0.05 or macd_hist <= -0.03 or trend_score <= -0.08
        trend_supportive = trend_score >= 0.03 or (slope20 >= -0.01 and ma20_bias >= -0.025 and macd_hist >= -0.015)

        if risk_mode == "RISK_OFF":
            return {
                "symbol": symbol,
                "action": "SELL",
                "confidence": min(0.96, 0.68 + abs(execution_score) * 0.22),
                "ai_score": round(ai_score, 4),
                "setup_score": round(setup_score, 4),
                "execution_score": round(execution_score, 4),
                "market_risk_penalty": round(market_risk_penalty, 4),
                "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                "phase_penalty": round(phase_penalty, 4),
                "gate_penalty": round(gate_penalty, 4),
                "risk_mode": risk_mode,
                "holding_bias": "SHORT_TERM",
                "reason": exit_reason or "账户或市场已进入风险关闭模式，优先退出已有持仓。",
                "warnings": warnings,
                "final_score": round(execution_score, 4),
                "feature_score": round(feature_score, 4),
                "extra": {
                    "exit_type": exit_type or "sell_on_break",
                    "exit_quality_score": exit_quality_score,
                },
            }

        if exit_type == "take_profit_partial" and suggested_action == "REDUCE":
            return {
                "symbol": symbol,
                "action": "REDUCE",
                "reduce_pct": max(0.2, min(reduce_pct, 0.6)),
                "confidence": min(0.90, 0.60 + abs(execution_score) * 0.18),
                "ai_score": round(ai_score, 4),
                "setup_score": round(setup_score, 4),
                "execution_score": round(execution_score, 4),
                "market_risk_penalty": round(market_risk_penalty, 4),
                "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                "phase_penalty": round(phase_penalty, 4),
                "gate_penalty": round(gate_penalty, 4),
                "risk_mode": risk_mode,
                "holding_bias": "SHORT_TERM",
                "reason": exit_reason or "盈利单进入分批兑现阶段。",
                "warnings": warnings,
                "final_score": round(execution_score, 4),
                "feature_score": round(feature_score, 4),
                "extra": {
                    "exit_type": exit_type,
                    "exit_quality_score": exit_quality_score,
                },
            }

        if unrealized_pct <= -0.08 and (structure_broken or execution_score <= -min_reduce_score * 0.6 or risk_mode == "DEFENSIVE"):
            return {
                "symbol": symbol,
                "action": "SELL",
                "confidence": min(0.95, 0.67 + abs(execution_score) * 0.2),
                "ai_score": round(ai_score, 4),
                "setup_score": round(setup_score, 4),
                "execution_score": round(execution_score, 4),
                "market_risk_penalty": round(market_risk_penalty, 4),
                "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                "phase_penalty": round(phase_penalty, 4),
                "gate_penalty": round(gate_penalty, 4),
                "risk_mode": risk_mode,
                "holding_bias": "SHORT_TERM",
                "reason": exit_reason or "持仓回撤已明显扩大，且走势结构转弱，执行清仓止损。",
                "warnings": warnings,
                "final_score": round(execution_score, 4),
                "feature_score": round(feature_score, 4),
                "extra": {
                    "exit_type": exit_type or "sell_on_break",
                    "exit_quality_score": exit_quality_score,
                },
            }

        if unrealized_pct <= -0.05:
            if suggested_action == "SELL" or structure_broken or execution_score <= -min_reduce_score:
                return {
                    "symbol": symbol,
                    "action": "SELL" if suggested_action == "SELL" and not self.settings.exit_structure.prefer_reduce_before_sell else "REDUCE",
                    "reduce_pct": max(0.3, min(reduce_pct or (0.5 if unrealized_pct <= -0.07 else 0.3), 0.8)),
                    "confidence": min(0.9, 0.6 + abs(execution_score) * 0.18),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": exit_reason or "持仓已有明显回撤，但更像走势转弱，先减仓而不是直接清仓。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                    "extra": {
                        "exit_type": exit_type or "reduce_on_weakening",
                        "exit_quality_score": exit_quality_score,
                    },
                }
            if trend_supportive and execution_score > -0.18:
                return {
                    "symbol": symbol,
                    "action": "HOLD",
                    "confidence": min(0.84, 0.55 + max(setup_score, 0.0) * 0.22),
                    "ai_score": round(ai_score, 4),
                    "setup_score": round(setup_score, 4),
                    "execution_score": round(execution_score, 4),
                    "market_risk_penalty": round(market_risk_penalty, 4),
                    "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                    "phase_penalty": round(phase_penalty, 4),
                    "gate_penalty": round(gate_penalty, 4),
                    "risk_mode": risk_mode,
                    "holding_bias": "SHORT_TERM",
                    "reason": exit_reason or "虽已有约 5% 回撤，但趋势和结构尚未完全破坏，继续观察而不直接止损。",
                    "warnings": warnings,
                    "final_score": round(execution_score, 4),
                    "feature_score": round(feature_score, 4),
                    "extra": {
                        "exit_type": exit_type or "hold_on_structure",
                        "exit_quality_score": exit_quality_score,
                    },
                }
        if suggested_action == "REDUCE" and exit_quality_score >= 0.58:
            return {
                "symbol": symbol,
                "action": "REDUCE",
                "reduce_pct": max(0.2, min(reduce_pct, 0.7)),
                "confidence": min(0.88, 0.58 + abs(execution_score) * 0.16),
                "ai_score": round(ai_score, 4),
                "setup_score": round(setup_score, 4),
                "execution_score": round(execution_score, 4),
                "market_risk_penalty": round(market_risk_penalty, 4),
                "portfolio_risk_penalty": round(portfolio_risk_penalty, 4),
                "phase_penalty": round(phase_penalty, 4),
                "gate_penalty": round(gate_penalty, 4),
                "risk_mode": risk_mode,
                "holding_bias": "SHORT_TERM",
                "reason": exit_reason or "趋势减弱，先做减仓处理。",
                "warnings": warnings,
                "final_score": round(execution_score, 4),
                "feature_score": round(feature_score, 4),
                "extra": {
                    "exit_type": exit_type or "reduce_on_weakening",
                    "exit_quality_score": exit_quality_score,
                },
            }
        return None
