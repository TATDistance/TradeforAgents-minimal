from __future__ import annotations

import math

from app.metrics_service import (
    calc_expectancy,
    calc_longest_loss_streak,
    calc_longest_win_streak,
    calc_max_drawdown,
    calc_monthly_positive_ratio,
    calc_profit_factor,
    calc_profit_loss_ratio,
    calc_return_drawdown_ratio,
    calc_total_return,
    calc_win_rate,
)


def test_calc_win_rate_handles_empty():
    result = calc_win_rate([])
    assert result.valid is False
    assert result.value == 0.0


def test_calc_profit_metrics_with_mixed_trades():
    trades = [100.0, -50.0, 60.0, -20.0]
    win_rate = calc_win_rate(trades)
    pnl_ratio = calc_profit_loss_ratio(trades)
    profit_factor = calc_profit_factor(trades)
    expectancy = calc_expectancy(trades)

    assert round(win_rate.value, 4) == 0.5
    assert round(pnl_ratio.value, 4) == round(((100.0 + 60.0) / 2) / ((50.0 + 20.0) / 2), 4)
    assert round(profit_factor.value, 4) == round((100.0 + 60.0) / (50.0 + 20.0), 4)
    assert round(expectancy.value, 4) == 22.5


def test_calc_profit_factor_all_wins_is_infinite():
    result = calc_profit_factor([20.0, 30.0])
    assert math.isinf(result.value)


def test_calc_total_return_and_drawdown():
    total_return = calc_total_return(100000.0, 112000.0)
    drawdown = calc_max_drawdown([100000.0, 110000.0, 103000.0, 112000.0])
    ratio = calc_return_drawdown_ratio(total_return.value, drawdown.value)

    assert round(total_return.value, 4) == 0.12
    assert round(drawdown.value, 4) == round((110000.0 - 103000.0) / 110000.0, 4)
    assert ratio.value > 1.0


def test_streak_metrics():
    trades = [10.0, 8.0, -2.0, -5.0, -3.0, 4.0, 6.0]
    win_streak = calc_longest_win_streak(trades)
    loss_streak = calc_longest_loss_streak(trades)

    assert win_streak.value == 2.0
    assert loss_streak.value == 3.0


def test_monthly_positive_ratio():
    result = calc_monthly_positive_ratio([0.03, -0.01, 0.02, 0.0, -0.02])
    assert round(result.value, 4) == 0.4
