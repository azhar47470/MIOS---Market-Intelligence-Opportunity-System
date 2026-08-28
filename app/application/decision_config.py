from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.application.platform_config import ConfigModel
from app.domain.intelligence import EngineId, MarketRegime


class DecisionThresholdConfig(ConfigModel):
    minimum_confidence_for_action: int = Field(default=60, ge=0, le=100)
    physical_action_threshold: int = Field(default=85, ge=0, le=100)
    forex_action_threshold: int = Field(default=60, ge=0, le=100)
    forex_high_confidence_threshold: int = Field(default=70, ge=0, le=100)
    etf_action_threshold: int = Field(default=70, ge=0, le=100)
    physical_minimum_opportunity_score: int = Field(default=75, ge=0, le=100)
    physical_minimum_investment_score: int = Field(default=70, ge=0, le=100)
    forex_minimum_opportunity_score: int = Field(default=60, ge=0, le=100)
    forex_minimum_investment_score: int = Field(default=60, ge=0, le=100)
    etf_minimum_opportunity_score: int = Field(default=70, ge=0, le=100)
    etf_minimum_investment_score: int = Field(default=65, ge=0, le=100)
    minimum_expected_move_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    physical_minimum_expected_move_usd: Decimal = Field(default=Decimal("50"), ge=Decimal("0"))
    forex_minimum_expected_move_usd: Decimal = Field(default=Decimal("10"), ge=Decimal("0"))
    etf_minimum_expected_move_usd: Decimal = Field(default=Decimal("40"), ge=Decimal("0"))
    max_high_severity_risks_for_action: int = Field(default=1, ge=0, le=10)
    stale_candle_threshold_minutes: int = Field(default=120, ge=1)


class DecisionWeightsConfig(ConfigModel):
    base_weights: dict[EngineId, Decimal] = Field(
        default_factory=lambda: {
            EngineId.TECHNICAL: Decimal("0.25"),
            EngineId.FUNDAMENTAL: Decimal("0.25"),
            EngineId.MARKET_REGIME: Decimal("0.15"),
            EngineId.INSTITUTIONAL: Decimal("0.15"),
            EngineId.GEOPOLITICAL: Decimal("0.10"),
            EngineId.NEWS: Decimal("0.10"),
        }
    )
    regime_overrides: dict[MarketRegime, dict[EngineId, Decimal]] = Field(default_factory=dict)

    @field_validator("base_weights")
    @classmethod
    def require_supported_engines(cls, value: dict[EngineId, Decimal]) -> dict[EngineId, Decimal]:
        required = {
            EngineId.TECHNICAL,
            EngineId.FUNDAMENTAL,
            EngineId.MARKET_REGIME,
            EngineId.INSTITUTIONAL,
            EngineId.GEOPOLITICAL,
            EngineId.NEWS,
        }
        missing = required - set(value)
        if missing:
            labels = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"missing base weights for: {labels}")
        return value

    @model_validator(mode="after")
    def validate_weight_sum(self) -> "DecisionWeightsConfig":
        total = sum(self.base_weights.values(), Decimal("0"))
        if total != Decimal("1.00") and total != Decimal("1"):
            raise ValueError("base weights must sum to 1.0")
        return self


class DecisionEngineConfig(ConfigModel):
    thresholds: DecisionThresholdConfig = Field(default_factory=DecisionThresholdConfig)
    weights: DecisionWeightsConfig = Field(default_factory=DecisionWeightsConfig)
