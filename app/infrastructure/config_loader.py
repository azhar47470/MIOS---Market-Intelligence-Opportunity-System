import json
from pathlib import Path

from app.application.ai_research_config import AIResearchConfig
from app.application.decision_config import DecisionEngineConfig
from app.application.notification_config import NotificationConfig
from app.application.platform_config import PlatformConfig


def load_notification_config(path: str | Path) -> NotificationConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw_config = json.load(handle)
    return NotificationConfig.model_validate(raw_config)


def load_platform_config(path: str | Path) -> PlatformConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw_config = json.load(handle)
    return PlatformConfig.model_validate(raw_config)


def load_decision_engine_config(path: str | Path) -> DecisionEngineConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw_config = json.load(handle)
    return DecisionEngineConfig.model_validate(raw_config)


def load_ai_research_config(path: str | Path) -> AIResearchConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw_config = json.load(handle)
    return AIResearchConfig.model_validate(raw_config)
