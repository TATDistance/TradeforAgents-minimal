from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

from .models import MarketQuote
from .market_clock import MarketClock
from .settings import Settings, load_settings


EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
EASTMONEY_RETRY_ATTEMPTS = max(1, int(os.getenv("TA_EASTMONEY_RETRY_ATTEMPTS", "1")))
EASTMONEY_RETRY_BACKOFF_SECONDS = 0.35
EASTMONEY_REQUEST_TIMEOUT_SECONDS = max(1.0, float(os.getenv("TA_EASTMONEY_TIMEOUT_SECONDS", "4")))


def infer_market(symbol: str) -> str:
    code = str(symbol)
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def secid_for_symbol(symbol: str, market: Optional[str] = None) -> str:
    resolved = market or infer_market(symbol)
    return f"{1 if resolved == 'SH' else 0}.{symbol}"


class MarketDataService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.session = requests.Session()
        self.session.headers.update(EASTMONEY_HEADERS)
        self.session.trust_env = False
        self.market_clock = MarketClock(self.settings.market_session)
        self.cache_dir = self.settings.cache_dir / "market"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_file(self, prefix: str, key: str) -> Path:
        safe_key = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in key)
        return self.cache_dir / f"{prefix}_{safe_key}.json"

    @staticmethod
    def _cache_fresh(cache_path: Path, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0 or not cache_path.exists():
            return False
        age = time.time() - cache_path.stat().st_mtime
        return age <= ttl_seconds

    @staticmethod
    def _read_cached_json(cache_path: Path) -> Dict[str, object]:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    @staticmethod
    def _normalize_em_price(value: object) -> float:
        raw = float(value or 0.0)
        if raw == 0.0:
            return 0.0
        return raw / 100.0 if abs(raw) >= 1000 else raw

    @staticmethod
    def _normalize_em_pct_change(value: object) -> float:
        raw = float(value or 0.0)
        if raw == 0.0:
            return 0.0
        if abs(raw) >= 100:
            return raw / 10000.0
        return raw / 100.0

    def _get_json(self, url: str, params: Dict[str, object], cache_path: Optional[Path] = None) -> Dict[str, object]:
        last_error: Exception | None = None
        for attempt in range(1, EASTMONEY_RETRY_ATTEMPTS + 1):
            try:
                response = self.session.get(url, params=params, timeout=EASTMONEY_REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                payload = response.json()
                if cache_path:
                    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                return payload
            except Exception as exc:
                last_error = exc
                if attempt < EASTMONEY_RETRY_ATTEMPTS:
                    time.sleep(EASTMONEY_RETRY_BACKOFF_SECONDS * attempt)
        if cache_path and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        if last_error is not None:
            raise last_error
        raise RuntimeError("eastmoney request failed without explicit exception")

    def fetch_realtime_snapshot(self, limit: int = 300, include_etf: bool = True) -> pd.DataFrame:
        cache_path = self._cache_file("snapshot_combined", f"{limit}_{int(include_etf)}")
        if self._cache_fresh(cache_path, self.settings.cache.snapshot_ttl_seconds):
            cached = self._read_cached_json(cache_path)
            rows = cached.get("rows") or []
            if rows:
                return pd.DataFrame(rows)
        try:
            frames = [self._fetch_spot_frame(asset_type="stock", limit=limit)]
            if include_etf:
                frames.append(self._fetch_spot_frame(asset_type="etf", limit=min(80, limit)))
            combined = pd.concat(frames, ignore_index=True)
            combined = combined.sort_values(by="amount", ascending=False).drop_duplicates(subset=["symbol"])
            result = combined.reset_index(drop=True)
            cache_path.write_text(
                json.dumps({"rows": result.to_dict(orient="records")}, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            return result
        except Exception:
            if cache_path.exists():
                cached = self._read_cached_json(cache_path)
                rows = cached.get("rows") or []
                if rows:
                    return pd.DataFrame(rows)
            return self._local_snapshot_frame(limit=limit)

    def _fetch_spot_frame(self, asset_type: str, limit: int) -> pd.DataFrame:
        if asset_type == "stock":
            fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
        else:
            fs = "b:MK0021,b:MK0022,b:MK0023,b:MK0024"
        params = {
            "pn": 1,
            "pz": max(1, min(int(limit), 500)),
            "po": 1,
            "np": 1,
            "ut": EASTMONEY_UT,
            "fltt": 2,
            "invt": 2,
            "fid": "f6",
            "fs": fs,
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18",
        }
        cache_path = self._cache_file("spot", f"{asset_type}_{limit}")
        payload = self._get_json("https://82.push2.eastmoney.com/api/qt/clist/get", params, cache_path=cache_path)
        rows = (payload.get("data") or {}).get("diff") or []
        parsed: List[Dict[str, object]] = []
        now = datetime.now()
        for row in rows:
            symbol = str(row.get("f12") or "").strip()
            if len(symbol) != 6:
                continue
            name = str(row.get("f14") or symbol)
            parsed.append(
                {
                    "ts": now,
                    "symbol": symbol,
                    "name": name,
                    "market": "SH" if str(row.get("f13")) == "1" else "SZ",
                    "asset_type": asset_type,
                    "latest_price": float(row.get("f2") or 0.0),
                    "pct_change": float(row.get("f3") or 0.0),
                    "open_price": float(row.get("f17") or 0.0),
                    "high_price": float(row.get("f15") or 0.0),
                    "low_price": float(row.get("f16") or 0.0),
                    "prev_close": float(row.get("f18") or 0.0),
                    "volume": float(row.get("f5") or 0.0),
                    "amount": float(row.get("f6") or 0.0),
                    "turnover_rate": float(row.get("f8") or 0.0),
                    "is_st": "ST" in name.upper(),
                    "data_source": "eastmoney_live",
                }
            )
        return pd.DataFrame(parsed)

    def fetch_realtime_quote(self, symbol: str) -> MarketQuote:
        cache_path = self._cache_file("quote_obj", symbol)
        if self._cache_fresh(cache_path, self.settings.cache.quote_ttl_seconds):
            return MarketQuote(**self._read_cached_json(cache_path))
        try:
            params = {
                "secid": secid_for_symbol(symbol),
                "ut": EASTMONEY_UT,
                "invt": 2,
                "fltt": 2,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169",
            }
            payload = self._get_json(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params,
                cache_path=self._cache_file("quote", symbol),
            )
            data = payload.get("data") or {}
            quote = MarketQuote(
                ts=datetime.now(),
                symbol=symbol,
                name=str(data.get("f58") or symbol),
                market=infer_market(symbol),
                asset_type="etf" if symbol.startswith(("1", "5")) else "stock",
                latest_price=self._normalize_em_price(data.get("f43")),
                pct_change=self._normalize_em_pct_change(data.get("f169")),
                open_price=self._normalize_em_price(data.get("f46")),
                high_price=self._normalize_em_price(data.get("f44")),
                low_price=self._normalize_em_price(data.get("f45")),
                prev_close=self._normalize_em_price(data.get("f60")),
                volume=float(data.get("f47") or 0.0),
                amount=float(data.get("f48") or 0.0),
                turnover_rate=0.0,
                is_st="ST" in str(data.get("f58") or "").upper(),
                data_source="eastmoney_quote",
            )
            cache_path.write_text(json.dumps(quote.model_dump(), ensure_ascii=False, default=str), encoding="utf-8")
            return quote
        except Exception:
            if cache_path.exists():
                return MarketQuote(**self._read_cached_json(cache_path))
            local = self._latest_local_quote(symbol)
            if local is not None:
                return local
            raise

    def build_quote_from_snapshot_row(self, row: Dict[str, object]) -> MarketQuote:
        symbol = str(row.get("symbol") or "")
        return MarketQuote(
            ts=datetime.now(),
            symbol=symbol,
            name=str(row.get("name") or symbol),
            market=str(row.get("market") or infer_market(symbol)),
            asset_type=str(row.get("asset_type") or ("etf" if symbol.startswith(("1", "5")) else "stock")),
            latest_price=float(row.get("latest_price") or 0.0),
            pct_change=float(row.get("pct_change") or 0.0) / 100.0,
            open_price=float(row.get("open_price") or 0.0),
            high_price=float(row.get("high_price") or 0.0),
            low_price=float(row.get("low_price") or 0.0),
            prev_close=float(row.get("prev_close") or 0.0),
            volume=float(row.get("volume") or 0.0),
            amount=float(row.get("amount") or 0.0),
            turnover_rate=float(row.get("turnover_rate") or 0.0),
            is_st=bool(row.get("is_st") or False),
            data_source="snapshot_fallback",
        )

    def fetch_history_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        asset_type: str = "stock",
        limit: int = 240,
    ) -> pd.DataFrame:
        end = end_date or datetime.now().strftime("%Y%m%d")
        begin = start_date or (datetime.now() - timedelta(days=limit * 2)).strftime("%Y%m%d")
        history_cache = self._cache_file("history_frame", f"{symbol}_{asset_type}_{begin}_{end}_{limit}")
        phase = self.market_clock.phase()
        ttl = self.settings.cache.history_market_hours_ttl_seconds if phase.is_trading_session else self.settings.cache.history_off_hours_ttl_seconds
        if self._cache_fresh(history_cache, ttl):
            cached = self._read_cached_json(history_cache)
            rows = cached.get("rows") or []
            if rows:
                return pd.DataFrame(rows)
        try:
            frame = self._fetch_history_eastmoney(symbol=symbol, start_date=begin, end_date=end, limit=limit)
            if not frame.empty:
                history_cache.write_text(
                    json.dumps({"rows": frame.to_dict(orient="records")}, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                return frame
        except Exception:
            pass
        try:
            frame = self._fetch_history_akshare(symbol=symbol, start_date=begin, end_date=end, asset_type=asset_type)
            if not frame.empty:
                history_cache.write_text(
                    json.dumps({"rows": frame.to_dict(orient="records")}, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                return frame
        except Exception:
            pass
        frame = self._fetch_history_from_local_results(symbol=symbol, limit=limit)
        if not frame.empty:
            history_cache.write_text(
                json.dumps({"rows": frame.to_dict(orient="records")}, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        return frame

    def _fetch_history_eastmoney(self, symbol: str, start_date: str, end_date: str, limit: int) -> pd.DataFrame:
        params = {
            "secid": secid_for_symbol(symbol),
            "ut": EASTMONEY_UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101,
            "fqt": 1,
            "beg": start_date.replace("-", ""),
            "end": end_date.replace("-", ""),
            "lmt": limit,
        }
        payload = self._get_json(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params,
            cache_path=self._cache_file("daily", f"{symbol}_{start_date}_{end_date}_{limit}"),
        )
        klines = (payload.get("data") or {}).get("klines") or []
        rows: List[Dict[str, object]] = []
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 7:
                continue
            rows.append(
                {
                    "trade_date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                }
            )
        return pd.DataFrame(rows)

    def _fetch_history_akshare(self, symbol: str, start_date: str, end_date: str, asset_type: str) -> pd.DataFrame:
        if ak is None:
            return pd.DataFrame(columns=["trade_date", "open", "close", "high", "low", "volume", "amount"])
        original_env = {key: os.environ.get(key) for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
        try:
            for key in original_env:
                os.environ.pop(key, None)
            if asset_type == "etf":
                frame = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            else:
                frame = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        finally:
            for key, value in original_env.items():
                if value:
                    os.environ[key] = value
        if frame.empty:
            return pd.DataFrame(columns=["trade_date", "open", "close", "high", "low", "volume", "amount"])
        frame = frame.rename(
            columns={
                "日期": "trade_date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        columns = ["trade_date", "open", "close", "high", "low", "volume", "amount"]
        return frame[columns].copy()

    def _fetch_history_from_local_results(self, symbol: str, limit: int = 240) -> pd.DataFrame:
        rows: List[Dict[str, object]] = []
        symbol_root = self.settings.tradeforagents_results_dir / symbol
        if not symbol_root.exists():
            return pd.DataFrame(columns=["trade_date", "open", "close", "high", "low", "volume", "amount"])
        for date_dir in sorted(symbol_root.iterdir()):
            snapshot_path = date_dir / "reports" / "market_snapshot.json"
            if not snapshot_path.exists():
                continue
            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                latest = payload.get("latest") or {}
                rows.append(
                    {
                        "trade_date": str(latest.get("date") or date_dir.name),
                        "open": float(latest["open"]),
                        "close": float(latest["close"]),
                        "high": float(latest["high"]),
                        "low": float(latest["low"]),
                        "volume": float(latest.get("volume", 0) or 0),
                        "amount": float(latest.get("volume", 0) or 0) * float(latest["close"]),
                    }
                )
            except Exception:
                continue
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        return frame.sort_values(by="trade_date").tail(limit).reset_index(drop=True)

    def _local_snapshot_frame(self, limit: int = 300) -> pd.DataFrame:
        records: List[Dict[str, object]] = []
        root = self.settings.tradeforagents_results_dir
        if not root.exists():
            return pd.DataFrame(columns=["symbol", "asset_type", "amount", "is_st"])
        for symbol_dir in sorted(root.iterdir()):
            if not symbol_dir.is_dir() or symbol_dir.name.startswith("_"):
                continue
            quote = self._latest_local_quote(symbol_dir.name)
            if quote is None:
                continue
            records.append(quote.model_dump())
        frame = pd.DataFrame(records)
        if frame.empty:
            return frame
        return frame.sort_values(by="amount", ascending=False).head(limit).reset_index(drop=True)

    def _latest_local_quote(self, symbol: str) -> Optional[MarketQuote]:
        symbol_root = self.settings.tradeforagents_results_dir / symbol
        if not symbol_root.exists():
            return None
        latest_quote: Optional[MarketQuote] = None
        for date_dir in sorted(symbol_root.iterdir(), reverse=True):
            snapshot_path = date_dir / "reports" / "market_snapshot.json"
            if not snapshot_path.exists():
                continue
            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                latest = payload.get("latest") or {}
                close_price = float(latest["close"])
                prev_close = float(latest.get("previous_close") or close_price)
                pct_change = 0.0 if prev_close <= 0 else (close_price - prev_close) / prev_close * 100
                latest_quote = MarketQuote(
                    ts=datetime.now(),
                    symbol=symbol,
                    name=str((payload.get("fundamentals") or {}).get("longName") or symbol),
                    market=infer_market(symbol),
                    asset_type="etf" if symbol.startswith(("1", "5")) else "stock",
                    latest_price=close_price,
                    pct_change=pct_change,
                    open_price=float(latest["open"]),
                    high_price=float(latest["high"]),
                    low_price=float(latest["low"]),
                    prev_close=prev_close,
                    volume=float(latest.get("volume", 0) or 0),
                    amount=float(latest.get("volume", 0) or 0) * close_price,
                    turnover_rate=0.0,
                    is_st="ST" in str((payload.get("fundamentals") or {}).get("longName") or "").upper(),
                    data_source="tradeforagents_local",
                )
                break
            except Exception:
                continue
        return latest_quote
