from typing import Protocol

from app.domain.intelligence import DecisionReport


class DecisionJournalRepository(Protocol):
    def append(self, report: DecisionReport) -> None:
        """Persist a decision report without discarding historical reports."""

    def latest(self) -> DecisionReport | None:
        """Return the most recent decision report."""

    def list_recent(self, limit: int = 50) -> tuple[DecisionReport, ...]:
        """Return recent decision reports in reverse chronological order."""
