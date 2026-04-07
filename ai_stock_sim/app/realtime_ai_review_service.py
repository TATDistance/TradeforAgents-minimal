from __future__ import annotations

import json
import os
import queue
import threading
import time
from datetime import datetime
from typing import Dict, List, Mapping, Sequence, Tuple

from openai import OpenAI

from .models import PortfolioManagerAction
from .settings import Settings, load_settings


class RealtimeAIReviewError(RuntimeError):
    def __init__(self, code: str, user_message: str, detail: str = "") -> None:
        super().__init__(detail or user_message)
        self.code = code
        self.user_message = user_message
        self.detail = detail


class RealtimeAIReviewService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._last_review_at: Dict[str, float] = {}
        self._pending_reviews: Dict[str, Dict[str, object]] = {}
        self._review_results: Dict[str, Dict[str, object]] = {}
        self._review_queue: queue.Queue[Dict[str, object]] = queue.Queue()
        self._lock = threading.Lock()
        self._worker_thread: threading.Thread | None = None

    @staticmethod
    def _classify_review_role(candidate_type: str, proposed_action: str, final_action: str) -> str:
        draft = str(proposed_action or "HOLD").upper()
        final = str(final_action or draft).upper()
        if draft == final:
            return "NO_CHANGE"
        if draft == "BUY" and final == "HOLD":
            return "VETO"
        if draft in {"SELL", "REDUCE"} and final in {"HOLD", "REDUCE"}:
            return "SOFTEN"
        if candidate_type == "holding" and final in {"REDUCE", "SELL"}:
            return "TRIGGER"
        if draft == "HOLD" and final in {"REDUCE", "SELL"}:
            return "TRIGGER"
        return "ADJUST"

    def request_reviews(
        self,
        actions: Sequence[PortfolioManagerAction],
        *,
        portfolio_feedback: Mapping[str, object],
        market_regime: Mapping[str, object],
        phase_state: Mapping[str, object],
        snapshot_rows: Mapping[str, Mapping[str, object]],
        decision_contexts: Mapping[str, Mapping[str, object]],
        trade_date: str,
        account_id: str,
    ) -> Tuple[List[PortfolioManagerAction], List[Dict[str, object]]]:
        if not self._enabled():
            return list(actions), []

        self._ensure_worker()
        action_map = {str(action.symbol): action for action in actions}
        updated = list(actions)
        reviews: List[Dict[str, object]] = []
        candidates = self._select_candidates(
            actions=actions,
            portfolio_feedback=portfolio_feedback,
        )

        for candidate in candidates:
            payload = self._build_review_payload(
                candidate=candidate,
                portfolio_feedback=portfolio_feedback,
                market_regime=market_regime,
                phase_state=phase_state,
                snapshot_rows=snapshot_rows,
                decision_contexts=decision_contexts,
                trade_date=trade_date,
            )
            review_key = self._review_key(candidate, account_id=account_id)
            record = self._get_review_result(review_key)
            review_status = str(record.get("status") or "PENDING").upper()
            applied = False
            reviewed_action = None
            fallback_reason = ""
            reason = ""
            confidence = 0.0
            latency_ms = int(record.get("latency_ms") or 0)
            error_code = str(record.get("error_code") or "")

            if review_status == "DONE":
                review_payload = dict(record.get("review") or {})
                reviewed_action = str(
                    review_payload.get("final_action")
                    or candidate.get("proposed_action")
                    or "HOLD"
                ).upper()
                reason = str(review_payload.get("reason") or "")
                confidence = float(review_payload.get("confidence") or 0.0)
                if candidate["candidate_type"] == "action":
                    original = action_map.get(str(candidate["symbol"]))
                    if original is not None:
                        revised = self._apply_review_to_action(original, review_payload, candidate)
                        if revised is not None:
                            updated = [
                                revised if item.symbol == original.symbol and item.action == original.action else item
                                for item in updated
                            ]
                            action_map[str(revised.symbol)] = revised
                            applied = revised.model_dump() != original.model_dump()
                else:
                    inserted = self._build_action_from_holding_review(candidate, review_payload)
                    if inserted is not None and inserted.symbol not in action_map:
                        updated.append(inserted)
                        action_map[str(inserted.symbol)] = inserted
                        applied = True
            else:
                if review_status in {"FAILED", "TIMEOUT"}:
                    review_status = "DEGRADED"
                    fallback_reason = str(record.get("error") or "实时 AI 终审失败，已回退到规则动作")
                reason = str(record.get("error") or "")
                if self._should_enqueue(review_key):
                    event_id = self._enqueue_candidate_review(
                        review_key=review_key,
                        candidate=candidate,
                        payload=payload,
                    )
                    record = self._get_review_result(review_key)
                    if event_id and not record.get("event_id"):
                        record["event_id"] = event_id
                    review_status = "PENDING"
                    reason = ""
                    fallback_reason = ""
                reviewed_action = str(record.get("reviewed_action") or reviewed_action or candidate["proposed_action"]).upper() if record.get("reviewed_action") else reviewed_action

            effective_final_action = str(reviewed_action or candidate["proposed_action"]).upper()
            submitted_at = str(
                record.get("submitted_at")
                or payload.get("submitted_at")
                or datetime.now().isoformat(timespec="seconds")
            )
            reviews.append(
                {
                    "event_id": str(record.get("event_id") or ""),
                    "review_key": review_key,
                    "submitted_at": submitted_at,
                    "trade_date": trade_date,
                    "symbol": candidate["symbol"],
                    "candidate_type": candidate["candidate_type"],
                    "candidate_label": "持仓复核" if candidate["candidate_type"] == "holding" else "交易前终审",
                    "draft_action": candidate["proposed_action"],
                    "proposed_action": candidate["proposed_action"],
                    "review_status": review_status,
                    "reviewed_action": reviewed_action,
                    "final_action": effective_final_action,
                    "review_role": self._classify_review_role(
                        str(candidate["candidate_type"]),
                        str(candidate["proposed_action"]),
                        effective_final_action,
                    ),
                    "confidence": confidence,
                    "reason": reason,
                    "fallback_reason": fallback_reason,
                    "error_code": error_code,
                    "latency_ms": latency_ms,
                    "applied": applied,
                    "allowed_actions": candidate["allowed_actions"],
                    "base_price": float(((payload.get("snapshot") or {}).get("latest_price") or 0.0)),
                    "base_ts": submitted_at,
                    "base_market_value": float(((payload.get("position") or {}).get("market_value") or 0.0)),
                    "position_qty": int(((payload.get("position") or {}).get("qty") or 0)),
                    "can_sell_qty": int(((payload.get("position") or {}).get("can_sell_qty") or 0)),
                    "unrealized_pct": float(((payload.get("position") or {}).get("unrealized_pct") or 0.0)),
                    "market_regime_name": str(((payload.get("market_regime") or {}).get("regime") or "")),
                    "risk_mode": str(((payload.get("portfolio") or {}).get("risk_mode") or "")),
                    "tracking_payload": payload,
                }
            )

        updated.sort(key=lambda item: float(item.priority or 0.0), reverse=True)
        return updated, reviews

    def review_actions(
        self,
        actions: Sequence[PortfolioManagerAction],
        *,
        portfolio_feedback: Mapping[str, object],
        market_regime: Mapping[str, object],
        phase_state: Mapping[str, object],
        snapshot_rows: Mapping[str, Mapping[str, object]],
        decision_contexts: Mapping[str, Mapping[str, object]],
        trade_date: str,
        account_id: str,
    ) -> Tuple[List[PortfolioManagerAction], List[Dict[str, object]]]:
        if not self._enabled():
            return list(actions), []
        client = self._build_client()
        if client is None:
            return list(actions), []

        action_map = {str(action.symbol): action for action in actions}
        candidates = self._select_candidates(
            actions=actions,
            portfolio_feedback=portfolio_feedback,
        )
        updated = list(actions)
        reviews: List[Dict[str, object]] = []
        for candidate in candidates:
            review_key = self._review_key(candidate, account_id=account_id)
            if self._cooldown_active(review_key):
                continue
            payload = self._build_review_payload(
                candidate=candidate,
                portfolio_feedback=portfolio_feedback,
                market_regime=market_regime,
                phase_state=phase_state,
                snapshot_rows=snapshot_rows,
                decision_contexts=decision_contexts,
                trade_date=trade_date,
            )
            review = self._call_review_model(client, payload)
            if not review:
                continue
            self._last_review_at[review_key] = time.time()
            submitted_at = datetime.now().isoformat(timespec="seconds")
            applied = False
            if candidate["candidate_type"] == "action":
                original = action_map.get(candidate["symbol"])
                if original is not None:
                    revised = self._apply_review_to_action(original, review, candidate)
                    if revised is not None:
                        updated = [revised if item.symbol == original.symbol and item.action == original.action else item for item in updated]
                        action_map[str(revised.symbol)] = revised
                        applied = revised.model_dump() != original.model_dump()
            else:
                inserted = self._build_action_from_holding_review(candidate, review)
                if inserted is not None:
                    updated.append(inserted)
                    action_map[str(inserted.symbol)] = inserted
                    applied = True
            reviews.append(
                {
                    "event_id": f"{review_key}:{int(time.time() * 1000)}",
                    "review_key": review_key,
                    "submitted_at": submitted_at,
                    "trade_date": trade_date,
                    "symbol": candidate["symbol"],
                    "candidate_type": candidate["candidate_type"],
                    "candidate_label": "持仓复核" if candidate["candidate_type"] == "holding" else "交易前终审",
                    "draft_action": candidate["proposed_action"],
                    "proposed_action": candidate["proposed_action"],
                    "review_status": "DONE",
                    "reviewed_action": str(review.get("final_action") or candidate["proposed_action"]),
                    "final_action": str(review.get("final_action") or candidate["proposed_action"]),
                    "review_role": self._classify_review_role(
                        str(candidate["candidate_type"]),
                        str(candidate["proposed_action"]),
                        str(review.get("final_action") or candidate["proposed_action"]),
                    ),
                    "confidence": float(review.get("confidence") or 0.0),
                    "reason": str(review.get("reason") or ""),
                    "applied": applied,
                    "allowed_actions": candidate["allowed_actions"],
                    "error_code": "",
                    "latency_ms": 0,
                    "fallback_reason": "",
                    "base_price": float(((payload.get("snapshot") or {}).get("latest_price") or 0.0)),
                    "base_ts": submitted_at,
                    "base_market_value": float(((payload.get("position") or {}).get("market_value") or 0.0)),
                    "position_qty": int(((payload.get("position") or {}).get("qty") or 0)),
                    "can_sell_qty": int(((payload.get("position") or {}).get("can_sell_qty") or 0)),
                    "unrealized_pct": float(((payload.get("position") or {}).get("unrealized_pct") or 0.0)),
                    "market_regime_name": str(((payload.get("market_regime") or {}).get("regime") or "")),
                    "risk_mode": str(((payload.get("portfolio") or {}).get("risk_mode") or "")),
                    "tracking_payload": payload,
                }
            )
        updated.sort(key=lambda item: float(item.priority or 0.0), reverse=True)
        return updated, reviews

    def _enabled(self) -> bool:
        if not self.settings.enable_ai:
            return False
        if not (
            self.settings.ai.realtime_action_review_enabled
            or self.settings.ai.realtime_position_review_enabled
        ):
            return False
        return bool(self._resolve_api_key())

    def _ensure_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="realtime-ai-review-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while True:
            task = self._review_queue.get()
            review_key = str(task.get("review_key") or "")
            started_at = time.time()
            try:
                client = self._build_client()
                if client is None:
                    self._store_review_result(
                        review_key,
                        event_id=str(task.get("event_id") or ""),
                        submitted_at=str(task.get("submitted_at") or ""),
                        status="FAILED",
                        review=None,
                        error_code="API_ERROR",
                        error="未检测到可用的实时 AI API Key",
                        latency_ms=int((time.time() - started_at) * 1000),
                    )
                    continue
                review = self._call_review_model(client, task.get("payload") or {})
                if review:
                    self._store_review_result(
                        review_key,
                        event_id=str(task.get("event_id") or ""),
                        submitted_at=str(task.get("submitted_at") or ""),
                        status="DONE",
                        review=review,
                        error_code="",
                        error="",
                        latency_ms=int((time.time() - started_at) * 1000),
                    )
            except RealtimeAIReviewError as exc:
                self._store_review_result(
                    review_key,
                    event_id=str(task.get("event_id") or ""),
                    submitted_at=str(task.get("submitted_at") or ""),
                    status="TIMEOUT" if exc.code == "TIMEOUT" else "FAILED",
                    review=None,
                    error_code=exc.code,
                    error=exc.user_message,
                    latency_ms=int((time.time() - started_at) * 1000),
                )
            except Exception as exc:
                self._store_review_result(
                    review_key,
                    event_id=str(task.get("event_id") or ""),
                    submitted_at=str(task.get("submitted_at") or ""),
                    status="FAILED",
                    review=None,
                    error_code="API_ERROR",
                    error=self._user_message_for_error_code("API_ERROR"),
                    latency_ms=int((time.time() - started_at) * 1000),
                )
            finally:
                self._review_queue.task_done()

    def _store_review_result(
        self,
        review_key: str,
        *,
        event_id: str,
        submitted_at: str,
        status: str,
        review: Mapping[str, object] | None,
        error_code: str,
        error: str,
        latency_ms: int,
    ) -> None:
        with self._lock:
            pending_meta = dict(self._pending_reviews.pop(review_key, {}) or {})
            self._review_results[review_key] = {
                "event_id": event_id or str(pending_meta.get("event_id") or ""),
                "submitted_at": submitted_at or str(pending_meta.get("submitted_at") or ""),
                "status": status,
                "review": dict(review or {}),
                "error_code": error_code,
                "error": error,
                "latency_ms": latency_ms,
                "completed_at": time.time(),
            }
            self._last_review_at[review_key] = time.time()

    def _get_review_result(self, review_key: str) -> Dict[str, object]:
        with self._lock:
            if review_key in self._pending_reviews:
                return {"status": "PENDING", **dict(self._pending_reviews[review_key])}
            return dict(self._review_results.get(review_key) or {})

    def _should_enqueue(self, review_key: str) -> bool:
        with self._lock:
            if review_key in self._pending_reviews:
                return False
        return not self._cooldown_active(review_key)

    def _enqueue_candidate_review(
        self,
        *,
        review_key: str,
        candidate: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> str:
        event_id = f"{review_key}:{int(time.time() * 1000)}"
        submitted_at = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            if review_key in self._pending_reviews:
                return str(self._pending_reviews[review_key].get("event_id") or "")
            self._pending_reviews[review_key] = {
                "event_id": event_id,
                "submitted_at": submitted_at,
            }
        self._review_queue.put(
            {
                "review_key": review_key,
                "event_id": event_id,
                "candidate": dict(candidate),
                "payload": dict(payload),
                "submitted_at": submitted_at,
            }
        )
        return event_id

    def _build_client(self) -> OpenAI | None:
        api_key = self._resolve_api_key()
        if not api_key:
            return None
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip() or "https://api.deepseek.com"
        return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def _resolve_api_key(self) -> str:
        env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if env_key:
            return env_key
        env_path = os.getenv("TRADEFORAGENTS_ENV_FILE", "").strip()
        if env_path:
            candidate_paths = [env_path]
        else:
            candidate_paths = [
                str(self.settings.project_root / ".env"),
                str(self.settings.project_root.parent / ".env"),
            ]
        for path_text in candidate_paths:
            try:
                with open(path_text, "r", encoding="utf-8", errors="ignore") as handle:
                    for raw in handle:
                        if raw.startswith("DEEPSEEK_API_KEY="):
                            value = raw.split("=", 1)[1].strip()
                            if value:
                                return value
            except Exception:
                continue
        return ""

    def _cooldown_active(self, key: str) -> bool:
        last = float(self._last_review_at.get(key) or 0.0)
        cooldown = int(self.settings.ai.realtime_review_cooldown_seconds or 0)
        return cooldown > 0 and (time.time() - last) < cooldown

    def _review_key(self, candidate: Mapping[str, object], *, account_id: str) -> str:
        return ":".join(
            [
                account_id,
                str(candidate.get("candidate_type") or ""),
                str(candidate.get("symbol") or ""),
                str(candidate.get("proposed_action") or ""),
                str(int(candidate.get("position_qty") or 0)),
            ]
        )

    def _select_candidates(
        self,
        *,
        actions: Sequence[PortfolioManagerAction],
        portfolio_feedback: Mapping[str, object],
    ) -> List[Dict[str, object]]:
        max_items = max(1, int(self.settings.ai.realtime_review_max_items or 1))
        holdings: List[Dict[str, object]] = []
        actionable: List[Dict[str, object]] = []
        raw_actions = [
            action
            for action in actions
            if action.symbol != "*" and action.action in {"BUY", "SELL", "REDUCE"}
        ]
        raw_actions.sort(
            key=lambda action: (
                0 if action.action in {"SELL", "REDUCE"} else 1,
                -float(action.priority or 0.0),
                str(action.symbol),
            )
        )
        for action in raw_actions:
            actionable.append(
                {
                    "candidate_type": "action",
                    "symbol": action.symbol,
                    "proposed_action": action.action,
                    "allowed_actions": self._allowed_actions(action.action, has_position=action.action != "BUY"),
                    "priority": float(action.priority or 0.0),
                    "position_qty": 0,
                }
            )
        if self.settings.ai.realtime_position_review_enabled:
            existing_symbols = {str(action.symbol) for action in raw_actions}
            account_risk_mode = str(portfolio_feedback.get("risk_mode") or "NORMAL").upper()
            positions = [
                item
                for item in (portfolio_feedback.get("positions_detail") or [])
                if isinstance(item, Mapping) and str(item.get("symbol") or "") not in existing_symbols
            ]
            positions.sort(
                key=lambda item: (
                    1 if float(item.get("market_value") or 0.0) >= float(portfolio_feedback.get("equity") or 0.0) * 0.12 else 0,
                    1 if abs(float(item.get("unrealized_pct") or 0.0)) >= 0.04 else 0,
                    1 if account_risk_mode in {"DEFENSIVE", "RISK_OFF"} else 0,
                    float(item.get("market_value") or 0.0),
                    abs(float(item.get("unrealized_pct") or 0.0)),
                    int(item.get("can_sell_qty") or 0),
                ),
                reverse=True,
            )
            for item in positions:
                market_value = float(item.get("market_value") or 0.0)
                unrealized_pct = abs(float(item.get("unrealized_pct") or 0.0))
                if market_value <= 0:
                    continue
                if market_value < float(portfolio_feedback.get("equity") or 0.0) * 0.06 and unrealized_pct < 0.025:
                    continue
                holdings.append(
                    {
                        "candidate_type": "holding",
                        "symbol": str(item.get("symbol") or ""),
                        "proposed_action": "HOLD",
                        "allowed_actions": ["HOLD", "REDUCE", "SELL"],
                        "priority": market_value,
                        "position_qty": int(item.get("qty") or 0),
                    }
                )
        prioritized = holdings + actionable
        return prioritized[:max_items]

    @staticmethod
    def _allowed_actions(proposed_action: str, *, has_position: bool) -> List[str]:
        if proposed_action == "BUY" and not has_position:
            return ["BUY", "HOLD"]
        return ["HOLD", "REDUCE", "SELL"]

    def _build_review_payload(
        self,
        *,
        candidate: Mapping[str, object],
        portfolio_feedback: Mapping[str, object],
        market_regime: Mapping[str, object],
        phase_state: Mapping[str, object],
        snapshot_rows: Mapping[str, Mapping[str, object]],
        decision_contexts: Mapping[str, Mapping[str, object]],
        trade_date: str,
    ) -> Dict[str, object]:
        symbol = str(candidate.get("symbol") or "")
        position = next(
            (
                item
                for item in (portfolio_feedback.get("positions_detail") or [])
                if isinstance(item, Mapping) and str(item.get("symbol") or "") == symbol
            ),
            {},
        )
        context = dict(decision_contexts.get(symbol) or {})
        technical = dict(context.get("technical_features") or {})
        snapshot = dict(snapshot_rows.get(symbol) or context.get("snapshot") or {})
        return {
            "symbol": symbol,
            "trade_date": trade_date,
            "candidate_type": str(candidate.get("candidate_type") or "action"),
            "proposed_action": str(candidate.get("proposed_action") or "HOLD"),
            "allowed_actions": list(candidate.get("allowed_actions") or ["HOLD"]),
            "market_regime": dict(market_regime or {}),
            "market_phase": dict(phase_state or {}),
            "portfolio": {
                "equity": float(portfolio_feedback.get("equity") or 0.0),
                "cash": float(portfolio_feedback.get("cash") or 0.0),
                "cash_pct": float(portfolio_feedback.get("cash_pct") or 0.0),
                "drawdown": float(portfolio_feedback.get("drawdown") or 0.0),
                "risk_mode": str(portfolio_feedback.get("risk_mode") or "NORMAL"),
            },
            "position": {
                "qty": int(position.get("qty") or 0),
                "avg_cost": float(position.get("avg_cost") or 0.0),
                "last_price": float(position.get("last_price") or snapshot.get("latest_price") or 0.0),
                "market_value": float(position.get("market_value") or 0.0),
                "unrealized_pct": float(position.get("unrealized_pct") or 0.0),
                "hold_days": int(position.get("hold_days") or 0),
                "can_sell_qty": int(position.get("can_sell_qty") or 0),
            },
            "snapshot": {
                "latest_price": float(snapshot.get("latest_price") or 0.0),
                "pct_change": float(snapshot.get("pct_change") or 0.0),
                "amount": float(snapshot.get("amount") or 0.0),
                "turnover_rate": float(snapshot.get("turnover_rate") or 0.0),
                "name": str(snapshot.get("name") or symbol),
            },
            "technical": {
                "ret_5d": float(technical.get("ret_5d") or 0.0),
                "ret_20d": float(technical.get("ret_20d") or 0.0),
                "rsi_14": float(technical.get("rsi_14") or 0.0),
                "macd_hist": float(technical.get("macd_hist") or 0.0),
                "ma20_bias": float(technical.get("ma20_bias") or 0.0),
                "ma60_bias": float(technical.get("ma60_bias") or 0.0),
                "trend_slope_20d": float(technical.get("trend_slope_20d") or 0.0),
            },
            "existing_reason": self._extract_reason(symbol, trade_date),
        }

    def _call_review_model(self, client: OpenAI, payload: Mapping[str, object]) -> Dict[str, object] | None:
        model = os.getenv("TA_REALTIME_AI_MODEL", "").strip() or self.settings.ai.realtime_review_model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        timeout = int(self.settings.ai.realtime_review_timeout_seconds or self.settings.ai.request_timeout_seconds or 20)
        system_prompt = (
            "你是A股实时交易终审员。必须结合走势结构、市场状态、账户风险和持仓全局判断。"
            "不要因为浮亏约5%就机械清仓；只有结构明显走坏或风险模式恶化才卖。"
            "输出严格 JSON，不要输出 markdown。"
        )
        user_prompt = {
            "task": "review_realtime_trade_action",
            "instruction": {
                "return_json_schema": {
                    "final_action": "BUY|SELL|REDUCE|HOLD",
                    "confidence": "0~1",
                    "position_pct": "仅 BUY 有效，可选",
                    "reduce_pct": "仅 REDUCE 有效，可选",
                    "reason": "一句到三句中文理由",
                    "risk_tags": ["trend_break", "risk_off", "weak_execution", "cash_pressure", "trend_supportive"],
                },
                "rules": [
                    "final_action 必须在 allowed_actions 内",
                    "BUY 若风险大可改成 HOLD",
                    "SELL 若没有明显走坏可以改成 REDUCE 或 HOLD",
                    "holding 候选若你认为需要处理，可以从 HOLD 改成 REDUCE 或 SELL",
                ],
            },
            "payload": payload,
        }
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.1,
                timeout=timeout,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
            )
        except Exception as exc:
            code = self._error_code_for_exception(exc)
            raise RealtimeAIReviewError(
                code=code,
                user_message=self._user_message_for_error_code(code),
                detail=str(exc),
            ) from exc
        content = ""
        try:
            content = str(resp.choices[0].message.content or "").strip()
        except Exception:
            content = ""
        if not content:
            raise RealtimeAIReviewError(
                code="EMPTY_RESPONSE",
                user_message=self._user_message_for_error_code("EMPTY_RESPONSE"),
            )
        parsed = self._parse_json_content(content)
        if not parsed:
            raise RealtimeAIReviewError(
                code="INVALID_JSON",
                user_message=self._user_message_for_error_code("INVALID_JSON"),
                detail=content[:500],
            )
        return parsed

    @staticmethod
    def _error_code_for_exception(exc: Exception) -> str:
        text = f"{exc.__class__.__name__} {exc}".lower()
        if "timeout" in text or "timed out" in text:
            return "TIMEOUT"
        return "API_ERROR"

    @staticmethod
    def _user_message_for_error_code(code: str) -> str:
        messages = {
            "API_ERROR": "实时 AI 接口调用失败，已降级为规则动作",
            "EMPTY_RESPONSE": "实时 AI 返回空结果，已降级为规则动作",
            "INVALID_JSON": "实时 AI 返回格式异常，已降级为规则动作",
            "TIMEOUT": "实时 AI 响应超时，已降级为规则动作",
        }
        return messages.get(code, "实时 AI 终审失败，已降级为规则动作")

    @staticmethod
    def _parse_json_content(content: str) -> Dict[str, object] | None:
        text = content.strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else None
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
                return payload if isinstance(payload, dict) else None
            except Exception:
                return None
        return None

    def _apply_review_to_action(
        self,
        action: PortfolioManagerAction,
        review: Mapping[str, object],
        candidate: Mapping[str, object],
    ) -> PortfolioManagerAction | None:
        final_action = str(review.get("final_action") or action.action).upper()
        if final_action not in set(candidate.get("allowed_actions") or []):
            final_action = action.action
        updates = {
            "action": final_action,
            "reason": str(review.get("reason") or action.reason),
            "source": list(dict.fromkeys([*action.source, "realtime_ai_review"])),
        }
        if final_action == "BUY":
            reviewed_pct = float(review.get("position_pct") or action.position_pct or 0.0)
            updates["position_pct"] = max(0.0, min(reviewed_pct, float(action.position_pct or reviewed_pct)))
        elif final_action == "REDUCE":
            reviewed_reduce = float(review.get("reduce_pct") or action.reduce_pct or 0.3)
            updates["reduce_pct"] = max(0.1, min(reviewed_reduce, 1.0))
        else:
            updates["position_pct"] = 0.0
            updates["reduce_pct"] = 0.0
        metadata = dict(action.metadata or {})
        metadata["realtime_ai_review"] = {
            "final_action": final_action,
            "confidence": float(review.get("confidence") or 0.0),
            "risk_tags": list(review.get("risk_tags") or []),
            "draft_action": str(action.action or "HOLD"),
        }
        metadata["review_status"] = "DONE"
        updates["metadata"] = metadata
        return action.model_copy(update=updates)

    def _build_action_from_holding_review(
        self,
        candidate: Mapping[str, object],
        review: Mapping[str, object],
    ) -> PortfolioManagerAction | None:
        final_action = str(review.get("final_action") or "HOLD").upper()
        if final_action not in {"REDUCE", "SELL"}:
            return None
        return PortfolioManagerAction(
            symbol=str(candidate.get("symbol") or ""),
            action=final_action,  # type: ignore[arg-type]
            reduce_pct=max(0.1, min(float(review.get("reduce_pct") or 0.3), 1.0)) if final_action == "REDUCE" else 0.0,
            reason=str(review.get("reason") or "实时 AI 复核建议调整持仓"),
            priority=round(0.72 + min(float(review.get("confidence") or 0.0), 1.0) * 0.18, 4),
            source=["realtime_ai_review"],
            mode_name="realtime_ai_review_mode",
            metadata={
                "review_status": "DONE",
                "realtime_ai_review": {
                    "final_action": final_action,
                    "confidence": float(review.get("confidence") or 0.0),
                    "risk_tags": list(review.get("risk_tags") or []),
                    "draft_action": "HOLD",
                }
            },
        )

    def _extract_reason(self, symbol: str, trade_date: str) -> Dict[str, object]:
        path = self.settings.tradeforagents_results_dir / symbol / trade_date / "decision.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {
            "action": str(payload.get("action") or ""),
            "confidence": float(payload.get("confidence") or 0.0),
            "reason": str(payload.get("reason") or payload.get("reasoning") or ""),
        }
