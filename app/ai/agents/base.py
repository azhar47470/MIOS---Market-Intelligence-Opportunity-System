from typing import Protocol

from app.domain.ai import AgentRole, AIContext, AIResponseEnvelope


class AIAgent(Protocol):
    @property
    def role(self) -> AgentRole:
        """The specialist role this agent performs."""

    def analyze(self, context: AIContext) -> AIResponseEnvelope:
        """Analyze context and return strict JSON wrapped in a validated envelope."""
