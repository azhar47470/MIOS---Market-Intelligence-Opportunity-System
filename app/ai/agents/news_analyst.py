import json

from app.ai.agents.llm_client import AIProviderError, LLMJsonClient
from app.ai.validator import AIJsonValidator
from app.application.http import HttpClient
from app.application.platform_config import AIReasoningConfig, ApiProviderConfig
from app.domain.ai import (
    AgentRole,
    AIContext,
    AINewsImpactAssessment,
    AIResponseEnvelope,
)


class GroqNewsAnalystAgent:
    """Backward-compatible news-impact specialist backed by the shared LLM client."""

    def __init__(
        self,
        *,
        http_client: HttpClient,
        groq_config: ApiProviderConfig,
        gemini_config: ApiProviderConfig,
        opencode_config: ApiProviderConfig,
        ollama_config: ApiProviderConfig,
        reasoning_config: AIReasoningConfig,
        validator: AIJsonValidator | None = None,
    ) -> None:
        self._client = LLMJsonClient(
            http_client=http_client,
            groq_config=groq_config,
            gemini_config=gemini_config,
            opencode_config=opencode_config,
            ollama_config=ollama_config,
            reasoning_config=reasoning_config,
        )
        self._validator = validator or AIJsonValidator()

    @property
    def role(self) -> AgentRole:
        return AgentRole.NEWS_ANALYST

    def analyze(self, context: AIContext) -> AIResponseEnvelope:
        assessment, raw_json, provider = self.analyze_impact(context)
        return AIResponseEnvelope(
            role=self.role,
            prompt_version=f"news-impact/{provider}",
            raw_json=raw_json,
            validated=assessment is not None,
            validation_error=None if assessment is not None else "AI assessment was not validated.",
        )

    def analyze_impact(self, context: AIContext) -> tuple[AINewsImpactAssessment, str, str]:
        def is_valid(raw_json: str) -> bool:
            assessment, _error = self._validator.validate(raw_json, AINewsImpactAssessment)
            return assessment is not None

        user_prompt, telemetry = _compress_user_prompt(context, 6000)
        completion = self._client.complete(
            _system_prompt(), user_prompt, is_valid=is_valid
        )
        assessment, validation_error = self._validator.validate(
            completion.raw_json,
            AINewsImpactAssessment,
        )
        if assessment is None:
            raise AIProviderError(
                f"{completion.provider}: validated JSON did not match news assessment: "
                f"{validation_error}"
            )
        return assessment, completion.raw_json, completion.provider


def _system_prompt() -> str:
    return (
        "You are an institutional gold market news analyst for physical XAU/USD "
        "investors. Analyze only the supplied facts. Return strict JSON only with "
        "keys severity, gold_impact_direction, gold_impact_magnitude, reliability, "
        "reasoning. Directions must be BULLISH, BEARISH, NEUTRAL, or MIXED. Numeric "
        "values are 0-100. Do not make a final investment recommendation."
    )


def _approx_tokens_str(text: str) -> int:
    return len(text) // 4

def _compress_user_prompt(context: AIContext, max_tokens: int = 6000) -> tuple[str, dict]:
    def _prompt(f):
        return f"Objective: {context.objective}\nFacts JSON:\n{json.dumps(f, default=str, ensure_ascii=True)}"
        
    full_prompt = _prompt(context.facts)
    if _approx_tokens_str(full_prompt) <= max_tokens:
        return full_prompt, {}

    telemetry = {
        "tokens_before": _approx_tokens_str(full_prompt),
        "articles_selected": 0,
        "articles_dropped": 0,
        "events_selected": 0,
        "events_dropped": 0,
    }
    
    facts = dict(context.facts)
    articles = facts.pop("articles", [])
    events = facts.pop("events", [])
    
    # Pre-rank logic (if articles are dicts, we can sort them, otherwise assume pre-sorted)
    
    facts["articles"] = []
    facts["events"] = []
    
    # Iteratively add articles
    for article in articles:
        facts["articles"].append(article)
        if _approx_tokens_str(_prompt(facts)) <= max_tokens * 0.8:
            telemetry["articles_selected"] += 1
        else:
            facts["articles"].pop()
            telemetry["articles_dropped"] += 1
            
    # Iteratively add events
    for event in events:
        facts["events"].append(event)
        if _approx_tokens_str(_prompt(facts)) <= max_tokens:
            telemetry["events_selected"] += 1
        else:
            facts["events"].pop()
            telemetry["events_dropped"] += 1
            
    final_prompt = _prompt(facts)
    telemetry["tokens_after"] = _approx_tokens_str(final_prompt)
    return final_prompt, telemetry

