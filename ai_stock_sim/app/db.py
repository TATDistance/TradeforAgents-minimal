from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import AccountSnapshot, AIDecision, FinalSignal, OrderRecord, PositionRecord, StrategySignal
from .settings import Settings, load_settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    action TEXT NOT NULL,
    score REAL NOT NULL,
    signal_price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    position_pct REAL NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS ai_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ai_action TEXT NOT NULL,
    confidence REAL NOT NULL,
    risk_score REAL NOT NULL,
    approved INTEGER NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    fee REAL NOT NULL,
    tax REAL NOT NULL,
    slippage REAL NOT NULL,
    status TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    qty INTEGER NOT NULL,
    avg_cost REAL NOT NULL,
    last_price REAL NOT NULL,
    market_value REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    can_sell_qty INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    market_value REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    drawdown REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    module TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS final_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    position_pct REAL NOT NULL,
    confidence REAL NOT NULL,
    source_strategies TEXT NOT NULL,
    ai_approved INTEGER NOT NULL,
    ai_reason TEXT,
    strategy_reason TEXT
);
"""


def now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect_db(settings: Settings | None = None) -> sqlite3.Connection:
    cfg = settings or load_settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cfg.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db(settings: Settings | None = None) -> None:
    cfg = settings or load_settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    conn = connect_db(cfg)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def seed_account(settings: Settings | None = None, cash: float | None = None) -> None:
    cfg = settings or load_settings()
    initialize_db(cfg)
    conn = connect_db(cfg)
    try:
        row = conn.execute("SELECT COUNT(1) AS count FROM account_snapshots").fetchone()
        if row and int(row["count"]) > 0:
            return
        amount = float(cash if cash is not None else cfg.initial_cash)
        write_account_snapshot(
            conn,
            AccountSnapshot(
                cash=amount,
                equity=amount,
                market_value=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                drawdown=0.0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def write_signal(conn: sqlite3.Connection, signal: StrategySignal) -> int:
    cursor = conn.execute(
        """
        INSERT INTO signals (ts, symbol, strategy_name, action, score, signal_price, stop_loss, take_profit, position_pct, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_ts(),
            signal.symbol,
            signal.strategy,
            signal.action,
            signal.score,
            signal.signal_price,
            signal.stop_loss,
            signal.take_profit,
            signal.position_pct,
            signal.reason,
        ),
    )
    return int(cursor.lastrowid)


def write_ai_decision(conn: sqlite3.Connection, decision: AIDecision) -> int:
    cursor = conn.execute(
        """
        INSERT INTO ai_decisions (ts, symbol, ai_action, confidence, risk_score, approved, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_ts(),
            decision.symbol,
            decision.ai_action,
            decision.confidence,
            decision.risk_score,
            1 if decision.approved else 0,
            decision.reason,
        ),
    )
    return int(cursor.lastrowid)


def write_final_signal(conn: sqlite3.Connection, signal: FinalSignal) -> int:
    cursor = conn.execute(
        """
        INSERT INTO final_signals (
            ts, symbol, action, entry_price, stop_loss, take_profit, position_pct,
            confidence, source_strategies, ai_approved, ai_reason, strategy_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_ts(),
            signal.symbol,
            signal.action,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profit,
            signal.position_pct,
            signal.confidence,
            json.dumps(signal.source_strategies, ensure_ascii=False),
            1 if signal.ai_approved else 0,
            signal.ai_reason,
            signal.strategy_reason,
        ),
    )
    return int(cursor.lastrowid)


def write_order(conn: sqlite3.Connection, order: OrderRecord) -> int:
    cursor = conn.execute(
        """
        INSERT INTO orders (ts, symbol, side, price, qty, fee, tax, slippage, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order.ts.isoformat(timespec="seconds"),
            order.symbol,
            order.side,
            order.price,
            order.qty,
            order.fee,
            order.tax,
            order.slippage,
            order.status,
            order.note,
        ),
    )
    return int(cursor.lastrowid)


def upsert_position(conn: sqlite3.Connection, position: PositionRecord) -> None:
    conn.execute(
        """
        INSERT INTO positions (symbol, qty, avg_cost, last_price, market_value, unrealized_pnl, can_sell_qty, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            qty = excluded.qty,
            avg_cost = excluded.avg_cost,
            last_price = excluded.last_price,
            market_value = excluded.market_value,
            unrealized_pnl = excluded.unrealized_pnl,
            can_sell_qty = excluded.can_sell_qty,
            updated_at = excluded.updated_at
        """,
        (
            position.symbol,
            position.qty,
            position.avg_cost,
            position.last_price,
            position.market_value,
            position.unrealized_pnl,
            position.can_sell_qty,
            position.updated_at.isoformat(timespec="seconds"),
        ),
    )


def delete_position(conn: sqlite3.Connection, symbol: str) -> None:
    conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))


def write_account_snapshot(conn: sqlite3.Connection, snapshot: AccountSnapshot) -> int:
    cursor = conn.execute(
        """
        INSERT INTO account_snapshots (ts, cash, equity, market_value, realized_pnl, unrealized_pnl, drawdown)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.ts.isoformat(timespec="seconds"),
            snapshot.cash,
            snapshot.equity,
            snapshot.market_value,
            snapshot.realized_pnl,
            snapshot.unrealized_pnl,
            snapshot.drawdown,
        ),
    )
    return int(cursor.lastrowid)


def write_system_log(conn: sqlite3.Connection, level: str, module: str, message: str) -> int:
    cursor = conn.execute(
        "INSERT INTO system_logs (ts, level, module, message) VALUES (?, ?, ?, ?)",
        (now_ts(), level.upper(), module, message),
    )
    return int(cursor.lastrowid)


def fetch_latest_account(conn: sqlite3.Connection) -> Dict[str, float]:
    row = conn.execute(
        "SELECT * FROM account_snapshots ORDER BY ts DESC, id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {
            "cash": 0.0,
            "equity": 0.0,
            "market_value": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "drawdown": 0.0,
        }
    return {key: float(row[key]) for key in ("cash", "equity", "market_value", "realized_pnl", "unrealized_pnl", "drawdown")}


def fetch_positions(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()


def fetch_recent_rows(conn: sqlite3.Connection, table: str, limit: int = 20) -> List[sqlite3.Row]:
    if table not in {"signals", "ai_decisions", "orders", "positions", "account_snapshots", "system_logs", "final_signals"}:
        raise ValueError("unsupported table")
    return conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def fetch_recent_equity_curve(conn: sqlite3.Connection, limit: int = 200) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT ts, equity, drawdown FROM account_snapshots ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()[::-1]


def max_equity(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT COALESCE(MAX(equity), 0) AS value FROM account_snapshots").fetchone()
    return float(row["value"]) if row else 0.0
