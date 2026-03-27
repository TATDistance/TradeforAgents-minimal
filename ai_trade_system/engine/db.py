from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import AppConfig, load_config


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    risk_score REAL NOT NULL,
    target_price_range TEXT,
    reasoning TEXT,
    source_dir TEXT NOT NULL UNIQUE,
    raw_decision_json TEXT NOT NULL,
    raw_metadata_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL UNIQUE,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    action TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    entry_price_min REAL,
    entry_price_max REAL,
    stop_loss REAL,
    take_profit REAL,
    position_pct REAL NOT NULL,
    confidence REAL NOT NULL,
    risk_score REAL NOT NULL,
    holding_days INTEGER NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'NEW',
    risk_state TEXT,
    approved_qty INTEGER NOT NULL DEFAULT 0,
    risk_notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(report_id) REFERENCES analysis_reports(id)
);

CREATE TABLE IF NOT EXISTS sim_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_qty INTEGER NOT NULL,
    approved_qty INTEGER NOT NULL,
    fill_qty INTEGER NOT NULL DEFAULT 0,
    order_price REAL,
    fill_price REAL,
    fees REAL NOT NULL DEFAULT 0,
    taxes REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(signal_id, order_date),
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    can_sell_qty INTEGER NOT NULL,
    pending_sellable_qty INTEGER NOT NULL DEFAULT 0,
    avg_cost REAL NOT NULL,
    last_price REAL NOT NULL,
    market_value REAL NOT NULL,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL UNIQUE,
    cash REAL NOT NULL,
    frozen_cash REAL NOT NULL DEFAULT 0,
    equity REAL NOT NULL,
    market_value REAL NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0,
    drawdown REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_exec_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    planned_qty INTEGER,
    actual_qty INTEGER,
    execution_status TEXT NOT NULL,
    broker_app TEXT,
    note TEXT,
    executed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);
"""


def now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect_db(config: Optional[AppConfig] = None) -> sqlite3.Connection:
    cfg = config or load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cfg.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_account(conn: sqlite3.Connection, cash: float) -> None:
    initialize_db(conn)
    row = conn.execute(
        "SELECT COUNT(1) AS count FROM account_snapshots"
    ).fetchone()
    if row and int(row["count"]) > 0:
        return

    conn.execute(
        """
        INSERT INTO account_snapshots (
            snapshot_date, cash, equity, market_value, daily_pnl, drawdown, note, created_at
        ) VALUES (?, ?, ?, 0, 0, 0, ?, ?)
        """,
        (datetime.now().date().isoformat(), float(cash), float(cash), "Initial paper account", now_ts()),
    )
    conn.commit()


def latest_snapshot(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM account_snapshots
        ORDER BY snapshot_date DESC, id DESC
        LIMIT 1
        """
    ).fetchone()


def compute_account_state(conn: sqlite3.Connection) -> Dict[str, Any]:
    snapshot = latest_snapshot(conn)
    cash = float(snapshot["cash"]) if snapshot else 0.0
    rows = conn.execute("SELECT * FROM positions ORDER BY ticker").fetchall()
    market_value = sum(float(row["market_value"]) for row in rows)
    equity = cash + market_value
    return {
        "cash": cash,
        "market_value": market_value,
        "equity": equity,
        "positions": rows,
    }


def max_historical_equity(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(MAX(equity), 0) AS max_equity FROM account_snapshots"
    ).fetchone()
    return float(row["max_equity"]) if row else 0.0
