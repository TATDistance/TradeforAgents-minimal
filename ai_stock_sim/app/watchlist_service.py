from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List

from .settings import Settings, load_settings, load_symbol_config
from .trading_calendar_service import TradingCalendarService


WatchlistPayload = Dict[str, object]


def _candidate_report_dirs(settings: Settings) -> List[Path]:
    dirs: List[Path] = []
    embedded = settings.project_root.parent / "ai_trade_system" / "reports"
    legacy = settings.project_root.parent.parent / "ai_trade_system" / "reports"
    for path in (embedded, legacy):
        if path.exists() and path not in dirs:
            dirs.append(path)
    return dirs


def _parse_watchlist_lines(path: Path) -> List[str]:
    try:
        rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except Exception:
        return []
    symbols = [value for value in rows if value and (not value.isdigit() or len(value) == 6)]
    return list(dict.fromkeys(symbols))


def _coerce_trade_date(path: Path) -> str:
    stem = path.stem
    if stem.startswith("auto_watchlist_"):
        return stem.replace("auto_watchlist_", "").strip()
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def _next_trading_day(calendar: TradingCalendarService, trading_day: str) -> str:
    return calendar.next_trading_day(date.fromisoformat(trading_day)).isoformat()


def _watchlist_payload(
    *,
    settings: Settings,
    symbols: List[str],
    source: str,
    generated_at: str,
    trading_day: str,
) -> WatchlistPayload:
    calendar = TradingCalendarService(settings)
    valid_until = datetime.combine(
        date.fromisoformat(_next_trading_day(calendar, trading_day)),
        time(hour=9, minute=0, second=0),
    ).isoformat(timespec="seconds")
    payload: WatchlistPayload = {
        "symbols": list(dict.fromkeys(symbols)),
        "source": source,
        "generated_at": generated_at,
        "valid_until": valid_until,
        "trading_day": trading_day,
    }
    payload["stale"] = is_watchlist_stale(payload, settings=settings)
    return payload


def load_default_watchlist(settings: Settings | None = None) -> List[str]:
    resolved_settings = settings or load_settings()
    symbols = load_symbol_config(resolved_settings.project_root)
    values = [*symbols.stock_watchlist, *symbols.etf_watchlist]
    return [value for value in dict.fromkeys(values) if value]


def is_watchlist_stale(
    watchlist: WatchlistPayload | None,
    *,
    settings: Settings | None = None,
    reference_time: datetime | None = None,
) -> bool:
    if not watchlist or not list(watchlist.get("symbols") or []):
        return True
    resolved_settings = settings or load_settings()
    now = reference_time or datetime.now()
    valid_until = str(watchlist.get("valid_until") or "")
    if valid_until:
        try:
            if datetime.fromisoformat(valid_until) < now:
                return True
        except Exception:
            pass
    trading_day = str(watchlist.get("trading_day") or "")
    if not trading_day:
        return str(watchlist.get("source") or "") == "default_fallback"
    calendar = TradingCalendarService(resolved_settings)
    today = now.date()
    watch_date = date.fromisoformat(trading_day)
    if calendar.is_trading_day(today) and watch_date < today:
        return True
    if str(watchlist.get("source") or "") == "default_fallback" and calendar.is_trading_day(today):
        return True
    return False


def get_active_watchlist(settings: Settings | None = None) -> WatchlistPayload:
    resolved_settings = settings or load_settings()
    now = datetime.now()
    today = now.date().isoformat()
    watchlist_files: List[Path] = []
    for report_dir in _candidate_report_dirs(resolved_settings):
        watchlist_files.extend(report_dir.glob("auto_watchlist_*.txt"))
    if watchlist_files:
        today_candidates = [path for path in watchlist_files if path.stem.endswith(today)]
        if today_candidates:
            latest = max(today_candidates, key=lambda item: item.stat().st_mtime)
            return _watchlist_payload(
                settings=resolved_settings,
                symbols=_parse_watchlist_lines(latest),
                source="auto_selector_today",
                generated_at=datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds"),
                trading_day=_coerce_trade_date(latest),
            )
        if resolved_settings.watchlist.use_recent_candidates_as_fallback:
            latest = max(watchlist_files, key=lambda item: item.stat().st_mtime)
            return _watchlist_payload(
                settings=resolved_settings,
                symbols=_parse_watchlist_lines(latest),
                source="recent_candidates",
                generated_at=datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds"),
                trading_day=_coerce_trade_date(latest),
            )
    default_symbols = load_default_watchlist(resolved_settings) if resolved_settings.watchlist.use_default_watchlist_as_last_resort else []
    generated_at = now.isoformat(timespec="seconds")
    return _watchlist_payload(
        settings=resolved_settings,
        symbols=default_symbols,
        source="default_fallback",
        generated_at=generated_at,
        trading_day=today,
    )
