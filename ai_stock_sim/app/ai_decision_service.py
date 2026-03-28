from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Dict, Mapping, Optional

from .models import AIDecision, StrategySignal
from .settings import Settings, load_settings


class AIDecisionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def review_signal(
        self,
        symbol: str,
        candidate: StrategySignal,
        market_snapshot: Optional[Mapping[str, object]] = None,
        technical_summary: Optional[Mapping[str, object]] = None,
        portfolio_context: Optional[Mapping[str, object]] = None,
        risk_constraints: Optional[Mapping[str, object]] = None,
        mode: Optional[str] = None,
        trade_date: Optional[str] = None,
        use_subprocess: bool = False,
    ) -> AIDecision:
        context = self._build_context(
            symbol=symbol,
            candidate=candidate,
            market_snapshot=market_snapshot,
            technical_summary=technical_summary,
            portfolio_context=portfolio_context,
            risk_constraints=risk_constraints,
        )
        if not self.settings.enable_ai:
            return AIDecision(
                symbol=symbol,
                ai_action=candidate.action,
                confidence=0.5,
                risk_score=0.5,
                approved=True,
                reason="AI 审批已关闭，直接沿用策略信号。",
                source_mode="disabled",
                context_json=json.dumps(context, ensure_ascii=False),
                context_summary=self._summarize_context(context),
            )

        analysis_date = trade_date or date.today().isoformat()
        if use_subprocess:
            self._trigger_analysis_subprocess(symbol, mode=mode or self.settings.ai_mode, analysis_date=analysis_date)

        decision = self._load_decision_file(symbol, analysis_date)
        if decision is None:
            return AIDecision(
                symbol=symbol,
                ai_action=candidate.action,
                confidence=0.5,
                risk_score=0.5,
                approved=True,
                reason="未找到 AI 结果，已降级为无 AI 审批模式。",
                source_mode="fallback_no_ai",
                context_json=json.dumps(context, ensure_ascii=False),
                context_summary=self._summarize_context(context),
            )
        decision.context_json = json.dumps(context, ensure_ascii=False)
        decision.context_summary = self._summarize_context(context)
        return decision

    def _load_decision_file(self, symbol: str, analysis_date: str) -> Optional[AIDecision]:
        decision_path = self.settings.tradeforagents_results_dir / symbol / analysis_date / "decision.json"
        if not decision_path.exists():
            return None
        payload: Dict[str, object] = json.loads(decision_path.read_text(encoding="utf-8"))
        action = str(payload.get("action") or "hold").strip().upper()
        normalized_action = "HOLD"
        if action in {"BUY", "买入"}:
            normalized_action = "BUY"
        elif action in {"SELL", "卖出"}:
            normalized_action = "SELL"
        confidence = float(payload.get("confidence", 0.5) or 0.5)
        risk_score = float(payload.get("risk_score", 0.5) or 0.5)
        return AIDecision(
            symbol=symbol,
            ai_action=normalized_action,  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, confidence)),
            risk_score=max(0.0, min(1.0, risk_score)),
            approved=normalized_action != "HOLD" or confidence >= self.settings.ai.approval_confidence_floor,
            reason=str(payload.get("reasoning") or payload.get("reason") or "读取本地 decision.json 成功"),
            source_mode="decision_json",
        )

    def _build_context(
        self,
        symbol: str,
        candidate: StrategySignal,
        market_snapshot: Optional[Mapping[str, object]],
        technical_summary: Optional[Mapping[str, object]],
        portfolio_context: Optional[Mapping[str, object]],
        risk_constraints: Optional[Mapping[str, object]],
    ) -> Dict[str, object]:
        return {
            "symbol": symbol,
            "market_snapshot": dict(market_snapshot or {}),
            "technical_summary": dict(technical_summary or {}),
            "portfolio_context": dict(portfolio_context or {}),
            "risk_constraints": dict(risk_constraints or {}),
            "candidate_signal": candidate.model_dump(),
        }

    @staticmethod
    def _summarize_context(context: Mapping[str, object]) -> str:
        snapshot = context.get("market_snapshot") or {}
        portfolio = context.get("portfolio_context") or {}
        candidate = context.get("candidate_signal") or {}
        latest_price = snapshot.get("latest_price") if isinstance(snapshot, Mapping) else None
        cash = portfolio.get("cash") if isinstance(portfolio, Mapping) else None
        action = candidate.get("action") if isinstance(candidate, Mapping) else None
        return f"候选动作={action}，最新价={latest_price}，可用现金={cash}"

    def _trigger_analysis_subprocess(self, symbol: str, mode: str, analysis_date: str) -> None:
        script = self.settings.tradeforagents_script
        if not script.exists():
            return
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.settings.project_root.parent) + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.run(
            ["bash", str(script), symbol, analysis_date, f"--mode={mode}"],
            cwd=str(self.settings.project_root.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
