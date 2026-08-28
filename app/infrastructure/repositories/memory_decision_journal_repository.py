from app.application.decision_journal import DecisionJournalRepository
from app.domain.intelligence import DecisionReport


class MemoryDecisionJournalRepository(DecisionJournalRepository):
    def __init__(self) -> None:
        self.reports: list[DecisionReport] = []

    def append(self, report: DecisionReport) -> None:
        self.reports.insert(0, report)

    def latest(self) -> DecisionReport | None:
        return self.reports[0] if self.reports else None

    def list_recent(self, limit: int = 50) -> tuple[DecisionReport, ...]:
        return tuple(self.reports[:limit])
