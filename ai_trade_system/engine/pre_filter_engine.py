from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import List, Optional

from .universe_service import UniverseBar, UniverseQuote


@dataclass
class CandidateMetrics:
    symbol: str
    market: str
    name: str
    last_price: float
    pct_change: float
    amount: float
    volume: float
    ma20: float
    ma60: float
    ret_5d: float
    ret_20d: float
    drawdown_20d: float
    volatility_20d: float
    avg_amount_20d: float
    data_source: str
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
    enhancement_source: str = ""


@dataclass
class FilterResult:
    passed: bool
    reason: str
    metrics: Optional[CandidateMetrics]


def _moving_average(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / float(window)


def _return_ratio(values: List[float], window: int) -> float:
    if len(values) <= window or values[-window - 1] <= 0:
        return 0.0
    return (values[-1] - values[-window - 1]) / values[-window - 1]


def _volatility(values: List[float], window: int) -> float:
    if len(values) <= window:
        return 0.0
    returns = []
    recent = values[-window - 1 :]
    for previous, current in zip(recent, recent[1:]):
        if previous <= 0:
            continue
        returns.append((current - previous) / previous)
    if len(returns) < 2:
        return 0.0
    return pstdev(returns)


def build_metrics(quote: UniverseQuote, bars: List[UniverseBar], bar_source: str) -> Optional[CandidateMetrics]:
    closes = [bar.close_price for bar in bars if bar.close_price > 0]
    amounts = [bar.amount for bar in bars if bar.amount > 0]
    if len(closes) < 60 or len(amounts) < 20:
        return None

    ma20 = _moving_average(closes, 20)
    ma60 = _moving_average(closes, 60)
    if ma20 is None or ma60 is None:
        return None

    recent_high = max(closes[-20:])
    drawdown_20d = 0.0 if recent_high <= 0 else (recent_high - closes[-1]) / recent_high

    return CandidateMetrics(
        symbol=quote.symbol,
        market=quote.market,
        name=quote.name,
        last_price=quote.last_price,
        pct_change=quote.pct_change,
        amount=quote.amount,
        volume=quote.volume,
        ma20=ma20,
        ma60=ma60,
        ret_5d=_return_ratio(closes, 5),
        ret_20d=_return_ratio(closes, 20),
        drawdown_20d=drawdown_20d,
        volatility_20d=_volatility(closes, 20),
        avg_amount_20d=mean(amounts[-20:]),
        data_source=bar_source,
    )


def evaluate_candidate(
    quote: UniverseQuote,
    bars: List[UniverseBar],
    bar_source: str,
    min_amount: float = 50_000_000.0,
) -> FilterResult:
    name = quote.name.upper()
    if "ST" in name or "退" in quote.name:
        return FilterResult(False, "ST/退市风险标的跳过", None)
    if quote.last_price <= 2.0:
        return FilterResult(False, "股价过低，跳过低价股", None)
    if quote.volume <= 0 or quote.amount <= 0:
        return FilterResult(False, "停牌或无成交量", None)
    if quote.amount < min_amount:
        return FilterResult(False, "成交额不足 {0:.0f} 万".format(min_amount / 10000.0), None)
    if abs(quote.pct_change) >= 9.5:
        return FilterResult(False, "接近涨跌停，跳过", None)

    metrics = build_metrics(quote, bars, bar_source)
    if metrics is None:
        return FilterResult(False, "历史日线不足 60 根", None)
    if metrics.avg_amount_20d < min_amount:
        return FilterResult(False, "近 20 日平均成交额不足", metrics)
    if metrics.last_price < metrics.ma60 * 0.92:
        return FilterResult(False, "明显弱于 60 日线，暂不纳入", metrics)

    return FilterResult(True, "通过预筛选", metrics)
