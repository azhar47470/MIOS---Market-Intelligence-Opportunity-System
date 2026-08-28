from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import NotificationKind, NotificationPriority, Recommendation


class ConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AlertRuleConfig(ConfigModel):
    send_initial_snapshot: bool = False
    confidence_significant_delta: int = Field(default=8, ge=1, le=100)
    consolidation_window_seconds: int = Field(default=900, ge=30, le=86_400)
    min_seconds_between_confidence_alerts: int = Field(default=900, ge=30, le=86_400)
    macro_materiality_threshold: int = Field(default=75, ge=0, le=100)
    geopolitical_materiality_threshold: int = Field(default=75, ge=0, le=100)
    high_priority_risk_levels: tuple[NotificationPriority, ...] = (
        NotificationPriority.HIGH,
        NotificationPriority.CRITICAL,
    )


class DiscordConfig(ConfigModel):
    enabled: bool = True
    webhook_url_env: str = Field(default="DISCORD_WEBHOOK_URL", min_length=1)
    username: str = Field(default="Gold Intelligence Platform", min_length=1, max_length=80)
    avatar_url: str | None = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    enabled_notification_types: tuple[NotificationKind, ...] = tuple(NotificationKind)
    colors: dict[Recommendation, int] = Field(
        default_factory=lambda: {
            Recommendation.STRONG_BUY: 0x21A67A,
            Recommendation.BUY: 0x2ECC71,
            Recommendation.HOLD: 0xF1C40F,
            Recommendation.WAIT: 0xC0C0C0,
            Recommendation.TAKE_PROFIT: 0xE67E22,
            Recommendation.STRONG_SELL: 0xE74C3C,
        }
    )
    priority_colors: dict[NotificationPriority, int] = Field(
        default_factory=lambda: {
            NotificationPriority.LOW: 0x95A5A6,
            NotificationPriority.NORMAL: 0x3498DB,
            NotificationPriority.HIGH: 0xF39C12,
            NotificationPriority.CRITICAL: 0xE74C3C,
        }
    )

    @field_validator("colors")
    @classmethod
    def require_all_recommendation_colors(
        cls, value: dict[Recommendation, int]
    ) -> dict[Recommendation, int]:
        missing = set(Recommendation) - set(value)
        if missing:
            labels = ", ".join(item.value for item in sorted(missing, key=lambda item: item.value))
            raise ValueError(f"missing colors for recommendations: {labels}")
        return value


class NotificationConfig(ConfigModel):
    alert_rules: AlertRuleConfig = Field(default_factory=AlertRuleConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
