import json
import os
import sys
import contextlib
from pathlib import Path

from app.application.ports import NotificationStateRepository
from app.domain.notification_models import NotificationState
from app.infrastructure.repositories.json_decision_journal_repository import file_lock


class JsonNotificationStateRepository(NotificationStateRepository):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> NotificationState:
        with file_lock(self._path):
            if not self._path.exists():
                return NotificationState()
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    raw_state = json.load(handle)
                return NotificationState.model_validate(raw_state)
            except (json.JSONDecodeError, ValueError):
                return NotificationState()

    def save(self, state: NotificationState) -> None:
        with file_lock(self._path):
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_suffix(".tmp")
            try:
                with temp_path.open("w", encoding="utf-8") as handle:
                    json.dump(state.model_dump(mode="json"), handle, indent=2, sort_keys=True)
                os.replace(temp_path, self._path)
            except Exception as e:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                raise e
