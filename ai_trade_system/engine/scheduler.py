from __future__ import annotations

from typing import Dict, Optional, Sequence

from .bridge_service import ingest_tradeforagents_results
from .config import AppConfig, load_config
from .db import connect_db, initialize_db
from .mock_broker import run_paper_execution
from .plan_center import build_daily_plan, save_daily_plan
from .risk_engine import evaluate_pending_signals


def run_end_of_day_pipeline(
    config: Optional[AppConfig] = None,
    limit: int = 20,
    trade_date: Optional[str] = None,
    execute_simulation: bool = False,
    tickers: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    cfg = config or load_config()
    imported_ids = ingest_tradeforagents_results(cfg, limit=limit)
    conn = connect_db(cfg)
    initialize_db(conn)
    try:
        risk_decisions = evaluate_pending_signals(conn)
        if trade_date:
            target_date = trade_date
        else:
            row = conn.execute(
                "SELECT MAX(signal_date) AS signal_date FROM signals"
            ).fetchone()
            target_date = str(row["signal_date"]) if row and row["signal_date"] else None
            if target_date is None:
                raise RuntimeError("No signals found after ingestion.")
        plan = build_daily_plan(conn, target_date, tickers=tickers)
        plan_path = save_daily_plan(plan, cfg.reports_dir)
        execution_events = []
        if execute_simulation:
            execution_events = run_paper_execution(conn, target_date, config=cfg)
            plan = build_daily_plan(conn, target_date, tickers=tickers)
            plan_path = save_daily_plan(plan, cfg.reports_dir)
        conn.commit()
    finally:
        conn.close()

    return {
        "imported_signal_ids": imported_ids,
        "risk_decisions": [decision.__dict__ for decision in risk_decisions],
        "plan_path": str(plan_path),
        "execution_events": execution_events,
    }
