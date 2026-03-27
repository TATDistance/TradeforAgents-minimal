from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import AppConfig, load_config
from .db import connect_db, initialize_db, now_ts


PRICE_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)")


@dataclass
class StructuredSignal:
    ticker: str
    market: str
    signal_date: str
    action: str
    entry_type: str
    entry_price_min: Optional[float]
    entry_price_max: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_pct: float
    confidence: float
    risk_score: float
    holding_days: int
    reason: str


def infer_market(symbol: str) -> str:
    clean = str(symbol).strip().upper()
    if clean.endswith(".SS") or clean.startswith(("5", "6", "9")):
        return "SH"
    if clean.endswith(".SZ") or clean.startswith(("0", "1", "2", "3")):
        return "SZ"
    return "UNKNOWN"


def normalize_action(raw_action: str) -> str:
    text = str(raw_action or "").strip().lower()
    if text in ("买入", "buy"):
        return "buy"
    if text in ("卖出", "sell"):
        return "sell"
    return "hold"


def parse_price_range(text: str) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None
    match = PRICE_RANGE_RE.search(str(text))
    if not match:
        return None, None
    low = float(match.group(1))
    high = float(match.group(2))
    if low > high:
        low, high = high, low
    return round(low, 3), round(high, 3)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_signal(ticker: str, analysis_date: str, decision: Dict[str, object]) -> StructuredSignal:
    action = normalize_action(str(decision.get("action", "hold")))
    confidence = clamp(float(decision.get("confidence", 0.5)), 0.0, 1.0)
    risk_score = clamp(float(decision.get("risk_score", 0.5)), 0.0, 1.0)
    target_low, target_high = parse_price_range(str(decision.get("target_price_range", "")))
    reasoning = str(decision.get("reasoning", "")).strip()
    mode = str(decision.get("mode", "quick")).strip().lower() or "quick"
    holding_days = 5 if mode == "deep" else 3
    market = infer_market(ticker)

    entry_type = "none"
    entry_min = None
    entry_max = None
    stop_loss = None
    take_profit = None
    position_pct = 0.0

    if action == "buy":
        entry_type = "limit"
        if target_low is not None and target_high is not None:
            mid = round((target_low + target_high) / 2.0, 3)
            entry_min = target_low
            entry_max = mid
            stop_loss = round(target_low * (1.0 - max(0.02, 0.01 + risk_score * 0.03)), 3)
            take_profit = target_high
        position_pct = round(clamp(0.08 + confidence * 0.18 - risk_score * 0.10, 0.05, 0.20), 3)
    elif action == "sell":
        entry_type = "market"
        entry_min = target_low
        entry_max = target_high
        take_profit = target_low
        position_pct = 1.0

    return StructuredSignal(
        ticker=ticker,
        market=market,
        signal_date=analysis_date,
        action=action,
        entry_type=entry_type,
        entry_price_min=entry_min,
        entry_price_max=entry_max,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_pct=position_pct,
        confidence=confidence,
        risk_score=risk_score,
        holding_days=holding_days,
        reason=reasoning,
    )


def iter_result_dirs(results_root: Path) -> Iterable[Path]:
    if not results_root.exists():
        return []

    result_dirs = []
    for ticker_dir in results_root.iterdir():
        if not ticker_dir.is_dir() or ticker_dir.name.startswith("_"):
            continue
        for date_dir in ticker_dir.iterdir():
            if not date_dir.is_dir():
                continue
            if (date_dir / "decision.json").exists():
                result_dirs.append(date_dir)

    return sorted(result_dirs, key=lambda path: str(path), reverse=True)


