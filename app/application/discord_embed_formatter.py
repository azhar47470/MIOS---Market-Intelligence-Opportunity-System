from decimal import Decimal

from app.application.notification_config import NotificationConfig
from app.domain.enums import AlertTrigger
from app.domain.notification_models import (
    DiscordEmbed,
    DiscordEmbedField,
    DiscordEmbedFooter,
    DiscordMessage,
    EvidenceItem,
    InvalidationCondition,
    MarketEventImpact,
    PriceLevel,
    RecommendationSnapshot,
    RiskItem,
    StructuredNotification,
)


class DiscordEmbedFormatter:
    def __init__(self, config: NotificationConfig) -> None:
        self._config = config

    def format_recommendation(
        self,
        snapshot: RecommendationSnapshot,
        trigger: AlertTrigger,
        reason: str,
        events: tuple[MarketEventImpact, ...] = (),
        pending_alerts_count: int = 0,
    ) -> DiscordMessage:
        fields = (
            DiscordEmbedField(
                name="Recommendation", value=snapshot.recommendation.label, inline=True
            ),
            DiscordEmbedField(
                name="Investment Score", value=f"{snapshot.investment_score}/100", inline=True
            ),
            DiscordEmbedField(name="Confidence", value=f"{snapshot.confidence}/100", inline=True),
            DiscordEmbedField(name="Expected Move", value=self._format_expected_move(snapshot)),
            DiscordEmbedField(
                name="Expected Holding Period", value=snapshot.expected_holding_period, inline=True
            ),
            DiscordEmbedField(name="Market Regime", value=snapshot.market_regime, inline=True),
            DiscordEmbedField(
                name="Supporting Evidence",
                value=self._format_evidence(snapshot.supporting_evidence),
            ),
            DiscordEmbedField(name="Risk Summary", value=self._format_risks(snapshot.risk_summary)),
            DiscordEmbedField(
                name="Invalidation Conditions",
                value=self._format_invalidation(snapshot.invalidation_conditions),
            ),
            DiscordEmbedField(
                name="Support & Resistance Levels",
                value=self._format_support_resistance(snapshot),
            ),
            DiscordEmbedField(name="Timestamp", value=snapshot.timestamp.isoformat(), inline=False),
        )
        optional_fields: list[DiscordEmbedField] = []
        if snapshot.contradicting_evidence:
            optional_fields.append(
                DiscordEmbedField(
                    name="Contradicting Evidence",
                    value=self._format_evidence(snapshot.contradicting_evidence),
                )
            )
        if events:
            optional_fields.append(
                DiscordEmbedField(name="Material Events", value=self._format_events(events))
            )
        if pending_alerts_count:
            optional_fields.append(
                DiscordEmbedField(
                    name="Consolidated Updates",
                    value=f"{pending_alerts_count} prior update(s) consolidated into this alert.",
                )
            )

        embed = DiscordEmbed(
            title=f"{snapshot.recommendation.label} | Gold Intelligence Alert",
            description=self._truncate(reason, 4096),
            color=self._config.discord.colors[snapshot.recommendation],
            fields=self._limit_fields(fields + tuple(optional_fields)),
            timestamp=snapshot.timestamp,
            footer=DiscordEmbedFooter(
                text=(
                    f"GIP recommendation ID: {snapshot.recommendation_id} | "
                    f"Trigger: {trigger.value}"
                )
            ),
        )
        return DiscordMessage(
            username=self._config.discord.username,
            avatar_url=self._config.discord.avatar_url,
            embeds=(embed,),
        )

    def format_structured_notification(
        self, notification: StructuredNotification
    ) -> DiscordMessage:
        configured_fields = tuple(
            DiscordEmbedField(
                name=field.name,
                value=self._truncate(field.value, 1024),
                inline=field.inline,
            )
            for field in notification.fields
        )
        embed = DiscordEmbed(
            title=notification.title,
            description=self._truncate(notification.summary, 4096),
            color=self._config.discord.priority_colors[notification.priority],
            fields=self._limit_fields(configured_fields),
            timestamp=notification.timestamp,
            footer=DiscordEmbedFooter(text=f"GIP notification: {notification.kind.value}"),
        )
        return DiscordMessage(
            username=self._config.discord.username,
            avatar_url=self._config.discord.avatar_url,
            embeds=(embed,),
        )

    def _format_expected_move(self, snapshot: RecommendationSnapshot) -> str:
        move = snapshot.expected_move
        range_text = ""
        if move.min_usd is not None and move.max_usd is not None:
            range_text = (
                f" ({self._format_decimal(move.min_usd)}-{self._format_decimal(move.max_usd)} USD)"
            )
        elif move.max_usd is not None:
            range_text = f" (up to {self._format_decimal(move.max_usd)} USD)"
        return f"{move.direction}{range_text}: {move.summary}"

    def _format_evidence(self, evidence_items: tuple[EvidenceItem, ...]) -> str:
        lines = [
            f"- {item.category}: {item.description} [{item.strength}, {item.confidence}/100]"
            for item in evidence_items
        ]
        return self._truncate("\n".join(lines), 1024)

    def _format_risks(self, risks: tuple[RiskItem, ...]) -> str:
        lines = [
            f"- {risk.summary} [{risk.severity.value}, {risk.probability}/100]" for risk in risks
        ]
        return self._truncate("\n".join(lines), 1024)

    def _format_invalidation(self, conditions: tuple[InvalidationCondition, ...]) -> str:
        lines = [
            f"- {condition.condition} [{condition.severity.value}]" for condition in conditions
        ]
        return self._truncate("\n".join(lines), 1024)

    def _format_support_resistance(self, snapshot: RecommendationSnapshot) -> str:
        support = self._format_levels("Support", snapshot.support_resistance.support)
        resistance = self._format_levels("Resistance", snapshot.support_resistance.resistance)
        return self._truncate(f"{support}\n{resistance}", 1024)

    def _format_levels(self, label: str, levels: tuple[PriceLevel, ...]) -> str:
        if not levels:
            return f"{label}: Not available"
        formatted = ", ".join(
            f"{level.label} {self._format_decimal(level.price)}" for level in levels
        )
        return f"{label}: {formatted}"

    def _format_events(self, events: tuple[MarketEventImpact, ...]) -> str:
        lines = [
            f"- {event.title}: {event.summary} [{event.materiality_score}/100]" for event in events
        ]
        return self._truncate("\n".join(lines), 1024)

    def _limit_fields(self, fields: tuple[DiscordEmbedField, ...]) -> tuple[DiscordEmbedField, ...]:
        return fields[:25]

    def _truncate(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        # Reserve exactly 3 characters for "...", so the result is exactly `limit`
        # characters long, never limit + 2 (the previous value[:limit-1] + "..."
        # always ran 2 characters over every max_length this guards - e.g. Discord's
        # 1024-char field-value cap - which is what crashed the notification path.
        return f"{value[: max(0, limit - 3)]}..."

    def _format_decimal(self, value: Decimal) -> str:
        return f"{value.normalize():f}"
