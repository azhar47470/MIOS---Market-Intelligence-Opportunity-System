"""Regression tests for the MIOS AURUM dashboard redesign.

Guards the presentation contract of the Decision Theatre interface:

A. live dashboard bindings replace any static values (no fabricated data)
B. WAIT never exposes trade levels (lanes + 3D corridor)
C. actionable mode displays persisted trade fields
D. empty journal displays the empty state
E. stale decision drops out of LIVE (badge + stage fog)
F. missing/empty provider-status fails gracefully
G. one missing optional DOM node does not abort the entire render
"""

import json
import re
import threading
import urllib.request
from datetime import timedelta
from datetime import UTC
from datetime import datetime
from http.server import ThreadingHTTPServer

import pytest

from app.presentation.dashboard import (
    _dashboard_html,
    _freshness_payload,
    _freshness_window_seconds,
    create_dashboard_handler,
)
from tests.test_orchestrator_backtesting_dashboard import (
    FakeMarketDataClient,
    low_threshold_config,
    make_bars,
)
from app.application.event_bus import InMemoryEventBus
from app.application.orchestrator import GoldIntelligenceOrchestrator
from app.infrastructure.repositories.memory_decision_journal_repository import (
    MemoryDecisionJournalRepository,
)
from app.ingestion.factory import IngestionClients


class StubJournal:
    def __init__(self, report=None):
        self._report = report

    def latest(self):
        return self._report

    def list_recent(self, limit: int = 50):
        return (self._report,) if self._report is not None else ()


@pytest.fixture(scope="module")
def decision():
    orchestrator = GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(twelve_data=FakeMarketDataClient(make_bars())),
        decision_config=low_threshold_config(),
        decision_journal=MemoryDecisionJournalRepository(),
        event_bus=InMemoryEventBus(),
    )
    return orchestrator.run_once().decision


def _serve(journal):
    handler = create_dashboard_handler(journal)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get_json(server, path):
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_a_live_bindings_replace_static_mockup_values():
    html = _dashboard_html()

    # Fabricated mockup numbers/labels must never survive into the served page.
    for fabricated in (
        "4651", "4650", "4837", "4558", "98% CONF", "SYS: 2026", "BUY 95",
        "1234.56", "MOCK", "mock",
    ):
        assert fabricated not in html, f"fabricated mockup value present: {fabricated}"

    # Live binding targets must exist in the DOM.
    for element_id in (
        "rail-spot",
        "verdict-word",
        "conf-val",
        "v-move",
        "lane-physical",
        "lane-forex",
        "lane-etf",
        "constellation",
        "memory-track",
        "provider-strip",
        "rail-time",
        "rail-live-txt",
        "empty-state",
        "decision-stamp",
    ):
        assert f'id="{element_id}"' in html, f"live binding target missing: {element_id}"

    # Every el('id') JS target must resolve to a real DOM id.
    targets = set(re.findall(r"el\('([A-Za-z0-9_-]+)'\)", html))
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
    assert targets <= ids, f"JS targets with no DOM element: {sorted(targets - ids)}"


def test_b_wait_hides_trade_levels():
    html = _dashboard_html()

    # Mode lanes render Entry/TP/SL only when the persisted mode policy is
    # not WAIT, is actionable, and actually carries an entry price.
    assert "!isWait && p.actionable && p.entry" in html
    # WAIT branch explicitly refuses trade parameters.
    assert "Conservative posture — no trade parameters while WAIT." in html
    # The 3D corridor gates trade planes on actionable forex only.
    assert "!!(fx && !fx.is_wait && fx.actionable && fx.entry)" in html
    # Corridor WAIT note: market structure only, no trade levels.
    assert "no trade levels" in html


def test_c_actionable_mode_displays_trade_fields():
    html = _dashboard_html()

    for field in ("Entry", "Take profit", "Stop loss", "Risk", "Horizon"):
        assert field in html
    # The actionable lane branch renders levels from the persisted policy
    # (guarded by the test_b conditions), never recomputed client-side.
    assert "fmt2(p.entry)" in html
    assert "fmt2(p.take_profit)" in html
    assert "fmt2(p.stop_loss)" in html
    # Corridor planes for trade levels exist for the actionable case.
    assert "pl-entry" in html and "pl-tp" in html and "pl-sl" in html


