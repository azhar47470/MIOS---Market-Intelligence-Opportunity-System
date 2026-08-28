from decimal import Decimal

from app.domain.enums import Recommendation
from app.domain.research import BacktestDecisionSample


def directional_hit_rate(samples: tuple[BacktestDecisionSample, ...]) -> Decimal:
    actionable = [
        sample for sample in samples if sample.decision.recommendation != Recommendation.WAIT
    ]
    if not actionable:
        return Decimal("0")
    return hit_rate_from_outcomes(
        tuple(sample.was_directionally_correct for sample in actionable)
    )


def wait_count(samples: tuple[BacktestDecisionSample, ...]) -> int:
    return sum(1 for sample in samples if sample.decision.recommendation == Recommendation.WAIT)


def hit_rate_from_outcomes(outcomes: tuple[bool, ...]) -> Decimal:
    if not outcomes:
        return Decimal("0")
    hits = sum(1 for outcome in outcomes if outcome)
    return Decimal(hits) / Decimal(len(outcomes)) * Decimal("100")
