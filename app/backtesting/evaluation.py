from decimal import Decimal

from app.domain.enums import Recommendation


def directionally_correct(recommendation: Recommendation, realized_move: Decimal) -> bool:
    if recommendation in {Recommendation.BUY, Recommendation.STRONG_BUY, Recommendation.HOLD}:
        return realized_move >= 0
    if recommendation in {Recommendation.TAKE_PROFIT, Recommendation.STRONG_SELL}:
        return realized_move <= 0
    return True
