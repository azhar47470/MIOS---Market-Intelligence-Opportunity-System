import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.enums import Recommendation
from app.domain.intelligence import DecisionReport, MarketRegime
from app.domain.notification_models import ExpectedMove
from app.domain.common import EvidenceRecord, EvidenceStrength, RiskRecord
from app.domain.notification_models import InvalidationCondition, NotificationPriority, SupportResistanceLevels
from app.infrastructure.repositories.sqlite_decision_journal_repository import (
    SqliteDecisionJournalRepository,
)


def _report(recommendation: Recommendation = Recommendation.BUY, confidence: int = 70) -> DecisionReport:
    evidence = (
        EvidenceRecord(
            evidence_id="e-1",
            category="Technical",
            description="Support held",
            strength=EvidenceStrength.MEDIUM,
            confidence=60,
            source="technical_engine",
        ),
    )
    return DecisionReport(
        recommendation_id=f"rec-{recommendation.value}",
        recommendation=recommendation,
        investment_score=60,
        opportunity_score=55,
        confidence=confidence,
        expected_move=ExpectedMove(direction="SIDEWAYS", summary="Range"),
        expected_holding_period="1-2 weeks",
        market_regime=MarketRegime.RANGE,
        supporting_evidence=evidence,
        contradicting_evidence=(),
        risk_summary=(
            RiskRecord(risk="Dollar strength", severity=EvidenceStrength.HIGH, probability=60),
        ),
        invalidation_conditions=(
            InvalidationCondition(condition="Break below support", severity=NotificationPriority.NORMAL),
        ),
        support_resistance=SupportResistanceLevels(),
        explanation="Range-bound evidence.",
        timestamp=datetime.now(UTC),
    )


def test_empty_database_returns_none(tmp_path: Path):
    repo = SqliteDecisionJournalRepository(tmp_path / "decisions.db")
    assert repo.latest() is None
    assert repo.list_recent() == ()


def test_append_and_latest_roundtrip(tmp_path: Path):
    repo = SqliteDecisionJournalRepository(tmp_path / "decisions.db")
    repo.append(_report(Recommendation.BUY, 70))

    latest = repo.latest()
    assert latest is not None
    assert latest.recommendation is Recommendation.BUY
    assert latest.confidence == 70
    assert latest.explanation == "Range-bound evidence."


def test_list_recent_is_reverse_chronological(tmp_path: Path):
    repo = SqliteDecisionJournalRepository(tmp_path / "decisions.db")
    repo.append(_report(Recommendation.WAIT, 40))
    repo.append(_report(Recommendation.STRONG_SELL, 55))
    repo.append(_report(Recommendation.BUY, 80))

    reports = repo.list_recent()
    assert [r.recommendation for r in reports] == [
        Recommendation.BUY,
        Recommendation.STRONG_SELL,
        Recommendation.WAIT,
    ]
    assert repo.latest().recommendation is Recommendation.BUY


def test_list_recent_respects_limit(tmp_path: Path):
    repo = SqliteDecisionJournalRepository(tmp_path / "decisions.db")
    for index in range(5):
        repo.append(_report(Recommendation.WAIT, confidence=10 + index))

    assert len(repo.list_recent(limit=2)) == 2
    assert len(repo.list_recent(limit=100)) == 5


def test_persistence_across_instances(tmp_path: Path):
    db_path = tmp_path / "persisted.db"
    SqliteDecisionJournalRepository(db_path).append(_report(Recommendation.STRONG_BUY, 90))

    reopened = SqliteDecisionJournalRepository(db_path)
    assert reopened.latest() is not None
    assert reopened.latest().recommendation is Recommendation.STRONG_BUY
    assert len(reopened.list_recent()) == 1


def test_database_file_is_real_sqlite(tmp_path: Path):
    db_path = tmp_path / "real.db"
    SqliteDecisionJournalRepository(db_path).append(_report())

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT report FROM decisions").fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert payload["recommendation"] == "Buy"
    finally:
        conn.close()


def test_invalid_payload_row_is_skipped(tmp_path: Path):
    db_path = tmp_path / "dirty.db"
    repo = SqliteDecisionJournalRepository(db_path)
    repo.append(_report())
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("INSERT INTO decisions (report) VALUES (?)", ("{not json",))
        conn.commit()
    finally:
        conn.close()

    assert repo.latest() is not None
    assert len(repo.list_recent()) == 1
