from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

import yaml

from .settings import Settings, load_settings, load_symbol_yaml
from .watchlist_service import WatchlistPayload, get_active_watchlist, is_watchlist_stale


def _runtime_symbols_path(settings: Settings) -> Path:
    return settings.project_root / "config" / "runtime_symbols.yaml"


def _classify_asset_type(symbol: str) -> str:
    code = str(symbol).strip()
    if code.startswith(("1", "5")):
        return "etf"
    return "stock"


def _normalize_symbols(values: List[object]) -> List[str]:
    symbols: List[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if text.isdigit() and len(text) != 6:
            continue
        symbols.append(text)
    return list(dict.fromkeys(symbols))


def load_runtime_watchlist(settings: Settings | None = None) -> WatchlistPayload:
    resolved_settings = settings or load_settings()
    runtime_path = _runtime_symbols_path(resolved_settings)
    if not runtime_path.exists():
        return {}
    payload = load_symbol_yaml(runtime_path)
    if not payload:
        return {}
    watchlist = payload.get("watchlist") or {}
    symbols = _normalize_symbols(list(watchlist.get("stocks", [])) + list(watchlist.get("etfs", [])))
    result: WatchlistPayload = {
        "symbols": [item for item in dict.fromkeys(symbols) if item],
        "source": str(payload.get("source") or "runtime"),
        "generated_at": str(payload.get("generated_at") or ""),
        "valid_until": str(payload.get("valid_until") or ""),
        "trading_day": str(payload.get("trading_day") or ""),
    }
    if payload.get("watchlist_evolution") is not None:
        result["watchlist_evolution"] = payload.get("watchlist_evolution")
    if payload.get("watchlist_events") is not None:
        result["watchlist_events"] = payload.get("watchlist_events")
    if payload.get("last_scan_at") is not None:
        result["last_scan_at"] = str(payload.get("last_scan_at") or "")
    result["stale"] = is_watchlist_stale(result, settings=resolved_settings)
    return result


def sync_watchlist_to_runtime(
    watchlist: WatchlistPayload,
    settings: Settings | None = None,
) -> WatchlistPayload:
    resolved_settings = settings or load_settings()
    symbols = _normalize_symbols(list(watchlist.get("symbols") or []))
    stocks = [symbol for symbol in symbols if _classify_asset_type(symbol) == "stock"]
    etfs = [symbol for symbol in symbols if _classify_asset_type(symbol) == "etf"]
    payload = {
        "source": str(watchlist.get("source") or "runtime"),
        "generated_at": str(watchlist.get("generated_at") or ""),
        "valid_until": str(watchlist.get("valid_until") or ""),
        "trading_day": str(watchlist.get("trading_day") or ""),
        "watchlist": {
            "stocks": stocks,
            "etfs": etfs,
        },
        "blacklist": [],
        "universe": {
            "include_stocks": True,
            "include_etfs": True,
        },
    }
    if watchlist.get("watchlist_evolution") is not None:
        payload["watchlist_evolution"] = watchlist.get("watchlist_evolution")
    if watchlist.get("watchlist_events") is not None:
        payload["watchlist_events"] = watchlist.get("watchlist_events")
    if watchlist.get("last_scan_at") is not None:
        payload["last_scan_at"] = str(watchlist.get("last_scan_at") or "")
    runtime_path = _runtime_symbols_path(resolved_settings)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result: WatchlistPayload = dict(watchlist)
    result["symbols"] = symbols
    result["stale"] = is_watchlist_stale(result, settings=resolved_settings)
    return result


def refresh_watchlist_if_needed(
    settings: Settings | None = None,
    selector_callable: Callable[[], object] | None = None,
) -> WatchlistPayload:
    resolved_settings = settings or load_settings()
    watchlist = get_active_watchlist(resolved_settings)
    if is_watchlist_stale(watchlist, settings=resolved_settings) and resolved_settings.watchlist.enable_auto_refresh_on_start and selector_callable:
        selector_callable()
        watchlist = get_active_watchlist(resolved_settings)
    return sync_watchlist_to_runtime(watchlist, resolved_settings)
