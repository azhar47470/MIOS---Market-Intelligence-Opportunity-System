from pydantic import Field, model_validator

from app.application.platform_config import ConfigModel
from app.domain.ai import AgentRole

SPECIALIST_ROLES = (
    AgentRole.TECHNICAL_ANALYST,
    AgentRole.MACRO_ECONOMIST,
    AgentRole.FEDERAL_RESERVE_ANALYST,
    AgentRole.INSTITUTIONAL_ANALYST,
    AgentRole.ETF_FLOW_ANALYST,
    AgentRole.NEWS_ANALYST,
    AgentRole.GEOPOLITICAL_ANALYST,
    AgentRole.RISK_ANALYST,
)


class AIEscalationConfig(ConfigModel):
    enabled: bool = True
    stability_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    geopolitical_shock_threshold: float = Field(default=30.0, ge=0.0, le=100.0)
    ambiguous_margin: float = Field(default=10.0, ge=0.0, le=100.0)


class AnalystPromptConfig(ConfigModel):
    enabled: bool = True
    system_prompt: str = Field(min_length=1, max_length=6000)




class AIResearchConfig(ConfigModel):
    enabled: bool = True
    escalation: AIEscalationConfig = Field(default_factory=AIEscalationConfig)
    escalation: AIEscalationConfig = Field(default_factory=AIEscalationConfig)
    specialist_prompts: dict[AgentRole, AnalystPromptConfig]
    committee_system_prompt: str = Field(min_length=1, max_length=6000)
    fallback_confidence_cap: int = Field(default=35, ge=0, le=100)
    committee_fallback_confidence_adjustment: int = Field(default=-8, ge=-30, le=0)
    max_evidence_per_report: int = Field(default=8, ge=1, le=10)

    @model_validator(mode="after")
    def require_all_specialist_prompts(self) -> "AIResearchConfig":
        missing = set(SPECIALIST_ROLES) - set(self.specialist_prompts)
        if missing:
            labels = ", ".join(sorted(role.value for role in missing))
            raise ValueError(f"missing specialist prompt configuration for: {labels}")
        return self

