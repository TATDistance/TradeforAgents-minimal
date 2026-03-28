from __future__ import annotations

import signal
import sys
import time

from .db import initialize_db, seed_account
from .logger import configure_logger, log_event
from .scheduler import TradingScheduler
from .settings import load_settings


def main() -> int:
    settings = load_settings()
    initialize_db(settings)
    seed_account(settings)
    logger = configure_logger(settings.logs_dir / "engine.log")
    scheduler = TradingScheduler(settings, logger=logger)

    def _shutdown(*_args) -> None:
        log_event(logger, "info", "main", "shutting_down")
        try:
            scheduler.shutdown()
        except Exception:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    log_event(logger, "info", "main", "engine_starting", refresh_interval=settings.refresh_interval_seconds)
    scheduler.start()
    scheduler.run_cycle()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
