from __future__ import annotations

from app.scoring_service import ScoringService


def test_scoring_service_returns_grade():
    service = ScoringService()
    score = service.score_strategy(
        "momentum_plus_ai",
        {
            "total_return": 0.18,
            "monthly_return": 0.04,
            "expectancy": 12.0,
            "max_drawdown": 0.06,
            "current_drawdown": 0.02,
            "monthly_positive_ratio": 0.75,
            "return_volatility": 0.03,
            "longest_loss_streak": 2,
            "pnl_ratio": 1.8,
            "profit_factor": 1.9,
            "signal_hit_rate": 0.62,
            "risk_events": 1,
        },
    )
    assert score.score_total > 0
    assert score.grade in {"A", "B+", "B", "C", "D"}
    assert score.status in {"KEEP_RUNNING", "OBSERVE", "PAUSE", "REVIEW_RISK"}


def test_scoring_service_penalizes_large_drawdown():
    service = ScoringService()
    conservative = service.score_strategy(
        "conservative",
        {"total_return": 0.08, "max_drawdown": 0.03, "monthly_positive_ratio": 0.7, "pnl_ratio": 1.4, "profit_factor": 1.5, "signal_hit_rate": 0.55},
    )
    risky = service.score_strategy(
        "risky",
        {"total_return": 0.10, "max_drawdown": 0.18, "monthly_positive_ratio": 0.7, "pnl_ratio": 1.4, "profit_factor": 1.5, "signal_hit_rate": 0.55},
    )
    assert conservative.score_risk > risky.score_risk
