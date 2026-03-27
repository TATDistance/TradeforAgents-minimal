from __future__ import annotations

from ai_trade_system.engine.config import load_config
from ai_trade_system.engine.db import connect_db, initialize_db
from ai_trade_system.engine.review_service import generate_review, save_review


def main() -> None:
    config = load_config()
    conn = connect_db(config)
    try:
        initialize_db(conn)
        review = generate_review(conn)
    finally:
        conn.close()

    path = save_review(review, config.reports_dir)
    print("Review saved to: {0}".format(path))


if __name__ == "__main__":
    main()
