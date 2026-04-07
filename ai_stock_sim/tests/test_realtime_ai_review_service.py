from __future__ import annotations

from app.realtime_ai_review_service import RealtimeAIReviewService
from app.settings import load_settings


def test_realtime_ai_review_service_can_review_holding_without_preexisting_actions(monkeypatch) -> None:
    settings = load_settings()
    settings.ai.realtime_action_review_enabled = False
    settings.ai.realtime_position_review_enabled = True
    service = RealtimeAIReviewService(settings)

    monkeypatch.setattr(service, "_enabled", lambda: True)
    monkeypatch.setattr(service, "_build_client", lambda: object())

    def _fake_review(_client, payload):
        assert payload["candidate_type"] == "holding"
        assert payload["symbol"] == "600036"
        return {
            "final_action": "REDUCE",
            "reduce_pct": 0.4,
            "confidence": 0.81,
            "reason": "持仓已有回撤且结构转弱，先减仓而不直接清仓。",
            "risk_tags": ["weak_execution"],
        }

    monkeypatch.setattr(service, "_call_review_model", _fake_review)

    updated_actions, reviews = service.review_actions(
        [],
        portfolio_feedback={
            "equity": 100000,
            "cash": 25000,
            "cash_pct": 0.25,
            "drawdown": 0.03,
            "risk_mode": "DEFENSIVE",
            "positions_detail": [
                {
                    "symbol": "600036",
                    "qty": 1000,
                    "can_sell_qty": 1000,
                    "avg_cost": 41.2,
                    "last_price": 38.8,
                    "market_value": 38800,
                    "unrealized_pct": -0.058,
                    "hold_days": 6,
                }
            ],
        },
        market_regime={"regime": "RANGE_BOUND", "risk_bias": "DEFENSIVE"},
        phase_state={"phase": "CONTINUOUS_AUCTION_PM"},
        snapshot_rows={"600036": {"latest_price": 38.8, "pct_change": -0.021, "amount": 180000000}},
        decision_contexts={"600036": {"technical_features": {"trend_slope_20d": -0.04, "ma20_bias": -0.03}}},
        trade_date="2026-04-07",
        account_id="paper_main",
    )

    assert len(updated_actions) == 1
    assert updated_actions[0].symbol == "600036"
    assert updated_actions[0].action == "REDUCE"
    assert updated_actions[0].reduce_pct == 0.4
    assert reviews[0]["candidate_type"] == "holding"
    assert reviews[0]["applied"] is True

