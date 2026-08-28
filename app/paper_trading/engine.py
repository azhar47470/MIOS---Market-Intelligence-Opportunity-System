from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

from app.backtesting.metrics import hit_rate_from_outcomes
from app.domain.enums import Recommendation
from app.domain.intelligence import DecisionReport
from app.paper_trading.models import PaperPosition, PaperTradingState
from app.paper_trading.repository import PaperTradingRepository

OPEN_RECOMMENDATIONS = {Recommendation.BUY, Recommendation.STRONG_BUY}
CLOSE_RECOMMENDATIONS = {Recommendation.TAKE_PROFIT, Recommendation.STRONG_SELL}


class PaperTradingEngine:
    def __init__(self, repository: PaperTradingRepository) -> None:
        self._repository = repository

    def update(
        self,
        decision: DecisionReport,
        current_price: Decimal,
        narratives: tuple[str, ...] = (),
    ) -> PaperTradingState:
        state = self._repository.load()
        now = datetime.now(UTC)
        if state.open_position is None and decision.recommendation in OPEN_RECOMMENDATIONS:
            state = state.model_copy(
                update={
                    "open_position": PaperPosition(
                        position_id=_position_id(decision.recommendation_id, current_price),
                        opened_recommendation_id=decision.recommendation_id,
                        entry_price=current_price,
                        entry_recommendation=decision.recommendation,
                        opened_at=now,
                        narratives=narratives,
                    )
                }
            )
        elif state.open_position is not None and decision.recommendation in CLOSE_RECOMMENDATIONS:
            closed_position = state.open_position.model_copy(
                update={
                    "closed_recommendation_id": decision.recommendation_id,
                    "exit_price": current_price,
                    "exit_recommendation": decision.recommendation,
                    "closed_at": now,
                }
            )
            state = state.model_copy(
                update={
                    "open_position": None,
                    "closed_positions": (closed_position, *state.closed_positions),
                }
            )
        state = state.model_copy(update={"last_price": current_price, "last_updated_at": now})
        self._repository.save(state)
        return state

    def summary(self) -> dict[str, object]:
        state = self._repository.load()
        closed_pnl = tuple(
            position.realized_pnl
            for position in state.closed_positions
            if position.realized_pnl is not None
        )
        open_pnl = (
            state.open_position.unrealized_pnl(state.last_price)
            if state.open_position is not None and state.last_price is not None
            else Decimal("0")
        )
        return {
            "open_position": (
                state.open_position.model_dump(mode="json")
                if state.open_position is not None
                else None
            ),
            "closed_positions": [
                position.model_dump(mode="json") for position in state.closed_positions
            ],
            "open_unrealized_pnl": str(open_pnl),
            "closed_realized_pnl": str(sum(closed_pnl, Decimal("0"))),
            "hit_rate": str(hit_rate_from_outcomes(tuple(pnl > 0 for pnl in closed_pnl))),
            "by_narrative": _narrative_breakdown(state.closed_positions),
            "last_price": str(state.last_price) if state.last_price is not None else None,
            "last_updated_at": (
                state.last_updated_at.isoformat() if state.last_updated_at is not None else None
            ),
        }


def _narrative_breakdown(
    closed_positions: tuple[PaperPosition, ...],
) -> dict[str, dict[str, str]]:
    per_narrative: dict[str, list[Decimal]] = {}
    for position in closed_positions:
        if position.realized_pnl is None:
            continue
        for name in position.narratives:
            per_narrative.setdefault(name, []).append(position.realized_pnl)
    breakdown: dict[str, dict[str, str]] = {}
    for name, pnls in sorted(per_narrative.items(), key=lambda kv: sum(kv[1]), reverse=True):
        wins = sum(1 for pnl in pnls if pnl > 0)
        breakdown[name] = {
            "trades": str(len(pnls)),
            "win_rate": str(hit_rate_from_outcomes(tuple(pnl > 0 for pnl in pnls))),
            "total_pnl": str(sum(pnls, Decimal("0"))),
        }
    return breakdown


def _position_id(recommendation_id: str, price: Decimal) -> str:
    return sha256(f"{recommendation_id}|{price}".encode()).hexdigest()[:24]
