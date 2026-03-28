from __future__ import annotations

from typing import Optional

from .db import write_manual_execution_log
from .models import ManualExecutionLog
from .settings import Settings, load_settings


class ManualExecutionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def record_execution(
        self,
        conn,
        signal_id: int,
        symbol: str,
        executed: bool,
        actual_price: Optional[float] = None,
        actual_qty: Optional[int] = None,
        reason: str = "",
        note: str = "",
    ) -> int:
        log = ManualExecutionLog(
            signal_id=signal_id,
            symbol=symbol,
            executed=executed,
            actual_price=actual_price,
            actual_qty=actual_qty,
            reason=reason,
            note=note,
        )
        return write_manual_execution_log(conn, log)
