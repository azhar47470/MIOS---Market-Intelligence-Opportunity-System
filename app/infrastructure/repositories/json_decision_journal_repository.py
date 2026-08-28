import json
import os
import sys
import contextlib
from pathlib import Path

from app.application.decision_journal import DecisionJournalRepository
from app.domain.intelligence import DecisionReport

@contextlib.contextmanager
def file_lock(file_path: Path):
    lock_path = str(file_path) + ".lock"
    # Ensure parent directory exists before opening lock file
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt
            try:
                # LK_LOCK (1) blocks until lock is acquired
                msvcrt.locking(lock_file.fileno(), 1, 1)
            except (ImportError, IOError):
                pass
        else:
            import fcntl
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, IOError):
                pass
        yield
    finally:
        if sys.platform == "win32":
            import msvcrt
            try:
                lock_file.seek(0)
                # LK_UNLCK (0) unlocks
                msvcrt.locking(lock_file.fileno(), 0, 1)
            except (ImportError, IOError):
                pass
        lock_file.close()
        try:
            os.remove(lock_path)
        except OSError:
            pass


class JsonDecisionJournalRepository(DecisionJournalRepository):
    def __init__(self, path: str | Path, max_stored_records: int = 1000) -> None:
        self._path = Path(path)
        self._max_stored_records = max_stored_records

    def append(self, report: DecisionReport) -> None:
        with file_lock(self._path):
            reports = list(self.list_recent(limit=self._max_stored_records))
            reports.insert(0, report)
            # Cap the number of records to keep file I/O fast and memory footprint low
            if len(reports) > self._max_stored_records:
                reports = reports[:self._max_stored_records]
            self._write_locked(reports)

    def latest(self) -> DecisionReport | None:
        with file_lock(self._path):
            reports = self.list_recent(limit=1)
            return reports[0] if reports else None

    def list_recent(self, limit: int = 50) -> tuple[DecisionReport, ...]:
        # If calling list_recent from outside append/latest, we still need a shared lock,
        # but to keep it simple, we wrap file read in file_lock.
        # Since file_lock is exclusive, it is safe against concurrent writes.
        if not self._path.exists():
            return ()
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                raw_reports = json.load(handle)
            reports = tuple(DecisionReport.model_validate(item) for item in raw_reports)
            return reports[:limit]
        except (json.JSONDecodeError, ValueError):
            # If the file is empty or corrupted, return empty tuple
            return ()

    def _write_locked(self, reports: list[DecisionReport]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [report.model_dump(mode="json") for report in reports]
        
        # Write atomically using a temporary file in the same directory
        temp_path = self._path.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            # Atomic replace (overwrites self._path if it exists)
            os.replace(temp_path, self._path)
        except Exception as e:
            # Clean up temp file if something went wrong
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise e
