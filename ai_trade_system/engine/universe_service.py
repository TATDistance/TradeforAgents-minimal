from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import AppConfig, load_config
from .market_data import PriceBar, ResultBarStore

try:
    import akshare as ak
except Exception:  # pragma: no cover - optional dependency in Python 3.10 env
    ak = None


EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"


@dataclass
class UniverseQuote:
    symbol: str
    market: str
    name: str
    last_price: float
    pct_change: float
    volume: float
    amount: float
    open_price: float
    high_price: float
    low_price: float
    prev_close: float
    data_source: str


@dataclass
class UniverseBar:
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float


@dataclass
class UniverseFetchResult:
    quotes: List[UniverseQuote]
    source: str
    cache_path: Optional[Path]
    warnings: List[str]


@dataclass
class CandidateEnhancement:
    symbol: str
    industry_name: str = ""
    fund_flow_rank_5d: int = 0
    fund_flow_main_net_inflow_5d: float = 0.0
    fund_flow_main_net_pct_5d: float = 0.0
    notice_count_3d: int = 0
    risk_notice_count_14d: int = 0
    latest_notice_date: str = ""
    finance_report_date: str = ""
    revenue_yoy: float = 0.0
    net_profit_yoy: float = 0.0
    roe: float = 0.0
    data_sources: List[str] = field(default_factory=list)


@dataclass
class EnhancementFetchResult:
    items: Dict[str, CandidateEnhancement]
    warnings: List[str]


def infer_market(symbol: str) -> str:
    if str(symbol).startswith(("5", "6", "9")):
        return "SH"
    if str(symbol).startswith(("0", "1", "2", "3")):
        return "SZ"
    return "UNKNOWN"


def secid_for_symbol(symbol: str, market: Optional[str] = None) -> str:
    resolved_market = market or infer_market(symbol)
    if resolved_market == "SH":
        return "1.{0}".format(symbol)
    return "0.{0}".format(symbol)


