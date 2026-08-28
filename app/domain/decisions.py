"""Canonical market outlook and mode-specific decision views.

Port of the mios_v2 UnifiedDecision + adapters architecture onto the GIP domain.
The UnifiedDecision is the single canonical outlook downstream consumers reason
about; the adapters re-express that same outlook for different users (a forex
trading signal, a physical-gold investor recommendation, an ETF investor
recommendation). Adapters are pure presentation — they never alter the
intelligence, only its rendering.
"""

from datetime import datetime

from pydantic import Field

from app.domain.ai import CommitteeVoteSnapshot
from app.domain.common import DomainModel, utc_now
from app.domain.intelligence import DirectionalBias


class UnifiedDecision(DomainModel):
    market_bias: DirectionalBias
    confidence: int = Field(ge=0, le=100)
    risk: str = Field(default="low", min_length=1, max_length=10)
    horizon_days: int = Field(default=14, ge=1)
    horizon_label: str = Field(default="1-2 weeks", min_length=1, max_length=40)
    narratives: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    committee_votes: tuple[CommitteeVoteSnapshot, ...] = Field(
        default_factory=tuple, max_length=8
    )
    engine_signals: dict[str, str] = Field(default_factory=dict)
    reasoning: str = Field(min_length=1, max_length=2500)
    timestamp: datetime = Field(default_factory=utc_now)


class ForexDecision(DomainModel):
    signal: str = Field(min_length=1, max_length=10)
    confidence: int = Field(ge=0, le=100)
    entry: float | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    risk: str = Field(min_length=1, max_length=10)
    horizon: str = Field(min_length=1, max_length=40)
    reasoning: str = Field(min_length=1, max_length=2500)
    timestamp: datetime = Field(default_factory=utc_now)


class PhysicalGoldDecision(DomainModel):
    recommendation: str = Field(min_length=1, max_length=20)
    conviction: str = Field(min_length=1, max_length=20)
    horizon: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=200)
    allocation_guidance: str = Field(min_length=1, max_length=500)
    reasons: tuple[str, ...] = Field(default_factory=tuple, max_length=5)
    thesis: str = Field(min_length=1, max_length=1200)
    confidence: int = Field(ge=0, le=100)
    timestamp: datetime = Field(default_factory=utc_now)


class ETFDecision(DomainModel):
    recommendation: str = Field(min_length=1, max_length=20)
    conviction: str = Field(min_length=1, max_length=20)
    horizon: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=200)
    vehicle_guidance: str = Field(min_length=1, max_length=600)
    flow_context: str = Field(min_length=1, max_length=300)
    allocation_guidance: str = Field(min_length=1, max_length=500)
    reasons: tuple[str, ...] = Field(default_factory=tuple, max_length=5)
    thesis: str = Field(min_length=1, max_length=1200)
    confidence: int = Field(ge=0, le=100)
    timestamp: datetime = Field(default_factory=utc_now)
