from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Sequence


@dataclass
class MetricResult:
    name: str
    value: float
    sample_size: int = 0
    valid: bool = True
    details: dict[str, float | int | str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float | int | str | bool | dict[str, float | int | str]]:
        return asdict(self)


def _to_float_list(values: Iterable[float]) -> List[float]:
    result: List[float] = []
    for value in values:
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            continue
    return result


def calc_total_return(start_equity: float, end_equity: float) -> MetricResult:
    start_value = float(start_equity or 0.0)
    end_value = float(end_equity or 0.0)
    if start_value <= 0:
        return MetricResult(name="total_return", value=0.0, valid=False, details={"start_equity": start_value, "end_equity": end_value})
    return MetricResult(
        name="total_return",
        value=(end_value - start_value) / start_value,
        sample_size=1,
        details={"start_equity": start_value, "end_equity": end_value},
    )


def calc_win_rate(trade_pnls: Iterable[float]) -> MetricResult:
    pnl_list = _to_float_list(trade_pnls)
    total = len(pnl_list)
    if total == 0:
        return MetricResult(name="win_rate", value=0.0, sample_size=0, valid=False)
    wins = sum(1 for pnl in pnl_list if pnl > 0)
    return MetricResult(name="win_rate", value=wins / total, sample_size=total, details={"wins": wins, "losses": total - wins})


def calc_profit_loss_ratio(trade_pnls: Iterable[float]) -> MetricResult:
    pnl_list = _to_float_list(trade_pnls)
    wins = [pnl for pnl in pnl_list if pnl > 0]
    losses = [abs(pnl) for pnl in pnl_list if pnl < 0]
    if not wins or not losses:
        return MetricResult(
            name="profit_loss_ratio",
            value=0.0 if not wins else float("inf"),
            sample_size=len(pnl_list),
            valid=bool(wins and losses),
            details={"avg_win": sum(wins) / len(wins) if wins else 0.0, "avg_loss": sum(losses) / len(losses) if losses else 0.0},
        )
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    return MetricResult(
        name="profit_loss_ratio",
        value=avg_win / avg_loss if avg_loss > 0 else float("inf"),
        sample_size=len(pnl_list),
        details={"avg_win": avg_win, "avg_loss": avg_loss},
    )


def calc_profit_factor(trade_pnls: Iterable[float]) -> MetricResult:
    pnl_list = _to_float_list(trade_pnls)
    gross_profit = sum(pnl for pnl in pnl_list if pnl > 0)
    gross_loss = sum(abs(pnl) for pnl in pnl_list if pnl < 0)
    if gross_loss <= 0:
        return MetricResult(
            name="profit_factor",
            value=0.0 if gross_profit <= 0 else float("inf"),
            sample_size=len(pnl_list),
            valid=gross_profit > 0,
            details={"gross_profit": gross_profit, "gross_loss": gross_loss},
        )
    return MetricResult(
        name="profit_factor",
        value=gross_profit / gross_loss,
        sample_size=len(pnl_list),
        details={"gross_profit": gross_profit, "gross_loss": gross_loss},
    )


def calc_expectancy(trade_pnls: Iterable[float]) -> MetricResult:
    pnl_list = _to_float_list(trade_pnls)
    total = len(pnl_list)
    if total == 0:
        return MetricResult(name="expectancy", value=0.0, sample_size=0, valid=False)
    wins = [pnl for pnl in pnl_list if pnl > 0]
    losses = [abs(pnl) for pnl in pnl_list if pnl < 0]
    win_rate_result = calc_win_rate(pnl_list)
    win_rate = win_rate_result.value
    loss_rate = max(0.0, 1.0 - win_rate)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win - loss_rate * avg_loss
    return MetricResult(
        name="expectancy",
        value=expectancy,
        sample_size=total,
        details={"win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss},
    )


def calc_max_drawdown(equity_curve: Sequence[float]) -> MetricResult:
    curve = _to_float_list(equity_curve)
    if not curve:
        return MetricResult(name="max_drawdown", value=0.0, sample_size=0, valid=False)
    peak = curve[0]
    max_drawdown = 0.0
    current_drawdown = 0.0
    for equity in curve:
        peak = max(peak, equity)
        if peak <= 0:
            continue
        current_drawdown = max(0.0, (peak - equity) / peak)
        max_drawdown = max(max_drawdown, current_drawdown)
    return MetricResult(
        name="max_drawdown",
        value=max_drawdown,
        sample_size=len(curve),
        details={"current_drawdown": current_drawdown, "peak": peak},
    )


def calc_return_drawdown_ratio(total_return: float, max_drawdown: float) -> MetricResult:
    total_return_value = float(total_return or 0.0)
    drawdown_value = float(max_drawdown or 0.0)
    if drawdown_value <= 0:
        return MetricResult(
            name="return_drawdown_ratio",
            value=0.0 if total_return_value <= 0 else float("inf"),
            sample_size=1,
            valid=total_return_value > 0,
            details={"total_return": total_return_value, "max_drawdown": drawdown_value},
        )
    return MetricResult(
        name="return_drawdown_ratio",
        value=total_return_value / drawdown_value,
        sample_size=1,
        details={"total_return": total_return_value, "max_drawdown": drawdown_value},
    )


def calc_longest_win_streak(trade_pnls: Iterable[float]) -> MetricResult:
    pnl_list = _to_float_list(trade_pnls)
    longest = 0
    current = 0
    for pnl in pnl_list:
        if pnl > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return MetricResult(name="longest_win_streak", value=float(longest), sample_size=len(pnl_list), details={"streak": longest})


def calc_longest_loss_streak(trade_pnls: Iterable[float]) -> MetricResult:
    pnl_list = _to_float_list(trade_pnls)
    longest = 0
    current = 0
    for pnl in pnl_list:
        if pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return MetricResult(name="longest_loss_streak", value=float(longest), sample_size=len(pnl_list), details={"streak": longest})


def calc_monthly_positive_ratio(monthly_returns: Iterable[float]) -> MetricResult:
    values = _to_float_list(monthly_returns)
    if not values:
        return MetricResult(name="monthly_positive_ratio", value=0.0, sample_size=0, valid=False)
    positive = sum(1 for value in values if value > 0)
    return MetricResult(
        name="monthly_positive_ratio",
        value=positive / len(values),
        sample_size=len(values),
        details={"positive_months": positive, "negative_months": len(values) - positive},
    )
