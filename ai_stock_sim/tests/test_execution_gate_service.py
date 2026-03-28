from __future__ import annotations

from app.execution_gate_service import ExecutionGateService
from app.models import MarketPhaseState
from app.settings import load_settings


def test_gate_allows_fill_in_continuous_auction():
    service = ExecutionGateService(load_settings())
    gate = service.resolve(
        MarketPhaseState(
            is_trading_day=True,
            phase="CONTINUOUS_AUCTION_PM",
            allow_market_update=True,
            allow_signal_generation=True,
            allow_ai_decision=True,
            allow_new_buy=True,
            allow_sell_reduce=True,
            allow_simulate_fill=True,
            trade_date="2026-03-27",
        )
    )
    assert gate.can_execute_fill is True
    assert gate.can_open_position is True


def test_gate_blocks_fill_during_midday_break():
    service = ExecutionGateService(load_settings())
    gate = service.resolve(
        MarketPhaseState(
            is_trading_day=True,
            phase="MIDDAY_BREAK",
            allow_market_update=True,
            allow_signal_generation=True,
            allow_ai_decision=True,
            allow_new_buy=False,
            allow_sell_reduce=False,
            allow_simulate_fill=False,
            trade_date="2026-03-27",
        )
    )
    assert gate.can_execute_fill is False
    assert gate.intent_only_mode is True


def test_gate_blocks_non_trading_day():
    service = ExecutionGateService(load_settings())
    gate = service.resolve(
        MarketPhaseState(
            is_trading_day=False,
            phase="NON_TRADING_DAY",
            allow_market_update=False,
            allow_signal_generation=False,
            allow_ai_decision=False,
            allow_new_buy=False,
            allow_sell_reduce=False,
            allow_simulate_fill=False,
            trade_date="2026-03-28",
        )
    )
    assert gate.can_execute_fill is False
    assert gate.can_generate_signal is False
