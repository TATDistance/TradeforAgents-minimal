from __future__ import annotations

from app.score_service import ScoreService
from app.settings import load_settings


def test_score_service_separates_setup_and_execution() -> None:
    service = ScoreService(load_settings())
    result = service.compute_scores(
        symbol="300750",
        feature_score=0.48,
        dominant_direction="LONG",
        ai_score=0.10,
        market_risk_penalty=0.04,
        portfolio_risk_penalty=0.02,
        phase_name="MIDDAY_BREAK",
        execution_gate={"can_open_position": False, "can_reduce_position": False, "can_execute_fill": False},
        portfolio_state={"drawdown": 0.01, "total_position_pct": 0.2},
        position_state={"has_position": False},
        risk_mode="NORMAL",
    )

    assert result["setup_score"] > result["execution_score"]
    assert result["phase_penalty"] > 0
    assert result["setup_score"] >= 0.35


def test_score_service_reduce_path_can_turn_negative() -> None:
    service = ScoreService(load_settings())
    result = service.compute_scores(
        symbol="600036",
        feature_score=-0.35,
        dominant_direction="SHORT",
        ai_score=-0.10,
        market_risk_penalty=0.03,
        portfolio_risk_penalty=0.02,
        phase_name="CONTINUOUS_AUCTION_PM",
        execution_gate={"can_open_position": True, "can_reduce_position": True, "can_execute_fill": True},
        portfolio_state={"drawdown": 0.02, "total_position_pct": 0.4},
        position_state={"has_position": True},
        risk_mode="DEFENSIVE",
    )

    assert result["execution_score"] < 0
