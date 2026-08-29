"""Regression tests for the surgical dashboard repair.

Covers the P0 presentation failure where the static mockup DOM ids did not
match the live JavaScript targets:

A. live dashboard bindings replace static values
B. WAIT hides Entry/TP/SL
C. actionable mode displays trade fields
D. empty journal displays the empty state
E. stale timestamp does not appear LIVE
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

    # Fabricated mockup numbers/labels must not survive into the served page.
    for fabricated in ("4651", "4650", "4837", "4558", "98% CONF", "SYS: 2026", "BUY 95"):
        assert fabricated not in html, f"fabricated mockup value still present: {fabricated}"

    # Live binding targets must exist in the DOM.
    for element_id in (
        "val-spot",
        "mega-action",
        "mega-conf",
        "mega-move",
        "lenses-container",
        "v5-history-body",
        "provider-strip",
        "hdr-time",
        "hdr-live",
        "empty-state",
        "chart-area",
    ):
        assert f'id="{element_id}"' in html, f"live binding target missing: {element_id}"

    # Every el('id') JS target must resolve to a real DOM id.
    targets = set(re.findall(r"el\('([A-Za-z0-9_-]+)'\)", html))
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
    assert targets <= ids, f"JS targets with no DOM element: {sorted(targets - ids)}"


def test_b_wait_hides_trade_levels():
    html = _dashboard_html()

    # Lens cards only render Entry/TP/SL when the persisted mode policy is
    # not WAIT and actually carries an entry price.
    assert "if(!isWait && p.entry)" in html
    # Mode detail cards gate the trade-level block on actionable forex only.
    assert "p.mode==='forex' && p.actionable && p.entry" in html
    # No client-side policy recomputation: levels come straight from the
    # persisted mode-policy payload fields.
    assert "parseFloat(p.entry).toFixed(2)" in html


def test_c_actionable_mode_displays_trade_fields():
    html = _dashboard_html()

    for field in ("ENTRY", "TP", "SL", "Take Profit", "Stop Loss"):
        assert field in html
    # The actionable branch renders entry/take-profit/stop-loss from the
    # persisted policy (guarded by test_b conditions).
    assert "parseFloat(p.take_profit).toFixed(2)" in html
    assert "parseFloat(p.stop_loss).toFixed(2)" in html


def test_d_empty_journal_shows_empty_state():
    html = _dashboard_html()
    assert "No decision yet" in html
    assert "Run: python -m app.main run-once" in html
    # JS unhides the empty state instead of leaving the loader over the mockup.
    assert "el('empty-state').classList.remove('hidden')" in html

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

    # The badge text flips to STALE when the decision is outside the window.
    html = _dashboard_html()
    assert "fr.fresh ? 'LIVE' : 'STALE'" in html


def test_f_missing_provider_status_fails_gracefully():
    html = _dashboard_html()
    # Null-safe strip renderer: tolerates a missing endpoint/node.
    assert "if(!node) return;" in html
    assert "'PROVIDERS: --'" in html
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
    # The render body still logs failures instead of crashing the poll loop.
    assert "} catch(e) {" in html
    assert "console.error(e)" in html


def test_dashboard_wording_does_not_imply_execution():
    html = _dashboard_html()
    assert "Executed" not in html
    assert "Delivered" in html


def test_history_is_cached_per_decision():
    html = _dashboard_html()
    # History refetches only when the current decision changes, not per poll.
    assert "_historyCache" in html
    assert "d.timestamp !== _historyKey" in html
