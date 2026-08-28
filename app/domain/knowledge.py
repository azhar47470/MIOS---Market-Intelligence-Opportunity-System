from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from app.domain.common import DomainModel, utc_now


class KnowledgeCategory(StrEnum):
    MACRO_HISTORY = "macro_history"
    HISTORICAL_CASES = "historical_cases"
    RELATIONSHIPS = "relationships"
    RESEARCH_NOTES = "research_notes"
    MARKET_MEMORY = "market_memory"


class KnowledgeRecord(DomainModel):
    record_id: str = Field(min_length=1, max_length=160)
    category: KnowledgeCategory
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=10_000)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    source: str = Field(default="MIOS", min_length=1, max_length=160)
    confidence: int = Field(default=75, ge=0, le=100)
    related_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("knowledge timestamps must be timezone-aware")
        return value


class RelationshipRecord(DomainModel):
    relationship_id: str = Field(min_length=1, max_length=160)
    from_entity: str = Field(min_length=1, max_length=160)
    relation: str = Field(min_length=1, max_length=120)
    to_entity: str = Field(min_length=1, max_length=160)
    strength: int = Field(ge=0, le=100)
    evidence_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("relationship timestamps must be timezone-aware")
        return value