def test_d_empty_journal_shows_empty_state():
    html = _dashboard_html()
    assert "The observatory is dark" in html
    assert "No decision yet — Run: python -m app.main run-once" in html
    # JS lifts the boot veil and reveals the empty state instead of hanging.
    assert "el('empty-state').classList.remove('hidden')" in html
    # The .hidden class must actually hide overlays (empty state starts hidden).
    assert '.hidden { display: none !important; }' in html
    assert 'id="empty-state" class="hidden"' in html

    server = _serve(StubJournal())
    try:
        payload = _get_json(server, "/api/latest")
    finally:
        server.shutdown()
    assert payload == {"latest": None, "freshness": None}


def test_e_stale_decision_is_not_live(decision):
    fresh = _freshness_payload(decision)
    assert fresh["fresh"] is True
    assert fresh["stale_after_seconds"] == _freshness_window_seconds()

    old = decision.model_copy(
        update={"timestamp": datetime.now(UTC) - timedelta(minutes=30)}
    )
    stale = _freshness_payload(old)
    assert stale["fresh"] is False
    assert stale["age_seconds"] >= stale["stale_after_seconds"]

    # Badge text flips to STALE and the whole stage drops into fog.
    html = _dashboard_html()
    assert "fr.fresh ? 'LIVE' : 'STALE'" in html
    assert "document.body.classList.toggle('is-stale', !fr.fresh)" in html
    # The stale stamp is decorative and must never block rail interactions.
    assert "pointer-events: none;" in html


def test_f_missing_provider_status_fails_gracefully():
    html = _dashboard_html()
    # Null-safe strip renderer: tolerates a missing node/empty payload.
    assert "if (!node) return;" in html
    assert "'PROVIDERS --'" in html
    # Provider fetch cannot abort the render cycle.
    assert "fetch('/api/provider-status').then(r => r.json()).catch(() => null)" in html

    server = _serve(StubJournal())
    try:
        payload = _get_json(server, "/api/provider-status")
    finally:
        server.shutdown()
    assert payload == {"providers": []}


def test_g_missing_optional_dom_node_does_not_abort_render():
    html = _dashboard_html()

    # el() falls back to a noop stub instead of returning null.
    assert "document.getElementById(id) || _missingEl" in html
    # renderProviderStrip guards its own node lookup.
    assert "document.getElementById('provider-strip')" in html
    # The render body still survives exceptions instead of crashing the poll.
    assert "} catch (e) {" in html


def test_wording_never_implies_autonomous_execution():
    html = _dashboard_html()
    assert "Executed" not in html
    # The interface presents decision support language, not brokerage action.
    assert "CANONICAL OUTLOOK" in html.upper() or "verdict" in html.lower()


def test_history_is_cached_per_decision():
    html = _dashboard_html()
    # History refetches only when the current decision changes, not per poll.
    assert "_historyCache" in html
    assert "d.timestamp !== _historyKey" in html


def test_reduced_motion_is_honored():
    html = _dashboard_html()
    assert "prefers-reduced-motion" in html


def test_engine_score_is_magnitude_not_direction():
    html = _dashboard_html()

    # Market direction must never be inferred from the numeric engine score.
    assert "score > 50" not in html
    assert "score < 50" not in html
    assert "biasHexV" not in html

    # Real persisted analyst bias is displayed separately (role -> engine map).
    assert "extractEngineBias" in html
    assert "ROLE_ENGINE" in html
    assert "bias-chip" in html
    # Constellation hue comes from the persisted bias, never the score.
    assert "t.eng.bias ? biasHex(t.eng.bias)" in html


def test_critical_risk_is_visually_distinct():
    html = _dashboard_html()

    # CRITICAL gets an unmistakable filled, pulsing alarm treatment.
    assert ".risk-sev.critical" in html
    assert "criticalpulse" in html
    # Existing LOW/MEDIUM/HIGH semantics remain byte-identical.
    assert (
        ".risk-sev.high { color: var(--bear); } "
        ".risk-sev.medium { color: var(--warn); } "
        ".risk-sev.low { color: var(--bull); }" in html
    )
