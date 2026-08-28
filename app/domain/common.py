from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class ContractStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    STALE_DATA = "STALE_DATA"
    FAILED = "FAILED"
    NO_DATA = "NO_DATA"
    INVALID_INPUT = "INVALID_INPUT"


class DataQuality(StrEnum):
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class EvidenceStrength(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConfidenceScore(DomainModel):
    value: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=500)
    calibration: str = Field(default="v1.0", min_length=1, max_length=40)


class EvidenceRecord(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    strength: EvidenceStrength
    confidence: int = Field(ge=0, le=100)
    source: str = Field(min_length=1, max_length=120)


class RiskRecord(DomainModel):
    risk: str = Field(min_length=1, max_length=500)
    severity: EvidenceStrength
    probability: int = Field(ge=0, le=100)


class ContractMetadata(DomainModel):
    version: str = Field(default="1.0", min_length=1, max_length=20)
    generated_at: datetime = Field(default_factory=utc_now)
    data_time: datetime | None = None
    expires_at: datetime | None = None
    correlation_id: str | None = Field(default=None, max_length=120)
    trace_id: str | None = Field(default=None, max_length=120)

    @field_validator("generated_at", "data_time", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class ProviderResult[T](DomainModel):
    status: ContractStatus
    provider: str = Field(min_length=1, max_length=80)
    metadata: ContractMetadata = Field(default_factory=ContractMetadata)
    data: T | None = None
    quality: DataQuality = DataQuality.UNKNOWN
    error: str | None = Field(default=None, max_length=1000)
