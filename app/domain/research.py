from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.domain.common import DomainModel
from app.domain.enums import Recommendation
from app.domain.intelligence import DecisionReport


class BacktestDecisionSample(DomainModel):
    decision: DecisionReport
    entry_price: Decimal = Field(gt=Decimal("0"))
    exit_price: Decimal = Field(gt=Decimal("0"))
    realized_move_usd: Decimal
    was_directionally_correct: bool


class BacktestResult(DomainModel):
    started_at: datetime
    completed_at: datetime
    samples: tuple[BacktestDecisionSample, ...]
    action_count: int = Field(ge=0)
    wait_count: int = Field(ge=0)
    directional_hit_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("100"))

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class PaperValidationResult(DomainModel):
    recommendation_id: str = Field(min_length=1, max_length=120)
    recommendation: Recommendation
    reference_price: Decimal = Field(gt=Decimal("0"))
    current_price: Decimal = Field(gt=Decimal("0"))
    unrealized_move_usd: Decimal
    status: str = Field(min_length=1, max_length=120)
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value
