from datetime import UTC, datetime

from app.application.discord_embed_formatter import DiscordEmbedFormatter
from app.application.notification_config import NotificationConfig
from app.application.ports import Clock, NotificationPublisher, NotificationStateRepository
from app.domain.enums import (
    AlertTrigger,
    DeliveryStatus,
    MarketEventKind,
)
from app.domain.notification_models import (
    MarketEventImpact,
    NotificationOutcome,
    NotificationState,
    PendingAlert,
    RecommendationSnapshot,
    StructuredNotification,
)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class NotificationEngine:
    def __init__(
        self,
        publisher: NotificationPublisher,
        state_repository: NotificationStateRepository,
        config: NotificationConfig,
        clock: Clock | None = None,
    ) -> None:
        self._publisher = publisher
        self._state_repository = state_repository
        self._config = config
        self._clock = clock or SystemClock()
        self._formatter = DiscordEmbedFormatter(config)

    def process_recommendation(
        self,
        snapshot: RecommendationSnapshot,
        events: tuple[MarketEventImpact, ...] = (),
    ) -> NotificationOutcome:
        if not self._config.discord.enabled:
            return NotificationOutcome(
                status=DeliveryStatus.SUPPRESSED,
                reason="Discord notifications are disabled by configuration.",
            )

        state = self._state_repository.load()
        trigger, reason = self._select_trigger(snapshot, events, state)
        updated_state = state.model_copy(update={"last_evaluated_recommendation": snapshot})

        if trigger is None:
            self._state_repository.save(updated_state)
            return NotificationOutcome(
                status=DeliveryStatus.SUPPRESSED,
                reason=reason,
                pending_count=len(updated_state.pending_alerts),
            )

        if self._should_consolidate(trigger, updated_state):
            pending = PendingAlert(
                trigger=trigger,
                reason=reason,
                snapshot=snapshot,
                events=events,
                queued_at=self._clock.now(),
            )
            updated_state = updated_state.model_copy(
                update={"pending_alerts": (*updated_state.pending_alerts, pending)}
            )
            self._state_repository.save(updated_state)
            return NotificationOutcome(
                status=DeliveryStatus.CONSOLIDATED,
                trigger=trigger,
                reason="Alert queued for consolidation to avoid repeated Discord updates.",
                pending_count=len(updated_state.pending_alerts),
            )

        outcome = self._publish_recommendation(updated_state, snapshot, trigger, reason, events)
        return outcome

    def flush_pending_updates(self) -> NotificationOutcome:
        state = self._state_repository.load()
        if not state.pending_alerts:
            return NotificationOutcome(
                status=DeliveryStatus.SUPPRESSED,
                reason="No pending Discord updates to flush.",
            )

        oldest_pending = min(alert.queued_at for alert in state.pending_alerts)
        elapsed_seconds = (self._clock.now() - oldest_pending).total_seconds()
        if elapsed_seconds < self._config.alert_rules.consolidation_window_seconds:
            return NotificationOutcome(
                status=DeliveryStatus.CONSOLIDATED,
                trigger=AlertTrigger.CONSOLIDATED_UPDATE,
                reason="Pending Discord updates are still inside the consolidation window.",
                pending_count=len(state.pending_alerts),
            )

        latest_pending = state.pending_alerts[-1]
        all_events = tuple(event for pending in state.pending_alerts for event in pending.events)
        reason = (
            f"Consolidated {len(state.pending_alerts)} material update(s): "
            f"{latest_pending.reason}"
        )
        return self._publish_recommendation(
            state,
            latest_pending.snapshot,
            AlertTrigger.CONSOLIDATED_UPDATE,
            reason,
            all_events,
        )

    def send_structured_notification(
        self, notification: StructuredNotification
    ) -> NotificationOutcome:
        if not self._config.discord.enabled:
            return NotificationOutcome(
                status=DeliveryStatus.SUPPRESSED,
                reason="Discord notifications are disabled by configuration.",
            )
        if notification.kind not in self._config.discord.enabled_notification_types:
            return NotificationOutcome(
                status=DeliveryStatus.SUPPRESSED,
                reason=f"{notification.kind.value} is disabled by configuration.",
            )

        message = self._formatter.format_structured_notification(notification)
        receipt = self._publisher.publish(message)
        return NotificationOutcome(
            status=receipt.status,
            reason="Structured Discord notification processed.",
            receipt=receipt,
        )

    def _select_trigger(
        self,
        snapshot: RecommendationSnapshot,
        events: tuple[MarketEventImpact, ...],
        state: NotificationState,
    ) -> tuple[AlertTrigger | None, str]:
        previous = state.last_evaluated_recommendation
        if previous is None:
            if self._config.alert_rules.send_initial_snapshot:
                return AlertTrigger.INITIAL_SNAPSHOT, "Initial recommendation snapshot."
            return None, "Initial recommendation baseline recorded without sending an alert."

        for event in events:
            event_trigger = self._trigger_for_event(event)
            if event_trigger is not None:
                return event_trigger, f"{event.title}: {event.summary}"

        if snapshot.recommendation != previous.recommendation:
            return (
                AlertTrigger.RECOMMENDATION_CHANGED,
                f"Recommendation changed from {previous.recommendation.value} to "
                f"{snapshot.recommendation.value}.",
            )

        confidence_reference = state.last_notified_recommendation or previous
        confidence_delta = abs(snapshot.confidence - confidence_reference.confidence)
        if confidence_delta >= self._config.alert_rules.confidence_significant_delta:
            return (
                AlertTrigger.CONFIDENCE_CHANGED_SIGNIFICANTLY,
                f"Confidence changed by {confidence_delta} point(s).",
            )

        return None, "No material notification trigger was detected."

    def _trigger_for_event(self, event: MarketEventImpact) -> AlertTrigger | None:
        if (
            event.kind == MarketEventKind.MACROECONOMIC
            and event.materiality_score >= self._config.alert_rules.macro_materiality_threshold
        ):
            return AlertTrigger.MAJOR_MACRO_EVENT
        if (
            event.kind == MarketEventKind.GEOPOLITICAL
            and event.materiality_score
            >= self._config.alert_rules.geopolitical_materiality_threshold
        ):
            return AlertTrigger.MAJOR_GEOPOLITICAL_EVENT
        if (
            event.kind == MarketEventKind.RISK_WARNING
            and event.priority in self._config.alert_rules.high_priority_risk_levels
        ):
            return AlertTrigger.HIGH_PRIORITY_RISK
        return None

    def _should_consolidate(self, trigger: AlertTrigger, state: NotificationState) -> bool:
        if trigger != AlertTrigger.CONFIDENCE_CHANGED_SIGNIFICANTLY:
            return False
        if state.last_alert_at is None:
            return False
        elapsed_seconds = (self._clock.now() - state.last_alert_at).total_seconds()
        return elapsed_seconds < self._config.alert_rules.min_seconds_between_confidence_alerts

    def _publish_recommendation(
        self,
        state: NotificationState,
        snapshot: RecommendationSnapshot,
        trigger: AlertTrigger,
        reason: str,
        events: tuple[MarketEventImpact, ...],
    ) -> NotificationOutcome:
        message = self._formatter.format_recommendation(
            snapshot=snapshot,
            trigger=trigger,
            reason=reason,
            events=events,
            pending_alerts_count=len(state.pending_alerts),
        )
        receipt = self._publisher.publish(message)
        if receipt.status == DeliveryStatus.SENT:
            state = state.model_copy(
                update={
                    "last_evaluated_recommendation": snapshot,
                    "last_notified_recommendation": snapshot,
                    "last_alert_at": self._clock.now(),
                    "pending_alerts": (),
                }
            )
            self._state_repository.save(state)
        return NotificationOutcome(
            status=receipt.status,
            trigger=trigger,
            reason=reason,
            receipt=receipt,
            pending_count=len(state.pending_alerts),
        )
