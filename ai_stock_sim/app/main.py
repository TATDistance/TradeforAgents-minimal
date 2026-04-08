from __future__ import annotations

import atexit
import os
import signal
import subprocess
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
    lock_acquired = False

    def _pid_alive(pid: int | None) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _pid_command(pid: int | None) -> str:
        if not pid or pid <= 0 or os.name == "nt":
            return ""
        try:
            output = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "cmd="],
                stderr=subprocess.DEVNULL,
                timeout=0.8,
            )
            return output.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""

    def _pid_matches_engine(pid: int | None) -> bool:
        if not _pid_alive(pid):
            return False
        if os.name == "nt":
            return True
        cmd = _pid_command(pid).lower()
        if not cmd:
            return False
        return any(
            marker in cmd
            for marker in (
                "python -m app.main",
                "run_engine.sh",
                "role_engine",
            )
        )

    def _read_pid() -> int | None:
        if not pid_path.exists():
            return None
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    try:
        existing_pid = _read_pid()
        if existing_pid and existing_pid != os.getpid():
            if _pid_matches_engine(existing_pid):
                log_event(logger, "warning", "main", "engine_already_running", pid=existing_pid, pid_path=str(pid_path))
                raise SystemExit(0)
            log_event(logger, "warning", "main", "engine_stale_pid_ignored", pid=existing_pid, pid_path=str(pid_path))
            try:
                pid_path.unlink()
            except Exception:
                pass
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
            except OSError:
                stale_pid = _read_pid()
                if stale_pid and _pid_matches_engine(stale_pid):
                    log_event(logger, "warning", "main", "engine_already_running", lock_path=str(lock_path), pid=stale_pid)
                    raise SystemExit(0)
                log_event(logger, "warning", "main", "engine_stale_lock_bypassed", lock_path=str(lock_path), pid_path=str(pid_path))
        pid_path.write_text(str(os.getpid()), encoding="utf-8")

        def _cleanup() -> None:
            try:
                if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_path.unlink()
            except Exception:
                pass
            try:
                if fcntl is not None and lock_acquired:
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
            if fcntl is not None and lock_acquired:
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
    with _engine_process_guard(settings, logger):
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
        scheduler.run_cycle()
        scheduler.start()
        while True:
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
