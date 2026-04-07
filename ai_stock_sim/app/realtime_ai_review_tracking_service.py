from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from .db import fetch_rows_by_sql
from .settings import Settings, load_settings


class RealtimeAIReviewTrackingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    @staticmethod
    def _safe_json(payload: object) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def classify_review_role(
        candidate_type: str,
        proposed_action: str,
        final_action: str,
    ) -> str:
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

    def persist_reviews(self, conn, reviews: Iterable[Mapping[str, object]]) -> int:
        written = 0
        for row in reviews:
            event_id = str(row.get("event_id") or "").strip()
            review_key = str(row.get("review_key") or "").strip()
            symbol = str(row.get("symbol") or "").strip()
            if not event_id or not review_key or not symbol:
                continue
            conn.execute(
                """
                INSERT INTO realtime_ai_review_events (
                    ts, review_key, event_id, symbol, trade_date, candidate_type, review_role,
                    proposed_action, reviewed_action, final_action, allowed_actions_json,
                    review_status, applied, confidence, reason, fallback_reason, error_code,
                    latency_ms, base_price, base_ts, base_market_value, position_qty,
                    can_sell_qty, unrealized_pct, market_regime, risk_mode, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    ts = excluded.ts,
                    review_role = excluded.review_role,
                    reviewed_action = excluded.reviewed_action,
                    final_action = excluded.final_action,
                    review_status = excluded.review_status,
                    applied = excluded.applied,
                    confidence = excluded.confidence,
                    reason = excluded.reason,
                    fallback_reason = excluded.fallback_reason,
                    error_code = excluded.error_code,
                    latency_ms = excluded.latency_ms,
                    market_regime = excluded.market_regime,
                    risk_mode = excluded.risk_mode,
                    payload_json = excluded.payload_json
                """,
                (
                    str(row.get("submitted_at") or row.get("ts") or datetime.now().isoformat(timespec="seconds")),
                    review_key,
                    event_id,
                    symbol,
                    str(row.get("trade_date") or ""),
                    str(row.get("candidate_type") or "action"),
                    str(row.get("review_role") or "NO_CHANGE"),
                    str(row.get("draft_action") or row.get("proposed_action") or "HOLD"),
                    str(row.get("reviewed_action") or "") or None,
                    str(row.get("final_action") or row.get("reviewed_action") or row.get("draft_action") or "HOLD"),
                    self._safe_json(list(row.get("allowed_actions") or [])),
                    str(row.get("review_status") or "PENDING"),
                    1 if bool(row.get("applied")) else 0,
                    float(row.get("confidence") or 0.0),
                    str(row.get("reason") or ""),
                    str(row.get("fallback_reason") or ""),
                    str(row.get("error_code") or ""),
                    int(row.get("latency_ms") or 0),
                    float(row.get("base_price") or 0.0),
                    str(row.get("base_ts") or row.get("submitted_at") or datetime.now().isoformat(timespec="seconds")),
                    float(row.get("base_market_value") or 0.0),
                    int(row.get("position_qty") or 0),
                    int(row.get("can_sell_qty") or 0),
                    float(row.get("unrealized_pct") or 0.0),
                    str(row.get("market_regime_name") or ""),
                    str(row.get("risk_mode") or ""),
                    self._safe_json(row.get("tracking_payload") or {}),
                ),
            )
            written += 1
        return written

    def update_outcomes(self, conn, lookback_days: int = 5) -> int:
        rows = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT *
                FROM realtime_ai_review_events
                WHERE date(ts) >= date('now', ?)
                ORDER BY ts DESC, id DESC
                """,
                (f"-{int(max(lookback_days, 1))} day",),
            )
        ]
        price_cache: Dict[str, Dict[str, List[Dict[str, object]]]] = {}
        updated = 0
        for row in rows:
            symbol = str(row.get("symbol") or "").strip()
            base_price = float(row.get("base_price") or 0.0)
            base_ts = str(row.get("base_ts") or "").strip()
            if not symbol or base_price <= 0 or not base_ts:
                continue
            try:
                base_dt = datetime.fromisoformat(base_ts)
            except Exception:
                continue
            symbol_points = price_cache.setdefault(symbol, self._load_symbol_points(symbol))
            close_price = self._same_day_close_price(symbol_points, str(row.get("trade_date") or ""), base_dt)
            next_close_price = self._next_day_close_price(symbol_points, str(row.get("trade_date") or ""))
            one_hour_price = self._price_at_or_after(symbol_points, base_dt.timestamp() + 3600)
            outcome_1h_return = self._calc_return(base_price, one_hour_price)
            outcome_close_return = self._calc_return(base_price, close_price)
            outcome_next_close_return = self._calc_return(base_price, next_close_price)
            role = str(row.get("review_role") or "NO_CHANGE")
            proposed_action = str(row.get("proposed_action") or "HOLD")
            final_action = str(row.get("final_action") or proposed_action)
            benefit_1h = self._benefit(role, proposed_action, final_action, outcome_1h_return)
            benefit_close = self._benefit(role, proposed_action, final_action, outcome_close_return)
            benefit_next_close = self._benefit(role, proposed_action, final_action, outcome_next_close_return)
            conn.execute(
                """
                UPDATE realtime_ai_review_events
                SET outcome_1h_return = ?,
                    outcome_close_return = ?,
                    outcome_next_close_return = ?,
                    benefit_1h = ?,
                    benefit_close = ?,
                    benefit_next_close = ?,
                    outcome_1h_label = ?,
                    outcome_close_label = ?,
                    outcome_next_close_label = ?,
                    evaluated_at = ?
                WHERE event_id = ?
                """,
                (
                    outcome_1h_return,
                    outcome_close_return,
                    outcome_next_close_return,
                    benefit_1h,
                    benefit_close,
                    benefit_next_close,
                    self._outcome_label(role, benefit_1h),
                    self._outcome_label(role, benefit_close),
                    self._outcome_label(role, benefit_next_close),
                    datetime.now().isoformat(timespec="seconds"),
                    str(row.get("event_id") or ""),
                ),
            )
            updated += 1
        return updated

    def build_summary(self, conn, limit: int = 60) -> Dict[str, object]:
        rows = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT *
                FROM realtime_ai_review_events
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]
        role_counts = {"VETO": 0, "SOFTEN": 0, "TRIGGER": 0}
        positive_close = 0
        for row in rows:
            role = str(row.get("review_role") or "")
            if role in role_counts and bool(row.get("applied")):
                role_counts[role] += 1
            if float(row.get("benefit_close") or 0.0) > 0:
                positive_close += 1
        avg_benefit_close = sum(float(row.get("benefit_close") or 0.0) for row in rows) / max(len(rows), 1)
        return {
            "review_count": len(rows),
            "positive_close_count": positive_close,
            "avg_benefit_close": avg_benefit_close,
            "role_counts": role_counts,
            "items": rows,
        }

    def build_learning_feedback(self, conn, limit: int = 120) -> Dict[str, object]:
        rows = [
            dict(row)
            for row in fetch_rows_by_sql(
                conn,
                """
                SELECT review_role, candidate_type, market_regime, risk_mode,
                       benefit_close, benefit_next_close, outcome_close_label
                FROM realtime_ai_review_events
                WHERE applied = 1
                  AND review_role IN ('VETO', 'SOFTEN', 'TRIGGER')
                  AND benefit_close IS NOT NULL
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]
        role_stats: Dict[str, Dict[str, object]] = {
            "VETO": self._empty_role_stat("否决型"),
            "SOFTEN": self._empty_role_stat("缓和型"),
            "TRIGGER": self._empty_role_stat("触发型"),
        }
        regime_stats: Dict[str, Dict[str, float]] = {}
        total_positive = 0
        total_benefit_close = 0.0
        total_benefit_next = 0.0
        for row in rows:
            role = str(row.get("review_role") or "")
            if role not in role_stats:
                continue
            stat = role_stats[role]
            benefit_close = float(row.get("benefit_close") or 0.0)
            benefit_next = float(row.get("benefit_next_close") or 0.0)
            stat["count"] = int(stat["count"]) + 1
            stat["positive_count"] = int(stat["positive_count"]) + (1 if benefit_close > 0 else 0)
            stat["avg_benefit_close"] = float(stat["avg_benefit_close"]) + benefit_close
            stat["avg_benefit_next_close"] = float(stat["avg_benefit_next_close"]) + benefit_next
            candidate_type = str(row.get("candidate_type") or "action")
            candidate_mix = dict(stat.get("candidate_mix") or {})
            candidate_mix[candidate_type] = int(candidate_mix.get(candidate_type) or 0) + 1
            stat["candidate_mix"] = candidate_mix
            regime = str(row.get("market_regime") or "").strip() or "UNKNOWN"
            regime_entry = regime_stats.setdefault(regime, {"count": 0.0, "benefit_close": 0.0})
            regime_entry["count"] += 1.0
            regime_entry["benefit_close"] += benefit_close
            total_benefit_close += benefit_close
            total_benefit_next += benefit_next
            total_positive += 1 if benefit_close > 0 else 0
        suggestions: List[Dict[str, object]] = []
        for role, stat in role_stats.items():
            count = int(stat["count"] or 0)
            if count <= 0:
                continue
            avg_close = float(stat["avg_benefit_close"] or 0.0) / count
            avg_next = float(stat["avg_benefit_next_close"] or 0.0) / count
            positive_rate = float(stat["positive_count"] or 0.0) / count
            stat["avg_benefit_close"] = round(avg_close, 6)
            stat["avg_benefit_next_close"] = round(avg_next, 6)
            stat["positive_rate"] = round(positive_rate, 4)
            stat["message"] = self._role_feedback_message(role, avg_close, count, positive_rate)
            suggestion = self._build_role_suggestion(role, avg_close, count, positive_rate)
            if suggestion:
                suggestions.append(suggestion)
        best_regime = ""
        best_regime_avg = 0.0
        for regime, stat in regime_stats.items():
            count = int(stat["count"] or 0)
            if count <= 0:
                continue
            avg_close = float(stat["benefit_close"] or 0.0) / count
            if count >= 2 and avg_close > best_regime_avg:
                best_regime = regime
                best_regime_avg = avg_close
        if best_regime:
            suggestions.append(
                {
                    "key": "高价值场景",
                    "value": best_regime,
                    "reason": f"{best_regime} 状态下，AI 终审最近平均改善 {best_regime_avg:.2%}，可优先保留复核预算。",
                }
            )
        suggestions = suggestions[:4]
        ai_bias, risk_bias = self._feedback_bias(role_stats, len(rows))
        return {
            "evaluated_count": len(rows),
            "positive_close_count": total_positive,
            "avg_benefit_close": round(total_benefit_close / max(len(rows), 1), 6),
            "avg_benefit_next_close": round(total_benefit_next / max(len(rows), 1), 6),
            "positive_rate": round(total_positive / max(len(rows), 1), 4) if rows else 0.0,
            "role_stats": role_stats,
            "top_regime": best_regime,
            "ai_multiplier_bias": ai_bias,
            "risk_multiplier_bias": risk_bias,
            "suggestions": suggestions,
        }

    def _load_symbol_points(self, symbol: str) -> Dict[str, List[Dict[str, object]]]:
        chart_dir = self.settings.cache_dir / "charts"
        points_by_date: Dict[str, List[Dict[str, object]]] = {}
        for path in sorted(chart_dir.glob(f"intraday_{symbol}_*.json")):
            trade_date = path.stem.rsplit("_", 1)[-1]
            rows = self._read_points(path)
            if rows:
                points_by_date[trade_date] = rows
        return points_by_date

    @staticmethod
    def _read_points(path: Path) -> List[Dict[str, object]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows: List[Dict[str, object]] = []
        for item in payload.get("points") or []:
            if not isinstance(item, dict):
                continue
            try:
                ts = datetime.fromisoformat(str(item.get("ts") or ""))
            except Exception:
                continue
            rows.append(
                {
                    "ts": ts,
                    "price": float(item.get("price") or 0.0),
                }
            )
        rows.sort(key=lambda item: item["ts"])
        return rows

    @staticmethod
    def _calc_return(base_price: float, future_price: float | None) -> float | None:
        if future_price is None or base_price <= 0:
            return None
        return round((future_price - base_price) / base_price, 6)

    @staticmethod
    def _price_at_or_after(points_by_date: Mapping[str, List[Dict[str, object]]], target_ts: float) -> float | None:
        for trade_date in sorted(points_by_date.keys()):
            for point in points_by_date.get(trade_date) or []:
                if point["ts"].timestamp() >= target_ts and float(point.get("price") or 0.0) > 0:
                    return float(point["price"])
        return None

    @staticmethod
    def _same_day_close_price(
        points_by_date: Mapping[str, List[Dict[str, object]]],
        trade_date: str,
        base_dt: datetime,
    ) -> float | None:
        rows = list(points_by_date.get(trade_date) or [])
        rows = [item for item in rows if item["ts"] >= base_dt]
        if not rows:
            return None
        return float(rows[-1]["price"])

    @staticmethod
    def _next_day_close_price(points_by_date: Mapping[str, List[Dict[str, object]]], trade_date: str) -> float | None:
        later_dates = [item for item in sorted(points_by_date.keys()) if item > trade_date]
        if not later_dates:
            return None
        rows = list(points_by_date.get(later_dates[0]) or [])
        if not rows:
            return None
        return float(rows[-1]["price"])

    @staticmethod
    def _benefit(role: str, proposed_action: str, final_action: str, outcome_return: float | None) -> float | None:
        if outcome_return is None:
            return None
        draft = str(proposed_action or "HOLD").upper()
        final = str(final_action or draft).upper()
        if role == "VETO":
            return round(-outcome_return, 6)
        if role == "SOFTEN":
            multiplier = 1.0 if draft == "SELL" and final == "HOLD" else 0.5
            return round(outcome_return * multiplier, 6)
        if role == "TRIGGER":
            multiplier = 1.0 if final == "SELL" else 0.5
            return round(-outcome_return * multiplier, 6)
        return 0.0

    @staticmethod
    def _outcome_label(role: str, benefit: float | None) -> str:
        if benefit is None:
            return "待评估"
        if benefit > 0.002:
            return {
                "VETO": "避免亏损",
                "SOFTEN": "避免卖飞",
                "TRIGGER": "降低回撤",
            }.get(role, "带来正收益")
        if benefit < -0.002:
            return {
                "VETO": "错过上涨",
                "SOFTEN": "保守不足",
                "TRIGGER": "卖出偏早",
            }.get(role, "效果偏弱")
        return "影响有限"

    @staticmethod
    def _empty_role_stat(label: str) -> Dict[str, object]:
        return {
            "label": label,
            "count": 0,
            "positive_count": 0,
            "positive_rate": 0.0,
            "avg_benefit_close": 0.0,
            "avg_benefit_next_close": 0.0,
            "candidate_mix": {},
            "message": "样本不足",
        }

    @staticmethod
    def _role_feedback_message(role: str, avg_close: float, count: int, positive_rate: float) -> str:
        label_map = {
            "VETO": "拦错买",
            "SOFTEN": "缓和卖出",
            "TRIGGER": "持仓防守",
        }
        if count < 2:
            return f"{label_map.get(role, role)}样本还少，先继续观察。"
        if avg_close > 0.002:
            return f"{label_map.get(role, role)}最近有效，收盘正向占比 {positive_rate:.0%}。"
        if avg_close < -0.002:
            return f"{label_map.get(role, role)}最近偏弱，可能需要收敛这类终审。"
        return f"{label_map.get(role, role)}最近影响有限，继续积累样本。"

    @staticmethod
    def _build_role_suggestion(role: str, avg_close: float, count: int, positive_rate: float) -> Dict[str, object] | None:
        if count < 2:
            return None
        if role == "VETO" and avg_close > 0.002:
            return {
                "key": "买入终审",
                "value": "保持严格",
                "reason": f"否决型最近 {count} 次平均改善 {avg_close:.2%}，更适合继续拦截高风险买点。",
            }
        if role == "SOFTEN" and avg_close > 0.002:
            return {
                "key": "卖出缓和",
                "value": "适度放宽",
                "reason": f"缓和型正向占比 {positive_rate:.0%}，说明部分卖出动作仍有持有价值。",
            }
        if role == "TRIGGER" and avg_close > 0.002:
            return {
                "key": "持仓防守",
                "value": "优先保留",
                "reason": f"触发型最近 {count} 次平均改善 {avg_close:.2%}，对控制回撤更有帮助。",
            }
        if avg_close < -0.002:
            return {
                "key": {
                    "VETO": "买入终审",
                    "SOFTEN": "卖出缓和",
                    "TRIGGER": "持仓防守",
                }.get(role, role),
                "value": "收敛使用",
                "reason": f"{count} 次样本里平均改善 {avg_close:.2%}，这类终审最近贡献偏弱。",
            }
        return None

    @staticmethod
    def _feedback_bias(role_stats: Mapping[str, Mapping[str, object]], sample_count: int) -> tuple[float, float]:
        if sample_count < 6:
            return 0.0, 0.0
        veto_avg = float((role_stats.get("VETO") or {}).get("avg_benefit_close") or 0.0)
        soften_avg = float((role_stats.get("SOFTEN") or {}).get("avg_benefit_close") or 0.0)
        trigger_avg = float((role_stats.get("TRIGGER") or {}).get("avg_benefit_close") or 0.0)
        ai_bias = veto_avg * 2.5 + soften_avg * 2.0 + trigger_avg * 1.2
        risk_bias = veto_avg * 3.5 - soften_avg * 2.2 + trigger_avg * 3.8
        ai_bias = max(-0.06, min(0.06, ai_bias))
        risk_bias = max(-0.06, min(0.06, risk_bias))
        return round(ai_bias, 4), round(risk_bias, 4)
