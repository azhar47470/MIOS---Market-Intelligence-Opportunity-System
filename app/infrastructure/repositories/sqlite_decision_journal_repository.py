"""SQLite-backed decision journal repository."""

import json
import logging
import sqlite3
import threading
from pathlib import Path

from app.application.decision_journal import DecisionJournalRepository
from app.domain.intelligence import DecisionReport

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _parse_report(payload: str) -> DecisionReport | None:
    try:
        return DecisionReport.model_validate(json.loads(payload))
    except (ValueError, TypeError):
        logger.warning("Skipping unreadable decision journal row")
        return None


class SqliteDecisionJournalRepository(DecisionJournalRepository):
    """Persists decision reports into a local SQLite database.

    Reports are stored as JSON documents with an auto-incrementing row id, so
    chronological order is preserved and historical reports are never discarded.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def append(self, report: DecisionReport) -> None:
        payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (report) VALUES (?)", (payload,)
            )
            self._conn.commit()

    def latest(self) -> DecisionReport | None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT report FROM decisions ORDER BY id DESC"
            ).fetchall()
        for row in rows:
            report = _parse_report(row["report"])
            if report is not None:
                return report
        return None

    def list_recent(self, limit: int = 50) -> tuple[DecisionReport, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT report FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        reports: list[DecisionReport] = []
        for row in rows:
            report = _parse_report(row["report"])
            if report is not None:
                reports.append(report)
        return tuple(reports)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
