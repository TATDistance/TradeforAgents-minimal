from __future__ import annotations

import atexit
import os
import signal
import sys
import time
from contextlib import contextmanager

try:
    import fcntl
except Exception:  # pragma: no cover - non-posix fallback
    fcntl = None

from .db import initialize_simulation_account_dbs, seed_simulation_accounts
from .logger import configure_logger, log_event
from .scheduler import TradingScheduler
from .settings import load_settings


@contextmanager
def _engine_process_guard(settings, logger):
    pid_path = settings.data_dir / "engine.pid"
    lock_path = settings.data_dir / "engine.lock"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                log_event(logger, "warning", "main", "engine_already_running", lock_path=str(lock_path))
                raise SystemExit(0)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")

        def _cleanup() -> None:
            try:
                if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_path.unlink()
            except Exception:
                pass
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass

        atexit.register(_cleanup)
        yield
    finally:
        try:
            if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_path.unlink()
        except Exception:
            pass
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            handle.close()
        except Exception:
            pass


def main() -> int:
    settings = load_settings()
    initialize_simulation_account_dbs(settings)
    seed_simulation_accounts(settings)
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
    log_event(
        logger,
        "info",
        "main",
        "engine_starting",
        refresh_interval=settings.refresh_interval_seconds,
        decision_mode=settings.decision_engine.mode,
        engine_mode=settings.runtime.engine_mode,
    )
    with _engine_process_guard(settings, logger):
        scheduler.run_cycle()
        scheduler.start()
        while True:
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
