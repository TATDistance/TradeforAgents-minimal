from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from .pre_filter_engine import CandidateMetrics


@dataclass
class RankedCandidate:
    symbol: str
    market: str
    name: str
    score: float
    stance: str
    position_hint: float
    reasons: List[str]
    metrics: Dict[str, object]
    data_source: str


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def rank_candidates(metrics_list: List[CandidateMetrics]) -> List[RankedCandidate]:
    ranked: List[RankedCandidate] = []
    for metrics in metrics_list:
        trend_score = 0.0
        reasons = []

        if metrics.last_price >= metrics.ma20:
            trend_score += 20.0
            reasons.append("收盘价站上 20 日线")
        if metrics.ma20 >= metrics.ma60:
            trend_score += 20.0
            reasons.append("20 日线位于 60 日线上方")
        if metrics.ret_20d > 0:
            trend_score += _clamp(metrics.ret_20d * 100.0, 0.0, 20.0)
            reasons.append("20 日动量为正")
        if metrics.ret_5d > -0.03:
            trend_score += 10.0
            reasons.append("近 5 日未明显走坏")
        if 0.02 <= metrics.drawdown_20d <= 0.12:
            trend_score += 15.0
            reasons.append("距 20 日高点有可接受回撤，适合等回踩")
        elif metrics.drawdown_20d < 0.02:
            trend_score += 8.0
            reasons.append("走势强，但不宜追高")
        if metrics.avg_amount_20d >= 100_000_000.0:
            trend_score += 10.0
            reasons.append("流动性充足")
        if metrics.volatility_20d <= 0.03:
            trend_score += 7.0
            reasons.append("20 日波动率可控")
        if metrics.fund_flow_main_net_pct_5d > 0:
            trend_score += _clamp(metrics.fund_flow_main_net_pct_5d * 0.8, 0.0, 10.0)
            reasons.append("5 日主力资金净流入为正")
        elif metrics.fund_flow_main_net_pct_5d < 0:
            trend_score -= _clamp(abs(metrics.fund_flow_main_net_pct_5d) * 0.6, 0.0, 8.0)
            reasons.append("5 日主力资金偏流出")
        if 0 < metrics.fund_flow_rank_5d <= 50:
            trend_score += 6.0
            reasons.append("位于 5 日资金流向前 50")
        if metrics.notice_count_3d > 0:
            trend_score += min(metrics.notice_count_3d, 3) * 1.2
            reasons.append("近 3 日公告较活跃")
        if metrics.risk_notice_count_14d > 0:
            trend_score -= min(metrics.risk_notice_count_14d, 3) * 4.0
            reasons.append("近 14 日存在风险提示公告")
        if metrics.revenue_yoy > 0:
            trend_score += _clamp(metrics.revenue_yoy * 0.08, 0.0, 6.0)
            reasons.append("最新财报营收同比为正")
        if metrics.net_profit_yoy > 0:
            trend_score += _clamp(metrics.net_profit_yoy * 0.08, 0.0, 8.0)
            reasons.append("最新财报净利同比为正")
        elif metrics.net_profit_yoy < 0:
            trend_score -= _clamp(abs(metrics.net_profit_yoy) * 0.04, 0.0, 6.0)
            reasons.append("最新财报净利同比承压")
        if metrics.roe >= 8.0:
            trend_score += _clamp((metrics.roe - 8.0) * 0.6, 0.0, 5.0)
            reasons.append("最新财报 ROE 处于可接受区间")
        if metrics.industry_name:
            reasons.append("所属行业：{0}".format(metrics.industry_name))

        score = round(_clamp(trend_score, 0.0, 100.0), 2)
        if score >= 70:
            stance = "重点观察"
            position_hint = 0.12
        elif score >= 55:
            stance = "候选观察"
            position_hint = 0.08
        else:
            stance = "边缘候选"
            position_hint = 0.05

        ranked.append(
            RankedCandidate(
                symbol=metrics.symbol,
                market=metrics.market,
                name=metrics.name,
                score=score,
                stance=stance,
                position_hint=position_hint,
                reasons=reasons,
                metrics={
                    "last_price": round(metrics.last_price, 3),
                    "pct_change": round(metrics.pct_change, 2),
                    "ma20": round(metrics.ma20, 3),
                    "ma60": round(metrics.ma60, 3),
                    "ret_5d": round(metrics.ret_5d, 4),
                    "ret_20d": round(metrics.ret_20d, 4),
                    "drawdown_20d": round(metrics.drawdown_20d, 4),
                    "volatility_20d": round(metrics.volatility_20d, 4),
                    "avg_amount_20d": round(metrics.avg_amount_20d, 2),
                    "industry_name": metrics.industry_name,
                    "fund_flow_rank_5d": metrics.fund_flow_rank_5d,
                    "fund_flow_main_net_inflow_5d": round(metrics.fund_flow_main_net_inflow_5d, 2),
                    "fund_flow_main_net_pct_5d": round(metrics.fund_flow_main_net_pct_5d, 2),
                    "notice_count_3d": metrics.notice_count_3d,
                    "risk_notice_count_14d": metrics.risk_notice_count_14d,
                    "latest_notice_date": metrics.latest_notice_date,
                    "finance_report_date": metrics.finance_report_date,
                    "revenue_yoy": round(metrics.revenue_yoy, 2),
                    "net_profit_yoy": round(metrics.net_profit_yoy, 2),
                    "roe": round(metrics.roe, 2),
                    "enhancement_source": metrics.enhancement_source,
                },
                data_source=metrics.data_source,
            )
        )

    ranked.sort(key=lambda item: (item.score, item.metrics["avg_amount_20d"]), reverse=True)
    return ranked
