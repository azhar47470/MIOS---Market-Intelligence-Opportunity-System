import hashlib
import json

from app.ai.agents.llm_client import AIProviderError, LLMJsonClient
from app.ai.validator import AIJsonValidator
from app.domain.ai import (
    AgentRole,
    AIContext,
    CommitteeReportPayload,
    InvestmentCommitteeReport,
)


class InvestmentCommitteeAgent:
    """Committee chair that synthesizes combined deterministic desk evidence, never raw
    market data, into a single advisory recommendation."""

    def __init__(
        self,
        *,
        system_prompt: str,
        client: LLMJsonClient,
        validator: AIJsonValidator | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._client = client
        self._validator = validator or AIJsonValidator()

    @property
    def role(self) -> AgentRole:
        return AgentRole.INVESTMENT_COMMITTEE_CHAIR

    def deliberate(self, context: AIContext) -> InvestmentCommitteeReport:
        def is_valid(raw_json: str) -> bool:
            payload, _error = self._validator.validate(raw_json, CommitteeReportPayload)
            return payload is not None

        completion = self._client.complete(
            _committee_system_prompt(self._system_prompt),
            _user_prompt(context),
            is_valid=is_valid,
        )
        payload, validation_error = self._validator.validate(
            completion.raw_json,
            CommitteeReportPayload,
        )
        if payload is None:
            # complete() already confirmed is_valid() passes before returning, so this only
            # fires if validation is somehow non-deterministic between calls - treat it the
            # same as before.
            raise AIProviderError(
                f"{completion.provider}: committee response failed contract validation: "
                f"{validation_error}"
            )
        return InvestmentCommitteeReport(
            **payload.model_dump(),
            report_id=_report_id(self.role.value, context.context_id, completion.raw_json),
            context_id=context.context_id,
            provider=completion.provider,
            usage=completion.usage,
            provider_attempts=completion.attempts,
        )


def _committee_system_prompt(role_prompt: str) -> str:
    return (
        f"{role_prompt}\n\n"
        "Return strict JSON only. The JSON object must have exactly these keys: "
        "final_recommendation, confidence, summary, disagreements, missing_evidence, "
        "weak_evidence, "
        "conflicting_evidence, required_confirmations, confidence_adjustment, why_not_buy, "
        "why_not_sell, alternative_scenarios. final_recommendation must be one of Strong "
        "Buy, Buy, Hold, Wait, Take Profit, Strong Sell. confidence_adjustment must be an "
        "integer from -30 to 30. disagreements, missing_evidence, weak_evidence, "
        "conflicting_evidence, required_confirmations, and alternative_scenarios must each "
        "be a flat JSON array of plain strings - never an object. For example: "
        '"alternative_scenarios": ["A stronger dollar would weaken the gold case.", '
        '"A dovish Fed surprise would strengthen it."]. Do not group these into bullish/'
        "bearish sub-objects."
    )


def _user_prompt(context: AIContext) -> str:
    return (
        f"Objective: {context.objective}\n"
        "Scoped facts JSON:\n"
        f"{json.dumps(context.facts, ensure_ascii=True, default=str)}"
    )


def _report_id(role: str, context_id: str, raw_json: str) -> str:
    digest = hashlib.sha256(f"{role}|{context_id}|{raw_json}".encode()).hexdigest()
    return f"AI-{role[:12].upper()}-{digest[:20]}"
