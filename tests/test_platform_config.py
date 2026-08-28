import json
from pathlib import Path

import pytest

from app.application.platform_config import ApiProviderConfig, AuthMode
from app.domain.market_data import DataProviderId
from app.infrastructure.config_loader import load_platform_config


def test_platform_config_loads_and_references_expected_providers():
    config = load_platform_config("config/platform.json")
    llm_providers = {entry.provider: entry for entry in config.ai_reasoning.providers}

    assert config.ai_reasoning_enabled is True
    assert llm_providers["groq"].models == ("openai/gpt-oss-120b",)
    assert llm_providers["gemini"].models[0].startswith("gemini-")
    assert len(llm_providers["gemini"].models) >= 2, "gemini should list a fallback chain"
    assert "cerebras" not in llm_providers
    assert config.polling.run_forever_interval_seconds == 60
    assert config.providers[DataProviderId.TWELVE_DATA].api_key_env == "TWELVE_DATA_API_KEY"
    assert config.providers[DataProviderId.FRED].api_key_env == "FRED_API_KEY"
    assert "economic_calendar" not in config.providers[DataProviderId.FINNHUB].endpoints
    assert config.providers[DataProviderId.FINNHUB].endpoints["news"].path == "/news"
    assert config.providers[DataProviderId.CFTC_COT].auth_mode == AuthMode.NONE
    assert (
        config.providers[DataProviderId.CFTC_COT].endpoints["cot_disaggregated"].path
        == "/resource/72hh-3qpy.json"
    )
    assert config.providers[DataProviderId.SPDR_GLD].auth_mode == AuthMode.NONE
    assert config.providers[DataProviderId.GDELT].auth_mode == AuthMode.NONE
    assert config.providers[DataProviderId.NEWSAPI].endpoints["everything"].cache_seconds >= 1800


def test_checked_in_platform_config_does_not_contain_secret_values():
    raw_config = Path("config/platform.json").read_text(encoding="utf-8")

    blocked_fragments = (
        "gsk_",
        "discord.com/api/webhooks/",
        "AQ.",
        "716c",
        "356015",
        "193d8",
    )
    assert not any(fragment in raw_config for fragment in blocked_fragments)


def test_authenticated_provider_requires_env_name_not_secret_value():
    with pytest.raises(ValueError):
        ApiProviderConfig.model_validate(
            {
                "provider_id": "twelve_data",
                "enabled": True,
                "base_url": "https://api.twelvedata.com",
                "auth_mode": "query_param",
                "api_key_env": "TWELVE_DATA_API_KEY=secret",
                "api_key_param": "apikey",
            }
        )


def test_no_manual_csv_path_workflow_is_configured():
    raw_config = json.loads(Path("config/platform.json").read_text(encoding="utf-8"))
    serialized = json.dumps(raw_config).lower()

    assert "csv_path" not in serialized
    assert "cot_csv_path" not in serialized
    assert "etf_flows_csv_path" not in serialized
