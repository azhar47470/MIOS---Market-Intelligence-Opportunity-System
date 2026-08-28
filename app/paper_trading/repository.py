import json
import os
from pathlib import Path
from typing import Protocol

from app.paper_trading.models import PaperTradingState
from app.infrastructure.repositories.json_decision_journal_repository import file_lock


class PaperTradingRepository(Protocol):
    def load(self) -> PaperTradingState:
        """Load current paper trading state."""

    def save(self, state: PaperTradingState) -> None:
        """Persist paper trading state."""


class JsonPaperTradingRepository(PaperTradingRepository):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> PaperTradingState:
        with file_lock(self._path):
            if not self._path.exists():
                return PaperTradingState()
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                return PaperTradingState.model_validate(payload)
            except (json.JSONDecodeError, ValueError):
                return PaperTradingState()

    def save(self, state: PaperTradingState) -> None:
        with file_lock(self._path):
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_suffix(".tmp")
            try:
                temp_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
                os.replace(temp_path, self._path)
            except Exception as e:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                raise e
