from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.market_data import DataProviderId


class ConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class AuthMode(StrEnum):
    NONE = "none"
    QUERY_PARAM = "query_param"
    HEADER = "header"


class EndpointConfig(ConfigModel):
    path: str = Field(min_length=1, max_length=1000)
    method: str = Field(default="GET", pattern="^(GET|POST)$")
    query_params: dict[str, str] = Field(default_factory=dict)
    cache_seconds: int = Field(default=60, ge=0, le=604_800)

    @field_validator("path")
    @classmethod
    def reject_embedded_secrets(cls, value: str) -> str:
        lowered = value.lower()
        blocked_fragments = ("apikey=", "api_key=", "token=", "webhook")
        if any(fragment in lowered for fragment in blocked_fragments):
            raise ValueError("endpoint paths must not contain embedded secrets")
        return value


class ApiProviderConfig(ConfigModel):
    provider_id: DataProviderId
    enabled: bool = True
    base_url: str = Field(min_length=1, max_length=500)
    auth_mode: AuthMode = AuthMode.NONE
    api_key_env: str | None = Field(default=None, min_length=1, max_length=80)
    api_key_param: str | None = Field(default=None, min_length=1, max_length=80)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    retry_attempts: int = Field(default=2, ge=0, le=5)
    symbol_map: dict[str, str] = Field(default_factory=dict)
    endpoints: dict[str, EndpointConfig] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def reject_secret_bearing_urls(cls, value: str) -> str:
        lowered = value.lower()
        if "api_key" in lowered or "apikey" in lowered or "token=" in lowered:
            raise ValueError("base_url must not contain secrets")
        return value.rstrip("/")

    @field_validator("api_key_env")
    @classmethod
    def validate_env_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if "=" in value or value.startswith("http"):
            raise ValueError("api_key_env must be an environment variable name, not a value")
        return value

    @model_validator(mode="after")
    def validate_auth(self) -> "ApiProviderConfig":
        if self.auth_mode != AuthMode.NONE and not self.api_key_env:
            raise ValueError("authenticated providers must define api_key_env")
        if self.auth_mode == AuthMode.QUERY_PARAM and not self.api_key_param:
            raise ValueError("query-param auth providers must define api_key_param")
        return self


class PollingConfig(ConfigModel):
    run_forever_interval_seconds: int = Field(default=60, ge=1, le=86_400)
    dashboard_cycle_budget_seconds: int = Field(default=120, ge=0, le=86_400)
    slow_poll_seconds: int = Field(default=14_400, ge=60, le=86_400)
    news_poll_seconds: int = Field(default=300, ge=60, le=86_400)
    economic_calendar_poll_seconds: int = Field(default=300, ge=60, le=86_400)
    institutional_poll_seconds: int = Field(default=86_400, ge=300, le=604_800)


class LLMProviderConfig(ConfigModel):
    """One entry in the ordered LLM fallback chain.

    ``models`` is always a list, even for single-model providers (e.g. Groq) â€” this
    keeps the router logic uniform instead of branching on "single model vs multi-model
    provider". List order is try-order within the provider; ``providers`` order on
    ``AIReasoningConfig`` is try-order across providers.
    """

    provider: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    models: tuple[str, ...] = Field(min_length=1, max_length=10)


# Groq stays primary rather than Gemini. This isn't arbitrary: earlier in this project
# Gemini's free tier measured 22/20 RPD and 7/5 RPM under real usage (from when 9 LLM
# calls fired per cycle) - it's the scarcest of the two providers, which is exactly why
# it belongs last, not first. Groq has also answered correctly on every single observed
# run. Trying Gemini first would mean paying its tightest quota on every cycle instead of
# only when Groq is unavailable - the opposite of what the ordering evidence supports.
_DEFAULT_LLM_PROVIDERS: tuple[LLMProviderConfig, ...] = (
    LLMProviderConfig(provider="groq", models=("openai/gpt-oss-120b",)),
    LLMProviderConfig(provider="opencode", models=("laguna-s-2.1-free",)),
    LLMProviderConfig(provider="ollama", models=("gpt-oss:120b",)),
    LLMProviderConfig(provider="gemini", models=("gemini-3.5-flash",)),
)



class AIEscalationConfig(ConfigModel):
    enabled: bool = True
    stability_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    geopolitical_shock_threshold: float = Field(default=30.0, ge=0.0, le=100.0)
    ambiguous_confidence_margin: float = Field(default=10.0, ge=0.0, le=100.0)


class AIReasoningConfig(ConfigModel):
    providers: tuple[LLMProviderConfig, ...] = Field(
        default_factory=lambda: _DEFAULT_LLM_PROVIDERS, min_length=1, max_length=10
    )
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2000, ge=100, le=4000)

    @model_validator(mode="after")
    def validate_unique_providers(self) -> "AIReasoningConfig":
        names = [entry.provider for entry in self.providers]
        if len(names) != len(set(names)):
            raise ValueError("ai_reasoning.providers must not repeat the same provider name")
        return self


class MacroSeriesConfig(ConfigModel):
    enabled: bool = True
    cache_seconds: int = Field(default=86_400, ge=60, le=604_800)


class PlatformConfig(ConfigModel):
    version: str = Field(default="1.0", min_length=1, max_length=20)
    ai_reasoning_enabled: bool = True
    ai_reasoning: AIReasoningConfig = Field(default_factory=AIReasoningConfig)
    ai_escalation: AIEscalationConfig = Field(default_factory=AIEscalationConfig)
    providers: dict[DataProviderId, ApiProviderConfig]
    polling: PollingConfig = Field(default_factory=PollingConfig)
    macro_series: dict[str, MacroSeriesConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_provider_keys(self) -> "PlatformConfig":
        for key, provider in self.providers.items():
            if key != provider.provider_id:
                raise ValueError(
                    f"provider key {key} does not match provider_id {provider.provider_id}"
                )
        return self

