from __future__ import annotations

import argparse

from ai_trade_system.engine.config import load_config
from ai_trade_system.engine.db import connect_db, initialize_db, latest_snapshot, seed_account
from ai_trade_system.engine.scheduler import run_end_of_day_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TradeforAgents results and build a daily plan.")
    parser.add_argument("--limit", type=int, default=20, help="How many latest result folders to ingest.")
    parser.add_argument("--trade-date", default=None, help="Signal date to plan or simulate. Defaults to latest imported signal date.")
    parser.add_argument("--execute-sim", action="store_true", help="Run paper execution for approved signals.")
    parser.add_argument("--seed-cash", type=float, default=100000.0, help="Initial seed cash if the DB is empty.")
    args = parser.parse_args()

    config = load_config()
    conn = connect_db(config)
    try:
        initialize_db(conn)
        if latest_snapshot(conn) is None:
            seed_account(conn, args.seed_cash)
    finally:
        conn.close()

    result = run_end_of_day_pipeline(
        config=config,
        limit=args.limit,
        trade_date=args.trade_date,
        execute_simulation=args.execute_sim,
    )
    print("Plan saved to: {0}".format(result["plan_path"]))
    if result["execution_events"]:
        print("Execution events:")
        for event in result["execution_events"]:
            print("- {0}".format(event))


if __name__ == "__main__":
    main()
