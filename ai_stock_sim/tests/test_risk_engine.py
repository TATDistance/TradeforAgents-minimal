from __future__ import annotations

from app.models import FinalSignal, MarketQuote
from app.risk_engine import PortfolioState, RiskEngine
from app.settings import load_settings


def test_risk_engine_rounds_to_board_lot():
    engine = RiskEngine(load_settings())
    signal = FinalSignal(
        symbol="600036",
        action="BUY",
        entry_price=40.0,
        stop_loss=38.0,
        take_profit=44.0,
        position_pct=0.15,
        confidence=0.7,
        source_strategies=["momentum", "breakout"],
        ai_approved=True,
    )
    quote = MarketQuote(
        ts=__import__("datetime").datetime.now(),
        symbol="600036",
        name="招商银行",
        market="SH",
        latest_price=40.0,
        pct_change=0.012,
        open_price=39.5,
        high_price=40.2,
        low_price=39.3,
        prev_close=39.5,
        volume=100000,
        amount=100000000,
        data_source="test",
    )
    portfolio = PortfolioState(
        cash=100000,
        equity=100000,
        market_value=0,
        realized_pnl=0,
        unrealized_pnl=0,
        drawdown=0.01,
        current_positions={},
    )
    result = engine.evaluate(signal, quote, portfolio)
    assert result.allowed is True
    assert result.adjusted_qty % 100 == 0
