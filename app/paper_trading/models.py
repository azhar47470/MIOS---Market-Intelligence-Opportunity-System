from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.domain.common import DomainModel
from app.domain.enums import Recommendation


class PaperPosition(DomainModel):
    position_id: str = Field(min_length=1, max_length=120)
    opened_recommendation_id: str = Field(min_length=1, max_length=120)
    entry_price: Decimal = Field(gt=Decimal("0"))
    entry_recommendation: Recommendation
    opened_at: datetime
    narratives: tuple[str, ...] = Field(default_factory=tuple)
    closed_recommendation_id: str | None = Field(default=None, max_length=120)
    exit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    exit_recommendation: Recommendation | None = None
    closed_at: datetime | None = None

    @field_validator("opened_at", "closed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("paper position timestamps must be timezone-aware")
        return value

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        return current_price - self.entry_price

    @property
    def realized_pnl(self) -> Decimal | None:
        if self.exit_price is None:
            return None
        return self.exit_price - self.entry_price


class PaperTradingState(DomainModel):
    open_position: PaperPosition | None = None
    closed_positions: tuple[PaperPosition, ...] = Field(default_factory=tuple)
    last_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    last_updated_at: datetime | None = None

    @field_validator("last_updated_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("paper trading timestamp must be timezone-aware")
        return value