def _load_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ingest_tradeforagents_results(
    config: Optional[AppConfig] = None,
    limit: int = 20,
) -> List[int]:
    cfg = config or load_config()
    conn = connect_db(cfg)
    initialize_db(conn)

    inserted_signal_ids = []
    try:
        for result_dir in list(iter_result_dirs(cfg.tradeforagents_results_dir))[:limit]:
            decision_path = result_dir / "decision.json"
            metadata_path = result_dir / "analysis_metadata.json"
            decision = _load_json(decision_path)
            metadata = _load_json(metadata_path) if metadata_path.exists() else {}
            ticker = str(metadata.get("stock_symbol") or result_dir.parent.name)
            analysis_date = str(metadata.get("analysis_date") or result_dir.name)
            market = infer_market(ticker)

            report_row = conn.execute(
                "SELECT id, raw_decision_json FROM analysis_reports WHERE source_dir = ?",
                (str(result_dir),),
            ).fetchone()
            if report_row:
                report_id = int(report_row["id"])
                signal_row = conn.execute(
                    "SELECT id FROM signals WHERE report_id = ?",
                    (report_id,),
                ).fetchone()

                new_decision_json = json.dumps(decision, ensure_ascii=False)
                old_decision_json = str(report_row["raw_decision_json"] or "")
                if signal_row and old_decision_json == new_decision_json:
                    inserted_signal_ids.append(int(signal_row["id"]))
                    continue

                created_at = now_ts()
                conn.execute(
                    """
                    UPDATE analysis_reports
                    SET ticker = ?, market = ?, analysis_date = ?, mode = ?, action = ?,
                        confidence = ?, risk_score = ?, target_price_range = ?, reasoning = ?,
                        raw_decision_json = ?, raw_metadata_json = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (
                        ticker,
                        market,
                        analysis_date,
                        str(decision.get("mode", "quick")),
                        str(decision.get("action", "hold")),
                        float(decision.get("confidence", 0.5)),
                        float(decision.get("risk_score", 0.5)),
                        str(decision.get("target_price_range", "")),
                        str(decision.get("reasoning", "")),
                        new_decision_json,
                        json.dumps(metadata, ensure_ascii=False),
                        created_at,
                        report_id,
                    ),
                )

                signal = build_signal(ticker, analysis_date, decision)
                if signal_row:
                    signal_id = int(signal_row["id"])
                    sim_order_row = conn.execute(
                        "SELECT COUNT(1) AS count FROM sim_orders WHERE signal_id = ?",
                        (signal_id,),
                    ).fetchone()
                    has_orders = bool(sim_order_row and int(sim_order_row["count"]) > 0)
                    if not has_orders:
                        conn.execute(
                            """
                            UPDATE signals
                            SET ticker = ?, market = ?, signal_date = ?, action = ?, entry_type = ?,
                                entry_price_min = ?, entry_price_max = ?, stop_loss = ?, take_profit = ?,
                                position_pct = ?, confidence = ?, risk_score = ?, holding_days = ?,
                                reason = ?, status = 'NEW', risk_state = NULL, approved_qty = 0,
                                risk_notes = NULL, created_at = ?
                            WHERE id = ?
                            """,
                            (
                                signal.ticker,
                                signal.market,
                                signal.signal_date,
                                signal.action,
                                signal.entry_type,
                                signal.entry_price_min,
                                signal.entry_price_max,
                                signal.stop_loss,
                                signal.take_profit,
                                signal.position_pct,
                                signal.confidence,
                                signal.risk_score,
                                signal.holding_days,
                                signal.reason,
                                created_at,
                                signal_id,
                            ),
                        )
                    inserted_signal_ids.append(signal_id)
                    continue

                conn.execute(
                    """
                    INSERT INTO signals (
                        report_id, ticker, market, signal_date, action, entry_type,
                        entry_price_min, entry_price_max, stop_loss, take_profit,
                        position_pct, confidence, risk_score, holding_days, reason,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?)
                    """,
                    (
                        report_id,
                        signal.ticker,
                        signal.market,
                        signal.signal_date,
                        signal.action,
                        signal.entry_type,
                        signal.entry_price_min,
                        signal.entry_price_max,
                        signal.stop_loss,
                        signal.take_profit,
                        signal.position_pct,
                        signal.confidence,
                        signal.risk_score,
                        signal.holding_days,
                        signal.reason,
                        created_at,
                    ),
                )
                inserted_signal_ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
                continue

            created_at = now_ts()
            conn.execute(
                """
                INSERT INTO analysis_reports (
                    ticker, market, analysis_date, mode, action, confidence, risk_score,
                    target_price_range, reasoning, source_dir, raw_decision_json,
                    raw_metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    market,
                    analysis_date,
                    str(decision.get("mode", "quick")),
                    str(decision.get("action", "hold")),
                    float(decision.get("confidence", 0.5)),
                    float(decision.get("risk_score", 0.5)),
                    str(decision.get("target_price_range", "")),
                    str(decision.get("reasoning", "")),
                    str(result_dir),
                    json.dumps(decision, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    created_at,
                ),
            )
            report_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

            signal = build_signal(ticker, analysis_date, decision)
            conn.execute(
                """
                INSERT INTO signals (
                    report_id, ticker, market, signal_date, action, entry_type,
                    entry_price_min, entry_price_max, stop_loss, take_profit,
                    position_pct, confidence, risk_score, holding_days, reason,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?)
                """,
                (
                    report_id,
                    signal.ticker,
                    signal.market,
                    signal.signal_date,
                    signal.action,
                    signal.entry_type,
                    signal.entry_price_min,
                    signal.entry_price_max,
                    signal.stop_loss,
                    signal.take_profit,
                    signal.position_pct,
                    signal.confidence,
                    signal.risk_score,
                    signal.holding_days,
                    signal.reason,
                    created_at,
                ),
            )
            signal_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            inserted_signal_ids.append(signal_id)

        conn.commit()
    finally:
        conn.close()

    return inserted_signal_ids
