import json
import pytest
from unittest.mock import MagicMock
from app.domain.intelligence import DecisionReport, ModePolicyPresentation
from tests.test_paper_trading import _sample_decision

def test_journal_serialization_and_backwards_compatibility():
    report = _sample_decision()
    
    # Missing mode_policy_results should parse fine
    old_report = report.model_copy(update={"mode_policy_results": None})
    assert old_report.mode_policy_results is None

    # Test serialization with mode_policy_results
    new_report = report.model_copy(update={
        "mode_policy_results": (
            ModePolicyPresentation(
                mode="physical",
                actionable=True,
                action="BUY",
                reason="Test",
                is_wait=False,
                confidence=90,
                expected_move="+$50",
            ),
        )
    })
    dumped = new_report.model_dump(mode="json")
    assert "mode_policy_results" in dumped
    assert dumped["mode_policy_results"][0]["mode"] == "physical"
    
    # And it deserializes back perfectly
    reloaded = DecisionReport.model_validate(dumped)
    assert len(reloaded.mode_policy_results) == 1
    assert reloaded.mode_policy_results[0].mode == "physical"

def test_api_mode_policies_endpoint_no_new_calls(monkeypatch):
    mock_journal = MagicMock()
    
    new_report = _sample_decision().model_copy(update={
        "mode_policy_results": (
            ModePolicyPresentation(
                mode="etf",
                actionable=False,
                action="WAIT",
                reason="Test reason",
                is_wait=True,
                confidence=80,
                expected_move="+$30",
            ),
        )
    })
    mock_journal.latest.return_value = new_report
    
    latest = mock_journal.latest()
    assert latest.mode_policy_results[0].mode == "etf"
    assert latest.mode_policy_results[0].reason == "Test reason"
    assert latest.mode_policy_results[0].actionable is False

def test_mode_policy_presentation_accepts_stringified_floats():
    p = ModePolicyPresentation(
        mode="forex",
        actionable=True,
        action="BUY",
        reason="Test",
        is_wait=False,
        confidence=90,
        expected_move="+$50",
        take_profit=str(4855.65),
        stop_loss=str(4575.52),
    )
    assert p.take_profit == "4855.65"
    assert p.stop_loss == "4575.52"
    
    # Ensure serialization treats them as strings
    dumped = p.model_dump(mode="json")
    assert dumped["take_profit"] == "4855.65"
    assert dumped["stop_loss"] == "4575.52"
