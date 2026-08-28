from app.application.ports import NotificationStateRepository
from app.domain.notification_models import NotificationState


class MemoryNotificationStateRepository(NotificationStateRepository):
    def __init__(self, initial_state: NotificationState | None = None) -> None:
        self.state = initial_state or NotificationState()

    def load(self) -> NotificationState:
        return self.state

    def save(self, state: NotificationState) -> None:
        self.state = state