class UniverseService:
    def __init__(self, config: Optional[AppConfig] = None, timeout: int = 15) -> None:
        self.config = config or load_config()
        self.timeout = timeout
        self.cache_dir = self.config.data_dir / "raw" / "eastmoney"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.result_bar_store = ResultBarStore(self.config.tradeforagents_results_dir)

    def _cache_file(self, prefix: str, key: str) -> Path:
        safe_key = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in key)
        return self.cache_dir / "{0}_{1}.json".format(prefix, safe_key)

    def _load_cached_json(self, cache_path: Path, force_refresh: bool = False) -> Optional[Dict[str, object]]:
        if not cache_path.exists() or force_refresh:
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _write_cached_json(self, cache_path: Path, payload: Dict[str, object]) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _should_bypass_remote_proxy() -> bool:
        override = os.environ.get("TRADEFORAGENTS_BYPASS_REMOTE_PROXY", "").strip().lower()
        if override in {"1", "true", "yes", "on"}:
            return True
        if override in {"0", "false", "no", "off"}:
            return False
        return os.name != "nt"

    def _remote_opener(self) -> urllib.request.OpenerDirector:
        if self._should_bypass_remote_proxy():
            return urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener()

    @staticmethod
    def _to_float(value: object, default: float = 0.0) -> float:
        try:
            if value in ("-", None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _request_json(self, url: str, params: Dict[str, object], cache_path: Path, force_refresh: bool = False) -> Dict[str, object]:
        if cache_path.exists() and not force_refresh:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        query = urllib.parse.urlencode(params)
        request = urllib.request.Request("{0}?{1}".format(url, query), headers=EASTMONEY_HEADERS)
        try:
            opener = self._remote_opener()
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if cache_path.exists():
                return json.loads(cache_path.read_text(encoding="utf-8"))
            raise

        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _local_quote_from_snapshot(self, snapshot_path: Path) -> Optional[UniverseQuote]:
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            latest = payload.get("latest") or {}
            fundamentals = payload.get("fundamentals") or {}
            symbol = str(payload.get("symbol") or snapshot_path.parents[2].name)
            clean_symbol = symbol.split(".")[0]
            close_price = float(latest["close"])
            open_price = float(latest["open"])
            high_price = float(latest["high"])
            low_price = float(latest["low"])
            volume = float(latest.get("volume", 0) or 0)
            prev_close = close_price
            amount = volume * close_price
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

        return UniverseQuote(
            symbol=clean_symbol,
            market=infer_market(clean_symbol),
            name=str(fundamentals.get("longName") or clean_symbol),
            last_price=close_price,
            pct_change=0.0 if prev_close <= 0 else (close_price - prev_close) / prev_close * 100.0,
            volume=volume,
            amount=amount,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            prev_close=prev_close,
            data_source="tradeforagents_local",
        )

    def _local_quote_from_auto_candidate(self, row: Dict[str, object]) -> Optional[UniverseQuote]:
        try:
            symbol = str(row.get("symbol") or "").strip()
            if len(symbol) != 6 or not symbol.isdigit():
                return None
            metrics = row.get("metrics") or {}
            if not isinstance(metrics, dict):
                return None
            last_price = self._to_float(metrics.get("last_price"))
            pct_change = self._to_float(metrics.get("pct_change"))
            avg_amount = self._to_float(metrics.get("avg_amount_20d"))
            if last_price <= 0 or avg_amount <= 0:
                return None
            prev_close = last_price / (1.0 + pct_change / 100.0) if abs(pct_change) < 99 else last_price
            if prev_close <= 0:
                prev_close = last_price
            volume = avg_amount / max(last_price, 0.01)
            return UniverseQuote(
                symbol=symbol,
                market=str(row.get("market") or infer_market(symbol)),
                name=str(row.get("name") or symbol),
                last_price=last_price,
                pct_change=pct_change,
                volume=volume,
                amount=avg_amount,
                open_price=last_price,
                high_price=last_price,
                low_price=last_price,
                prev_close=prev_close,
                data_source="tradeforagents_recent_candidates",
            )
        except Exception:
            return None

    def _candidate_report_quotes(self, limit: int = 200) -> List[UniverseQuote]:
        quotes: Dict[str, UniverseQuote] = {}
        report_dir = self.config.reports_dir
        if not report_dir.exists():
            return []
        for candidate_path in sorted(report_dir.glob("auto_candidates_*.json"), reverse=True)[:3]:
            try:
                payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for row in payload.get("selected") or []:
                if not isinstance(row, dict):
                    continue
                quote = self._local_quote_from_auto_candidate(row)
                if quote is None:
                    continue
                current = quotes.get(quote.symbol)
                if current is None or quote.amount > current.amount:
                    quotes[quote.symbol] = quote
        return sorted(quotes.values(), key=lambda item: item.amount, reverse=True)[:limit]

    def _fetch_universe_quotes_akshare(self, limit: int) -> UniverseFetchResult:
        if ak is None:
            raise RuntimeError("AKShare is not installed in the current interpreter")

        frame = ak.stock_zh_a_spot_em()
        quotes: List[UniverseQuote] = []
        for _, row in frame.iterrows():
            symbol = str(row.get("代码") or "").strip()
            if not symbol or len(symbol) != 6:
                continue
            quotes.append(
                UniverseQuote(
                    symbol=symbol,
                    market=infer_market(symbol),
                    name=str(row.get("名称") or symbol),
                    last_price=self._to_float(row.get("最新价")),
                    pct_change=self._to_float(row.get("涨跌幅")),
                    volume=self._to_float(row.get("成交量")),
                    amount=self._to_float(row.get("成交额")),
                    open_price=self._to_float(row.get("今开")),
                    high_price=self._to_float(row.get("最高")),
                    low_price=self._to_float(row.get("最低")),
                    prev_close=self._to_float(row.get("昨收")),
                    data_source="akshare_spot_em",
                )
            )

        quotes = [item for item in quotes if item.amount > 0 and item.last_price > 0]
        quotes.sort(key=lambda item: item.amount, reverse=True)
        return UniverseFetchResult(
            quotes=quotes[:limit],
            source="akshare_spot_em",
            cache_path=None,
            warnings=[],
        )

    def _fetch_daily_bars_akshare(self, symbol: str, limit: int) -> Tuple[List[UniverseBar], str]:
        if ak is None:
            raise RuntimeError("AKShare is not installed in the current interpreter")

        frame = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date="20180101",
            end_date="20500101",
            adjust="",
        )
        bars: List[UniverseBar] = []
        for _, row in frame.iterrows():
            trade_date = str(row.get("日期") or "").strip()
            if not trade_date:
                continue
            bars.append(
                UniverseBar(
                    trade_date=trade_date,
                    open_price=self._to_float(row.get("开盘")),
                    high_price=self._to_float(row.get("最高")),
                    low_price=self._to_float(row.get("最低")),
                    close_price=self._to_float(row.get("收盘")),
                    volume=self._to_float(row.get("成交量")),
                    amount=self._to_float(row.get("成交额")),
                )
            )
        if not bars:
            raise RuntimeError("AKShare returned no daily bars for {0}".format(symbol))
        return bars[-limit:], "akshare_hist_em"

    def _default_enhancements(self, symbols: List[str]) -> Dict[str, CandidateEnhancement]:
        return {symbol: CandidateEnhancement(symbol=symbol) for symbol in symbols}

    @staticmethod
    def _market_for_akshare(symbol: str) -> str:
        market = infer_market(symbol)
        if market == "SH":
            return "sh"
        if market == "SZ":
            return "sz"
        return "bj"

    @staticmethod
    def _quarter_end_candidates(trade_date: str, count: int = 6) -> List[str]:
        current = datetime.strptime(trade_date, "%Y-%m-%d").date().replace(day=1)
        quarter_ends: List[str] = []
        while len(quarter_ends) < count:
            if current.month <= 3:
                quarter_end = date(current.year - 1, 12, 31)
            elif current.month <= 6:
                quarter_end = date(current.year, 3, 31)
            elif current.month <= 9:
                quarter_end = date(current.year, 6, 30)
            else:
                quarter_end = date(current.year, 9, 30)
            value = quarter_end.strftime("%Y%m%d")
            if value not in quarter_ends:
                quarter_ends.append(value)
            current = (quarter_end.replace(day=1) - timedelta(days=1)).replace(day=1)
        return quarter_ends

    @staticmethod
    def _recent_date_strings(trade_date: str, days: int) -> List[str]:
        anchor = datetime.strptime(trade_date, "%Y-%m-%d").date()
        return [(anchor - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days)]

    def _fetch_fund_flow_rank_5d(self, trade_date: str, force_refresh: bool = False) -> Dict[str, Dict[str, object]]:
        cache_path = self._cache_file("ak_fundflow", trade_date)
        cached = self._load_cached_json(cache_path, force_refresh=force_refresh)
        if cached is not None:
            return cached.get("items", {})  # type: ignore[return-value]

        frame = ak.stock_individual_fund_flow_rank(indicator="5日")
        items: Dict[str, Dict[str, object]] = {}
        for _, row in frame.iterrows():
            symbol = str(row.get("代码") or "").strip()
            if not symbol:
                continue
            items[symbol] = {
                "fund_flow_rank_5d": int(self._to_float(row.get("序号"))),
                "fund_flow_main_net_inflow_5d": self._to_float(row.get("5日主力净流入-净额")),
                "fund_flow_main_net_pct_5d": self._to_float(row.get("5日主力净流入-净占比")),
            }

        payload = {"trade_date": trade_date, "items": items}
        self._write_cached_json(cache_path, payload)
        return items

    def _fetch_notice_snapshot(
        self,
        symbols: List[str],
        trade_date: str,
        force_refresh: bool = False,
    ) -> Dict[str, Dict[str, object]]:
        cache_path = self._cache_file("ak_notice", trade_date)
        cached = self._load_cached_json(cache_path, force_refresh=force_refresh)
        if cached is not None:
            return cached.get("items", {})  # type: ignore[return-value]

        target_symbols = set(symbols)
        items: Dict[str, Dict[str, object]] = {symbol: {} for symbol in symbols}
        for notice_date in self._recent_date_strings(trade_date, days=3):
            try:
                frame = ak.stock_notice_report(symbol="全部", date=notice_date)
            except Exception:
                continue
            if frame.empty:
                continue
            for _, row in frame.iterrows():
                symbol = str(row.get("代码") or "").strip()
                if symbol not in target_symbols:
                    continue
                current = items.setdefault(symbol, {})
                current["notice_count_3d"] = int(current.get("notice_count_3d", 0)) + 1
                current_date = str(row.get("公告日期") or "")
                latest_date = str(current.get("latest_notice_date") or "")
                if current_date and current_date > latest_date:
                    current["latest_notice_date"] = current_date

        for notice_date in self._recent_date_strings(trade_date, days=14):
            try:
                frame = ak.stock_notice_report(symbol="风险提示", date=notice_date)
            except Exception:
                continue
            if frame.empty:
                continue
            for _, row in frame.iterrows():
                symbol = str(row.get("代码") or "").strip()
                if symbol not in target_symbols:
                    continue
                current = items.setdefault(symbol, {})
                current["risk_notice_count_14d"] = int(current.get("risk_notice_count_14d", 0)) + 1
                current_date = str(row.get("公告日期") or "")
                latest_date = str(current.get("latest_notice_date") or "")
                if current_date and current_date > latest_date:
                    current["latest_notice_date"] = current_date

        payload = {"trade_date": trade_date, "items": items}
        self._write_cached_json(cache_path, payload)
        return items

    def _fetch_finance_snapshot(
        self,
        symbols: List[str],
        trade_date: str,
        force_refresh: bool = False,
    ) -> Dict[str, Dict[str, object]]:
        cache_path = self._cache_file("ak_finance", trade_date)
        cached = self._load_cached_json(cache_path, force_refresh=force_refresh)
        if cached is not None:
            return cached.get("items", {})  # type: ignore[return-value]

        remaining = set(symbols)
        items: Dict[str, Dict[str, object]] = {}
        for report_date in self._quarter_end_candidates(trade_date, count=6):
            if not remaining:
                break
            frame = ak.stock_yjbb_em(date=report_date)
            if frame.empty:
                continue
            for _, row in frame.iterrows():
                symbol = str(row.get("股票代码") or "").strip()
                if symbol not in remaining:
                    continue
                items[symbol] = {
                    "industry_name": str(row.get("所处行业") or "").strip(),
                    "revenue_yoy": self._to_float(row.get("营业收入-同比增长")),
                    "net_profit_yoy": self._to_float(row.get("净利润-同比增长")),
                    "roe": self._to_float(row.get("净资产收益率")),
                    "finance_report_date": str(row.get("公告日期") or report_date),
                }
                remaining.remove(symbol)

        payload = {"trade_date": trade_date, "items": items}
        self._write_cached_json(cache_path, payload)
        return items

    def _fetch_industry_snapshot(
        self,
        symbols: List[str],
        trade_date: str,
        force_refresh: bool = False,
    ) -> Dict[str, str]:
        items: Dict[str, str] = {}
        for symbol in symbols:
            cache_path = self._cache_file("ak_industry", "{0}_{1}".format(trade_date, symbol))
            cached = self._load_cached_json(cache_path, force_refresh=force_refresh)
            if cached is not None:
                items[symbol] = str(cached.get("industry_name") or "")
                continue

            frame = ak.stock_individual_info_em(symbol=symbol, timeout=float(self.timeout))
            industry_name = ""
            for _, row in frame.iterrows():
                if str(row.get("item") or "").strip() == "行业":
                    industry_name = str(row.get("value") or "").strip()
                    break
            items[symbol] = industry_name
            self._write_cached_json(
                cache_path,
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "industry_name": industry_name,
                },
            )
        return items

    def fetch_candidate_enhancements(
        self,
        symbols: List[str],
        trade_date: Optional[str] = None,
        force_refresh: bool = False,
    ) -> EnhancementFetchResult:
        clean_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
        items = self._default_enhancements(clean_symbols)
        warnings: List[str] = []
        if not clean_symbols:
            return EnhancementFetchResult(items=items, warnings=warnings)
        if ak is None:
            warnings.append("当前解释器未安装 AKShare，已跳过资金流/公告/财报/行业增强。")
            return EnhancementFetchResult(items=items, warnings=warnings)

        target_date = trade_date or date.today().isoformat()
        try:
            fund_map = self._fetch_fund_flow_rank_5d(target_date, force_refresh=force_refresh)
            for symbol in clean_symbols:
                fund_row = fund_map.get(symbol)
                if not fund_row:
                    continue
                item = items[symbol]
                item.fund_flow_rank_5d = int(fund_row.get("fund_flow_rank_5d", 0) or 0)
                item.fund_flow_main_net_inflow_5d = self._to_float(fund_row.get("fund_flow_main_net_inflow_5d"))
                item.fund_flow_main_net_pct_5d = self._to_float(fund_row.get("fund_flow_main_net_pct_5d"))
                item.data_sources.append("akshare_fund_flow_rank")
        except Exception as exc:
            warnings.append("资金流增强失败，已忽略该维度: {0}".format(exc))

        try:
            notice_map = self._fetch_notice_snapshot(clean_symbols, target_date, force_refresh=force_refresh)
            for symbol in clean_symbols:
                notice_row = notice_map.get(symbol) or {}
                item = items[symbol]
                item.notice_count_3d = int(notice_row.get("notice_count_3d", 0) or 0)
                item.risk_notice_count_14d = int(notice_row.get("risk_notice_count_14d", 0) or 0)
                item.latest_notice_date = str(notice_row.get("latest_notice_date") or "")
                if item.notice_count_3d or item.risk_notice_count_14d or item.latest_notice_date:
                    item.data_sources.append("akshare_notice_report")
        except Exception as exc:
            warnings.append("公告增强失败，已忽略该维度: {0}".format(exc))

        try:
            finance_map = self._fetch_finance_snapshot(clean_symbols, target_date, force_refresh=force_refresh)
            for symbol in clean_symbols:
                finance_row = finance_map.get(symbol) or {}
                item = items[symbol]
                item.finance_report_date = str(finance_row.get("finance_report_date") or "")
                item.revenue_yoy = self._to_float(finance_row.get("revenue_yoy"))
                item.net_profit_yoy = self._to_float(finance_row.get("net_profit_yoy"))
                item.roe = self._to_float(finance_row.get("roe"))
                if not item.industry_name:
                    item.industry_name = str(finance_row.get("industry_name") or "")
                if item.finance_report_date or item.revenue_yoy or item.net_profit_yoy or item.roe:
                    item.data_sources.append("akshare_yjbb_em")
        except Exception as exc:
            warnings.append("财报增强失败，已忽略该维度: {0}".format(exc))

        missing_industry = [symbol for symbol, item in items.items() if not item.industry_name]
        if missing_industry:
            try:
                industry_map = self._fetch_industry_snapshot(
                    missing_industry,
                    target_date,
                    force_refresh=force_refresh,
                )
                for symbol in missing_industry:
                    industry_name = industry_map.get(symbol, "")
                    if industry_name:
                        items[symbol].industry_name = industry_name
                        items[symbol].data_sources.append("akshare_individual_info")
            except Exception as exc:
                warnings.append("行业增强失败，已忽略该维度: {0}".format(exc))

        for item in items.values():
            item.data_sources = sorted(set(item.data_sources))
        return EnhancementFetchResult(items=items, warnings=warnings)

    def load_local_result_universe(self, limit: int = 200) -> UniverseFetchResult:
        latest_snapshots: Dict[str, Path] = {}
        for snapshot_path in self.config.tradeforagents_results_dir.glob("*/**/reports/market_snapshot.json"):
            ticker = snapshot_path.parents[2].name
            current = latest_snapshots.get(ticker)
            if current is None or str(snapshot_path) > str(current):
                latest_snapshots[ticker] = snapshot_path

        quotes_by_symbol: Dict[str, UniverseQuote] = {}
        for ticker, snapshot_path in latest_snapshots.items():
            quote = self._local_quote_from_snapshot(snapshot_path)
            if quote is not None:
                quotes_by_symbol[ticker] = quote

        for quote in self._candidate_report_quotes(limit=max(limit, 60)):
            quotes_by_symbol.setdefault(quote.symbol, quote)

        quotes = list(quotes_by_symbol.values())
        quotes.sort(key=lambda item: item.amount, reverse=True)
        warnings = [
            "已切换到本地候选池，结果仍可继续分析。",
        ]
        if any(item.data_source == "tradeforagents_recent_candidates" for item in quotes):
            warnings.append("本地候选池已补入最近自动选股结果，可覆盖更多近期活跃标的。")
        else:
            warnings.append("当前主要使用本地已有分析结果，覆盖范围有限。")
        return UniverseFetchResult(
            quotes=quotes[:limit],
            source="tradeforagents_local",
            cache_path=None,
            warnings=warnings,
        )

    def fetch_universe_quotes(self, limit: int = 300, force_refresh: bool = False) -> UniverseFetchResult:
        warnings: List[str] = []
        if ak is not None:
            try:
                return self._fetch_universe_quotes_akshare(limit=limit)
            except Exception as exc:
                warnings.append("AKShare 股票池抓取失败，已回退东财接口: {0}".format(exc))

        trade_date = date.today().isoformat()
        cache_path = self._cache_file("universe", "{0}_{1}".format(trade_date, limit))
        params = {
            "pn": 1,
            "pz": limit,
            "po": 1,
            "np": 1,
            "ut": EASTMONEY_UT,
            "fltt": 2,
            "invt": 2,
            "fid": "f6",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23",
            "fields": "f12,f14,f2,f3,f5,f6,f15,f16,f17,f18",
        }

        try:
            payload = self._request_json(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params=params,
                cache_path=cache_path,
                force_refresh=force_refresh,
            )
        except Exception as exc:
            local_result = self.load_local_result_universe(limit=limit)
            local_result.warnings = warnings + local_result.warnings
            message = "东财股票池暂不可用，已退回本地候选池: {0}".format(exc)
            if os.name == "nt" and "10013" in str(exc):
                message = "Windows 当前网络未放行东财抓取，已自动退回本地候选池: {0}".format(exc)
            local_result.warnings.insert(0, message)
            return local_result

        data = payload.get("data") or {}
        rows = data.get("diff") or []
        quotes: List[UniverseQuote] = []
        for row in rows:
            symbol = str(row.get("f12") or "").strip()
            if not symbol:
                continue
            try:
                quotes.append(
                    UniverseQuote(
                        symbol=symbol,
                        market=infer_market(symbol),
                        name=str(row.get("f14") or symbol),
                        last_price=float(row.get("f2") or 0.0),
                        pct_change=float(row.get("f3") or 0.0),
                        volume=float(row.get("f5") or 0.0),
                        amount=float(row.get("f6") or 0.0),
                        high_price=float(row.get("f15") or 0.0),
                        low_price=float(row.get("f16") or 0.0),
                        open_price=float(row.get("f17") or 0.0),
                        prev_close=float(row.get("f18") or 0.0),
                        data_source="eastmoney_live",
                    )
                )
            except (TypeError, ValueError):
                continue

        return UniverseFetchResult(quotes=quotes, source="eastmoney_live", cache_path=cache_path, warnings=warnings)

    def fetch_daily_bars(
        self,
        symbol: str,
        market: Optional[str] = None,
        limit: int = 120,
        force_refresh: bool = False,
    ) -> Tuple[List[UniverseBar], str]:
        if ak is not None:
            try:
                return self._fetch_daily_bars_akshare(symbol=symbol, limit=limit)
            except Exception:
                pass

        cache_path = self._cache_file("bars", "{0}_{1}_{2}".format(date.today().isoformat(), symbol, limit))
        params = {
            "secid": secid_for_symbol(symbol, market),
            "ut": EASTMONEY_UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": 101,
            "fqt": 1,
            "lmt": limit,
            "end": "20500101",
        }

        try:
            payload = self._request_json(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params=params,
                cache_path=cache_path,
                force_refresh=force_refresh,
            )
            data = payload.get("data") or {}
            klines = data.get("klines") or []
            bars = []
            for line in klines:
                parts = str(line).split(",")
                if len(parts) < 7:
                    continue
                bars.append(
                    UniverseBar(
                        trade_date=parts[0],
                        open_price=float(parts[1]),
                        close_price=float(parts[2]),
                        high_price=float(parts[3]),
                        low_price=float(parts[4]),
                        volume=float(parts[5]),
                        amount=float(parts[6]),
                    )
                )
            if bars:
                return bars, "eastmoney_live"
        except Exception:
            pass

        local_bars = [
            UniverseBar(
                trade_date=bar.trade_date,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                amount=bar.close_price * bar.volume,
            )
            for bar in self.result_bar_store.load_daily_bars(symbol)
        ]
        return local_bars[-limit:], "tradeforagents_local"

    def save_universe_snapshot(self, payload: UniverseFetchResult, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            "source": payload.source,
            "warnings": payload.warnings,
            "quotes": [asdict(row) for row in payload.quotes],
        }
        target_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        return target_path
