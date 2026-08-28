from datetime import datetime
from typing import Protocol

from app.domain.notification_models import DeliveryReceipt, DiscordMessage, NotificationState


class NotificationPublisher(Protocol):
    def publish(self, message: DiscordMessage) -> DeliveryReceipt:
        """Publish a formatted notification."""


class NotificationStateRepository(Protocol):
    def load(self) -> NotificationState:
        """Load the current notification state."""

    def save(self, state: NotificationState) -> None:
        """Persist the current notification state."""


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""
