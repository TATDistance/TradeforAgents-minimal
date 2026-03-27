from __future__ import annotations

from app.models import AIDecision, StrategySignal
from app.settings import load_settings
from app.signal_fusion import SignalFusion


class FakeAIService:
    def review_signal(self, symbol, candidate, trade_date=None):
        return AIDecision(symbol=symbol, ai_action="BUY", confidence=0.8, risk_score=0.3, approved=True, reason="同意")


def test_signal_fusion_requires_two_signals():
    fusion = SignalFusion(load_settings(), ai_service=FakeAIService())
    grouped = {
        "600036": [
            StrategySignal(symbol="600036", strategy="momentum", action="BUY", score=0.7, signal_price=40.0, position_pct=0.1, reason="a"),
            StrategySignal(symbol="600036", strategy="breakout", action="BUY", score=0.75, signal_price=40.1, position_pct=0.12, reason="b"),
        ]
    }
    final_signals, decisions = fusion.fuse(grouped)
    assert len(decisions) == 1
    assert len(final_signals) == 1
