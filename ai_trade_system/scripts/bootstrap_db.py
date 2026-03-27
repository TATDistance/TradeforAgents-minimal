from __future__ import annotations

import argparse

from ai_trade_system.engine.config import load_config
from ai_trade_system.engine.db import connect_db, initialize_db, seed_account


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize SQLite database and seed a paper account.")
    parser.add_argument("--cash", type=float, default=100000.0, help="Initial paper cash balance.")
    args = parser.parse_args()

    config = load_config()
    conn = connect_db(config)
    try:
        initialize_db(conn)
        seed_account(conn, args.cash)
    finally:
        conn.close()

    print("Database ready: {0}".format(config.db_path))


if __name__ == "__main__":
    main()
