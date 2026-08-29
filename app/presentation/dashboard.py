# ruff: noqa: E501
import json
import logging
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.application.decision_journal import DecisionJournalRepository
from app.backtesting.metrics import hit_rate_from_outcomes
from app.domain.intelligence import DecisionReport, EngineId
from app.paper_trading.repository import JsonPaperTradingRepository, PaperTradingRepository

ENGINE_ROUTES = {
    "/api/engines/technical": EngineId.TECHNICAL,
    "/api/engines/fundamental": EngineId.FUNDAMENTAL,
    "/api/engines/institutional": EngineId.INSTITUTIONAL,
    "/api/engines/news": EngineId.NEWS,
    "/api/engines/geopolitical": EngineId.GEOPOLITICAL,
    "/api/engines/regime": EngineId.MARKET_REGIME,
}

logger = logging.getLogger("mios.dashboard")


def create_dashboard_handler(
    decision_journal: DecisionJournalRepository,
    paper_trading_repository: PaperTradingRepository | None = None,
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self._send_html(_dashboard_html())
                return
            if self.path == "/api/latest":
                latest = decision_journal.latest()
                payload = latest.model_dump(mode="json") if latest is not None else None
                self._send_json({"latest": payload, "freshness": _freshness_payload(latest)})
                return
            if self.path.startswith("/api/history"):
                reports = [
                    report.model_dump(mode="json") for report in decision_journal.list_recent()
                ]
                self._send_json({"reports": reports})
                return
            if self.path == "/api/health":
                self._send_json(_health_payload(decision_journal.latest()))
                return
            if self.path == "/api/provider-status":
                self._send_json(_provider_status_payload(decision_journal.latest()))
                return
            if self.path == "/api/research":
                self._send_json(_research_payload(decision_journal.latest()))
                return
            if self.path == "/api/decision-trace":
                self._send_json(_decision_trace_payload(decision_journal.latest()))
                return
            if self.path == "/api/backtesting":
                self._send_json(_backtesting_payload(decision_journal))
                return
            if self.path == "/api/mode-policies":
                latest = decision_journal.latest()
                if latest is not None and getattr(latest, "mode_policy_results", None):
                    self._send_json({"policies": [p.model_dump(mode="json") for p in latest.mode_policy_results]})
                else:
                    self._send_json({"policies": []})
                return
            if self.path == "/api/paper-trading":
                self._send_json(_paper_trading_payload(paper_trading_repository))
                return
            if self.path in ENGINE_ROUTES:
                self._send_json(
                    _engine_payload(decision_journal.latest(), ENGINE_ROUTES[self.path])
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def log_message(self, format: str, *args: object) -> None:
            logger.debug(format, *args)

        def _send_html(self, html: str) -> None:
            encoded = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: object) -> None:
            encoded = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return DashboardHandler


def serve_dashboard(
    decision_journal: DecisionJournalRepository,
    host: str = "127.0.0.1",
    port: int = 8765,
    paper_trading_repository: PaperTradingRepository | None = None,
) -> None:
    warn_if_insecure_flask_secret()
    handler = create_dashboard_handler(decision_journal, paper_trading_repository)
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()


def write_static_dashboard(path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_dashboard_html(), encoding="utf-8")


def warn_if_insecure_flask_secret() -> None:
    secret = os.getenv("FLASK_SECRET", "").strip()
    if not secret or secret == "change_me":
        logger.warning(
            "FLASK_SECRET is unset or still set to 'change_me'; change it before using the dashboard outside localhost."
        )


def _engine_payload(report: DecisionReport | None, engine: EngineId) -> dict[str, object]:
    if report is None:
        return {"engine": engine.value, "latest": None}
    breakdown = next((item for item in report.engine_breakdown if item.engine == engine), None)
    if breakdown is None:
        return {"engine": engine.value, "latest": None}
    return {
        "engine": engine.value,
        "latest": {
            "status": breakdown.status.value,
            "score": breakdown.score,
            "confidence": breakdown.confidence,
            "evidence": [item.model_dump(mode="json") for item in breakdown.evidence],
            "timestamp": report.timestamp.isoformat(),
        },
    }


def _paper_trading_payload(repository: PaperTradingRepository | None) -> dict[str, object]:
    if repository is None:
        repository = JsonPaperTradingRepository(Path("data") / "paper_trading.json")
    state = repository.load()
    open_pnl = (
        state.open_position.unrealized_pnl(state.last_price)
        if state.open_position is not None and state.last_price is not None
        else None
    )
    closed_pnl = [
        position.realized_pnl
        for position in state.closed_positions
        if position.realized_pnl is not None
    ]
    hit_rate = hit_rate_from_outcomes(tuple(pnl > 0 for pnl in closed_pnl))
    return {
        "open_position": (
            state.open_position.model_dump(mode="json") if state.open_position else None
        ),
        "closed_positions": [
            position.model_dump(mode="json") for position in state.closed_positions
        ],
        "open_unrealized_pnl": str(open_pnl) if open_pnl is not None else None,
        "closed_realized_pnl": str(sum(closed_pnl)) if closed_pnl else "0",
        "hit_rate": str(hit_rate),
        "last_price": str(state.last_price) if state.last_price is not None else None,
        "last_updated_at": (
            state.last_updated_at.isoformat() if state.last_updated_at is not None else None
        ),
    }


def _health_payload(report: DecisionReport | None) -> dict[str, object]:
    if report is None:
        return {"status": "NO_DECISION", "service": "MIOS Dashboard", "engines": []}
    engines = [
        {
            "engine": item.engine.value,
            "status": item.status.value,
            "score": item.score,
            "confidence": item.confidence,
            "runtime_ms": item.runtime_ms,
        }
        for item in report.engine_breakdown
    ]
    healthy = all(item["status"] == "SUCCESS" for item in engines)
    research = report.research_desk_report
    ai_usage = [
        analyst.usage
        for analyst in (research.analyst_reports if research is not None else ())
        if analyst.usage is not None
    ]
    return {
        "status": "HEALTHY" if healthy else "DEGRADED",
        "service": "MIOS Dashboard",
        "timestamp": report.timestamp.isoformat(),
        "engines": engines,
        "ai": {
            "requests": len(ai_usage),
            "runtime_ms": sum(item.runtime_ms for item in ai_usage),
            "prompt_tokens": sum(item.prompt_tokens for item in ai_usage),
            "completion_tokens": sum(item.completion_tokens for item in ai_usage),
        },
    }


def _provider_status_payload(report: DecisionReport | None) -> dict[str, object]:
    if report is None:
        return {"providers": []}
    return {
        "providers": [
            {"provider": name, "status": status.value}
            for name, status in sorted(report.provider_statuses.items())
        ],
        "timestamp": report.timestamp.isoformat(),
    }


def _research_payload(report: DecisionReport | None) -> dict[str, object]:
    if report is None or report.research_desk_report is None:
        return {"research": None}
    return {"research": report.research_desk_report.model_dump(mode="json")}


def _decision_trace_payload(report: DecisionReport | None) -> dict[str, object]:
    if report is None or report.decision_trace is None:
        return {"trace": None}
    return {"trace": report.decision_trace.model_dump(mode="json")}


_FRESHNESS_CONFIG_PATH = Path("config") / "platform.json"
_freshness_window_cache: int | None = None


def _freshness_window_seconds() -> int:
    """Decision age in seconds within which the latest decision counts as current.

    Uses the configured continuous-run polling interval so a decision stays
    "live" for one full monitoring cycle; falls back to 60s when the config
    is unavailable.
    """
    global _freshness_window_cache
    if _freshness_window_cache is None:
        window = 60
        try:
            with _FRESHNESS_CONFIG_PATH.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
            window = int(config.get("polling", {}).get("run_forever_interval_seconds", 60))
        except (OSError, ValueError, AttributeError, TypeError):
            window = 60
        _freshness_window_cache = max(1, window)
    return _freshness_window_cache


def _freshness_payload(report: DecisionReport | None) -> dict[str, object] | None:
    if report is None:
        return None
    age_seconds = int(
        max(0.0, (datetime.now(timezone.utc) - report.timestamp).total_seconds())
    )
    window = _freshness_window_seconds()
    return {
        "timestamp": report.timestamp.isoformat(),
        "age_seconds": age_seconds,
        "stale_after_seconds": window,
        "fresh": age_seconds <= window,
    }


def _backtesting_payload(journal: DecisionJournalRepository) -> dict[str, object]:
    reports = journal.list_recent(limit=500)
    actions = sum(
        1
        for report in reports
        if report.recommendation.value not in {"Wait", "Hold"}
    )
    return {
        "available": False,
        "reason": "No persisted backtest run is available in the decision journal.",
        "historical_decision_count": len(reports),
        "action_decision_count": actions,
    }


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MIOS // AURUM — Decision Theatre</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
/* ================================================================
   MIOS AURUM // THE DECISION THEATRE
   Signal -> Pressure -> Verdict. Depth encodes certainty.
   ================================================================ */
:root {
  --void: #050608;
  --void-2: #090B10;
  --panel: rgba(13, 16, 22, 0.72);
  --panel-solid: #0B0D12;
  --line: #1B2029;
  --line-soft: #141821;
  --ink: #ECE7DB;
  --ink-2: #B7B2A6;
  --dim: #7E8694;
  --faint: #566074;
  --gold: #D9A441;
  --gold-bright: #F0C463;
  --gold-dim: rgba(217, 164, 65, 0.14);
  --bull: #4CC38A;
  --bull-dim: rgba(76, 195, 138, 0.12);
  --bear: #E5484D;
  --bear-dim: rgba(229, 72, 77, 0.12);
  --wait: #8A8F98;
  --warn: #E0A33E;
  --info: #5AA7D6;
  --display: 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, 'Times New Roman', serif;
  --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }

body {
  margin: 0; background: var(--void); color: var(--ink);
  font-family: var(--mono); font-size: 12px; line-height: 1.5;
  -webkit-font-smoothing: antialiased; overflow-x: hidden;
}

/* Ambient stage: vignette + grain + depth fog. Pure CSS, GPU-cheap. */
body::before {
  content: ''; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(120% 90% at 50% -10%, rgba(217,164,65,0.07), transparent 55%),
    radial-gradient(90% 70% at 85% 110%, rgba(90,167,214,0.05), transparent 60%),
    radial-gradient(140% 120% at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%);
}
body::after {
  content: ''; position: fixed; inset: -50%; z-index: 1; pointer-events: none; opacity: 0.05;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.6'/%3E%3C/svg%3E");
  animation: grain 9s steps(6) infinite;
}
@keyframes grain {
  0% { transform: translate(0,0); } 20% { transform: translate(-2%,1%); }
  40% { transform: translate(1%,-2%); } 60% { transform: translate(-1%,2%); }
  80% { transform: translate(2%,1%); } 100% { transform: translate(0,0); }
}

::selection { background: var(--gold-dim); color: var(--gold-bright); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--void); }
::-webkit-scrollbar-thumb { background: #1E2430; border: 2px solid var(--void); border-radius: 6px; }

.gold { color: var(--gold); }
.bull { color: var(--bull); }
.bear { color: var(--bear); }
.dimc { color: var(--dim); }
.warn { color: var(--warn); }
.upper { text-transform: uppercase; letter-spacing: 0.14em; }
.serif { font-family: var(--display); }

/* ============ BOOT VEIL ============ */
#veil {
  position: fixed; inset: 0; z-index: 100; background: var(--void);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px;
  transition: opacity 0.7s var(--ease), visibility 0.7s;
}
#veil.gone { opacity: 0; visibility: hidden; }
#veil .glyph {
  width: 54px; height: 54px; border: 1px solid var(--gold-dim); border-radius: 50%;
  display: grid; place-items: center; color: var(--gold); font-size: 20px; position: relative;
}
#veil .glyph::before {
  content: ''; position: absolute; inset: -7px; border-radius: 50%;
  border: 1px solid transparent; border-top-color: var(--gold);
  animation: spin 1.4s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
#veil .v-title { font-family: var(--display); font-size: 20px; letter-spacing: 0.3em; color: var(--ink); }
#veil .v-sub { font-size: 10px; letter-spacing: 0.25em; color: var(--dim); text-transform: uppercase; }

/* ============ EMPTY STATE ============ */
#empty-state {
  position: fixed; inset: 0; z-index: 90; background: var(--void);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 32px; gap: 10px;
}
#empty-state .e-ring {
  width: 92px; height: 92px; border-radius: 50%; border: 1px dashed var(--faint);
  display: grid; place-items: center; margin-bottom: 14px; color: var(--faint); font-size: 26px;
}
#empty-state .e-title { font-family: var(--display); font-size: 30px; letter-spacing: 0.08em; color: var(--ink-2); }
#empty-state .e-sub { color: var(--dim); max-width: 420px; }
#empty-state .e-cmd {
  margin-top: 12px; padding: 10px 18px; border: 1px solid var(--line);
  background: var(--panel-solid); color: var(--gold); font-size: 12px;
}
.hidden { display: none !important; }

/* ============ COMMAND RAIL (sticky instrument strip) ============ */
#rail {
  position: fixed; top: 0; left: 0; right: 0; z-index: 60; height: 52px;
  display: flex; align-items: stretch; border-bottom: 1px solid var(--line-soft);
  background: rgba(5,6,8,0.82); backdrop-filter: blur(10px);
}
.rail-cell {
  display: flex; align-items: center; gap: 10px; padding: 0 18px;
  border-right: 1px solid var(--line-soft); white-space: nowrap;
}
.rail-cell.grow { flex: 1; border-right: none; }
#rail .brand { font-family: var(--display); letter-spacing: 0.24em; font-size: 14px; color: var(--ink); }
#rail .brand b { color: var(--gold); font-weight: 400; }
.rail-k { font-size: 9px; letter-spacing: 0.2em; color: var(--faint); text-transform: uppercase; }
.rail-v { font-size: 12px; color: var(--ink-2); }
#rail-spot { color: var(--gold-bright); font-weight: 600; }
#rail-nav { display: flex; gap: 2px; margin-left: auto; }
#rail-nav a {
  color: var(--dim); text-decoration: none; font-size: 10px; letter-spacing: 0.18em;
  text-transform: uppercase; padding: 6px 12px; border-radius: 2px; transition: color 0.25s, background 0.25s;
}
#rail-nav a:hover { color: var(--ink); }
#rail-nav a.active { color: var(--gold-bright); background: var(--gold-dim); }

/* freshness badge */
#rail-live { display: flex; align-items: center; gap: 7px; font-size: 10px; letter-spacing: 0.2em; }
#rail-live .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--bull); box-shadow: 0 0 10px var(--bull); animation: pulse 2.4s ease-in-out infinite; }
#rail-live.is-stale { color: var(--warn); }
#rail-live.is-stale .dot { background: var(--warn); box-shadow: 0 0 10px var(--warn); animation: none; }
@keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.45; transform: scale(0.72); } }

/* provider strip */
#provider-strip { font-size: 10px; letter-spacing: 0.12em; color: var(--dim); cursor: default; }
#provider-strip.ok { color: var(--bull); }
#provider-strip.degraded { color: var(--warn); }
#provider-strip.down { color: var(--bear); }
#provider-detail {
  position: absolute; top: 52px; right: 0; min-width: 260px; max-height: 300px; overflow: auto;
  background: var(--panel-solid); border: 1px solid var(--line); border-top: none;
  padding: 10px 14px; display: none; z-index: 61;
}
#provider-detail.open { display: block; }
#provider-detail .pd-row { display: flex; justify-content: space-between; gap: 18px; padding: 3px 0; font-size: 11px; }

/* ============ STAGE / ACTS ============ */
#stage { position: relative; z-index: 2; padding-top: 52px; }

.act {
  position: relative; max-width: 1280px; margin: 0 auto; padding: 96px 40px 40px;
  opacity: 0; transform: translateY(46px);
  transition: opacity 0.9s var(--ease), transform 0.9s var(--ease);
}
.act.lit { opacity: 1; transform: none; }
.act-head { display: flex; align-items: baseline; gap: 18px; margin-bottom: 34px; }
.act-no {
  font-family: var(--display); font-size: 44px; line-height: 1; color: transparent;
  -webkit-text-stroke: 1px var(--faint);
}
.act-title { font-family: var(--display); font-size: 22px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink); }
.act-sub { font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--dim); }
.act-rule { flex: 1; height: 1px; background: linear-gradient(90deg, var(--line), transparent); align-self: center; }

.panel {
  background: var(--panel); border: 1px solid var(--line);
  backdrop-filter: blur(6px); position: relative;
}
.panel::before, .panel::after {
  content: ''; position: absolute; width: 14px; height: 14px; pointer-events: none;
}
.panel::before { top: -1px; left: -1px; border-top: 1px solid var(--gold); border-left: 1px solid var(--gold); }
.panel::after { bottom: -1px; right: -1px; border-bottom: 1px solid var(--gold); border-right: 1px solid var(--gold); }
.panel-title {
  font-size: 10px; letter-spacing: 0.24em; text-transform: uppercase; color: var(--dim);
  padding: 12px 18px; border-bottom: 1px solid var(--line-soft);
}
.panel-body { padding: 18px; }

/* ============ ACT I — VERDICT ============ */
#verdict-grid { display: grid; grid-template-columns: minmax(340px, 1.15fr) minmax(300px, 1fr); gap: 28px; align-items: stretch; }

.verdict-word-wrap { padding: 34px 34px 26px; position: relative; overflow: hidden; }
.verdict-kicker { font-size: 10px; letter-spacing: 0.3em; color: var(--dim); text-transform: uppercase; margin-bottom: 14px; }
.verdict-kicker b { color: var(--gold); font-weight: 400; }
#verdict-word {
  font-family: var(--display); font-weight: 400; margin: 0;
  font-size: clamp(64px, 10vw, 128px); line-height: 0.95; letter-spacing: 0.02em;
  color: var(--ink); text-shadow: 0 0 60px rgba(0,0,0,0.6);
}
#verdict-word.is-bull { color: var(--bull); }
#verdict-word.is-bear { color: var(--bear); }
#verdict-word.is-wait { color: var(--wait); }
#verdict-meta { display: flex; gap: 26px; margin-top: 22px; flex-wrap: wrap; }
.vm { min-width: 86px; }
.vm .vm-k { font-size: 9px; letter-spacing: 0.2em; color: var(--faint); text-transform: uppercase; }
.vm .vm-v { font-size: 15px; margin-top: 3px; color: var(--ink-2); }

/* confidence ring */
#conf-wrap { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 26px; gap: 14px; }
#conf-ring { position: relative; width: 190px; height: 190px; }
#conf-ring svg { transform: rotate(-90deg); }
#conf-ring .ring-bg { stroke: var(--line); }
#conf-ring .ring-val { stroke: var(--gold); stroke-linecap: round; transition: stroke-dashoffset 1.2s var(--ease), stroke 0.6s; filter: drop-shadow(0 0 6px rgba(217,164,65,0.35)); }
#conf-num { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
#conf-num .big { font-family: var(--display); font-size: 46px; line-height: 1; color: var(--ink); }
#conf-num .cap { font-size: 9px; letter-spacing: 0.26em; color: var(--dim); margin-top: 6px; text-transform: uppercase; }
#conf-note { font-size: 10px; color: var(--dim); text-align: center; max-width: 220px; letter-spacing: 0.06em; }

/* thesis */
#thesis-panel .panel-body { font-size: 13px; color: var(--ink-2); line-height: 1.75; }
#thesis-panel .ev-row { display: flex; gap: 22px; margin-top: 18px; padding-top: 14px; border-top: 1px dashed var(--line); }
#thesis-panel .ev-count { font-size: 10px; letter-spacing: 0.14em; color: var(--dim); text-transform: uppercase; }
#thesis-panel .ev-count b { font-size: 16px; display: block; font-weight: 600; }

/* ============ MODE EXECUTION BOARD ============ */
#modes-board { margin-top: 28px; }
#modes-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 14px; flex-wrap: wrap; }
#modes-head .mh-title { font-size: 11px; letter-spacing: 0.26em; text-transform: uppercase; color: var(--ink-2); }
#modes-head .mh-note { font-size: 9px; letter-spacing: 0.16em; color: var(--faint); text-transform: uppercase; }
#lanes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

.lane { border: 1px solid var(--line); background: var(--panel); position: relative; overflow: hidden; transition: border-color 0.4s, transform 0.4s var(--ease); }
.lane:hover { transform: translateY(-3px); }
.lane-top { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--line-soft); }
.lane-mode { font-family: var(--display); font-size: 17px; letter-spacing: 0.1em; color: var(--ink-2); }
.lane-badge { font-size: 9px; letter-spacing: 0.22em; padding: 4px 10px; border: 1px solid var(--line); color: var(--dim); text-transform: uppercase; }
.lane.is-wait .lane-badge { color: var(--wait); border-color: rgba(138,143,152,0.35); }
.lane.is-live { border-color: rgba(217,164,65,0.55); box-shadow: 0 0 34px rgba(217,164,65,0.07) inset; }
.lane.is-live .lane-badge { color: var(--gold-bright); border-color: var(--gold); background: var(--gold-dim); }
.lane.is-live::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
  animation: sweep 2.6s ease-in-out infinite;
}
@keyframes sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
.lane-body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 8px; min-height: 118px; }
.lane-reason { font-size: 11px; color: var(--dim); line-height: 1.55; }
.lane-levels { display: grid; grid-template-columns: 1fr 1fr; gap: 7px 14px; margin-top: 4px; }
.lv { display: flex; justify-content: space-between; border-bottom: 1px dotted var(--line-soft); padding: 3px 0; }
.lv .lv-k { font-size: 9px; letter-spacing: 0.18em; color: var(--faint); text-transform: uppercase; }
.lv .lv-v { font-size: 11px; color: var(--ink-2); }
.lv .lv-v.entry { color: var(--gold-bright); }
.lv .lv-v.tp { color: var(--bull); }
.lv .lv-v.sl { color: var(--bear); }
.lane-foot { font-size: 9px; letter-spacing: 0.14em; color: var(--faint); text-transform: uppercase; margin-top: auto; padding-top: 8px; }
.lane.is-wait .conservative { color: var(--wait); }

/* ============ ACT II — SIGNAL ============ */
#signal-grid { display: grid; grid-template-columns: 1.1fr 1fr; gap: 24px; align-items: stretch; }
#constellation-wrap { position: relative; height: 420px; }
#constellation { position: absolute; inset: 0; width: 100%; height: 100%; }
#const-legend { position: absolute; left: 14px; bottom: 10px; font-size: 9px; letter-spacing: 0.14em; color: var(--faint); text-transform: uppercase; }
#regime-strip { position: absolute; top: 12px; right: 14px; font-size: 10px; letter-spacing: 0.2em; color: var(--gold); text-transform: uppercase; }

#engine-list { display: flex; flex-direction: column; }
.engine-row { border-bottom: 1px solid var(--line-soft); }
.engine-row:last-child { border-bottom: none; }
.engine-head {
  display: grid; grid-template-columns: 110px 60px 66px 1fr 52px 16px; gap: 12px; align-items: center;
  padding: 11px 16px; cursor: pointer; transition: background 0.25s; width: 100%;
  background: none; border: none; color: inherit; font: inherit; text-align: left;
}
.engine-head:hover { background: rgba(255,255,255,0.02); }
.engine-name { font-size: 10px; letter-spacing: 0.2em; color: var(--ink-2); text-transform: uppercase; }
.engine-score { font-size: 13px; font-weight: 600; }
/* Engine bias chip: real persisted analyst direction, never inferred from score. */
.bias-chip {
  font-size: 8px; letter-spacing: 0.14em; text-transform: uppercase; text-align: center;
  padding: 2px 0; border: 1px solid var(--line); color: var(--dim); white-space: nowrap;
}
.bias-chip.bull { color: var(--bull); border-color: rgba(76,195,138,0.5); }
.bias-chip.bear { color: var(--bear); border-color: rgba(229,72,77,0.5); }
.bias-chip.dimc { color: var(--dim); border-style: dashed; }
.engine-bar { height: 3px; background: var(--line-soft); position: relative; overflow: hidden; }
.engine-bar i { position: absolute; inset: 0; right: auto; background: var(--gold); transition: width 1s var(--ease); }
.engine-meta { font-size: 9px; color: var(--faint); letter-spacing: 0.1em; text-align: right; }
.engine-caret { color: var(--faint); transition: transform 0.3s; font-size: 10px; }
.engine-row.open .engine-caret { transform: rotate(90deg); color: var(--gold); }
.engine-detail { display: none; padding: 4px 18px 16px; }
.engine-row.open .engine-detail { display: block; }
.ev-item { display: flex; gap: 10px; padding: 6px 0; border-bottom: 1px dotted var(--line-soft); font-size: 11px; }
.ev-item:last-child { border-bottom: none; }
.ev-tag { font-size: 8px; letter-spacing: 0.18em; padding: 2px 7px; height: fit-content; margin-top: 2px; text-transform: uppercase; white-space: nowrap; }
.ev-tag.for { color: var(--bull); border: 1px solid rgba(76,195,138,0.4); }
.ev-tag.against { color: var(--bear); border: 1px solid rgba(229,72,77,0.4); }
.ev-tag.fact { color: var(--info); border: 1px solid rgba(90,167,214,0.4); }
.ev-desc { color: var(--ink-2); line-height: 1.5; }
.ev-src { color: var(--faint); font-size: 9px; margin-top: 2px; letter-spacing: 0.08em; }

/* ============ ACT III — PRESSURE ============ */
#pressure-grid { display: grid; grid-template-columns: 1fr 1.25fr 1fr; gap: 20px; }
#pb-gauge { display: flex; flex-direction: column; align-items: center; padding: 24px 18px 18px; }
#pb-dial { position: relative; width: 200px; height: 110px; }
#pb-needle {
  position: absolute; left: 50%; bottom: 4px; width: 2px; height: 88px;
  background: linear-gradient(to top, var(--gold), transparent);
  transform-origin: bottom center; transform: rotate(-90deg);
  transition: transform 1.3s var(--ease);
}
#pb-score-big { font-family: var(--display); font-size: 40px; margin-top: 10px; }
#pb-level { font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; margin-top: 2px; }
#pb-drivers { margin: 14px 0 0; padding: 0; list-style: none; width: 100%; }
#pb-drivers li { font-size: 11px; color: var(--ink-2); padding: 6px 0 6px 16px; border-bottom: 1px dotted var(--line-soft); position: relative; line-height: 1.5; }
#pb-drivers li::before { content: '›'; position: absolute; left: 2px; color: var(--warn); }
#pb-warnings li::before { content: '!'; color: var(--bear); font-weight: 700; }

#committee-list { display: flex; flex-direction: column; gap: 10px; }
.vote-row { display: grid; grid-template-columns: 130px 1fr 54px; gap: 12px; align-items: center; }
.vote-name { font-size: 10px; letter-spacing: 0.14em; color: var(--ink-2); text-transform: uppercase; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vote-bar { height: 16px; background: var(--line-soft); position: relative; overflow: hidden; }
.vote-bar i { position: absolute; top: 0; bottom: 0; left: 50%; background: var(--bull-dim); border-right: 1px solid var(--bull); transition: width 0.9s var(--ease), background 0.4s, border-color 0.4s; }
.vote-bar i.neg { left: auto; right: 50%; border-right: none; border-left: 1px solid var(--bear); background: var(--bear-dim); }
.vote-bar .mid { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--line); }
.vote-val { font-size: 11px; text-align: right; }
#committee-meta { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line); font-size: 10px; color: var(--dim); letter-spacing: 0.08em; line-height: 1.8; }
#committee-meta b { color: var(--ink-2); font-weight: 400; }

#invalidation-list, #risk-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 9px; }
#invalidation-list li, #risk-list li { font-size: 11px; color: var(--ink-2); line-height: 1.55; padding-left: 16px; position: relative; }
#invalidation-list li::before { content: '×'; position: absolute; left: 0; color: var(--bear); }
.risk-sev { font-size: 8px; letter-spacing: 0.16em; text-transform: uppercase; margin-left: 8px; }
.risk-sev.high { color: var(--bear); } .risk-sev.medium { color: var(--warn); } .risk-sev.low { color: var(--bull); }
/* CRITICAL severity must be unmistakable: filled alarm chip with an alert pulse. */
.risk-sev.critical {
  color: #FF7A7E; background: rgba(229,72,77,0.3); border: 1px solid var(--bear);
  padding: 2px 7px; margin-left: 8px; font-weight: 700;
  animation: criticalpulse 1.6s ease-in-out infinite;
}
@keyframes criticalpulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(229,72,77,0.4); } 50% { box-shadow: 0 0 14px 2px rgba(229,72,77,0.55); } }
#why-blocks { margin-top: 16px; display: grid; gap: 10px; }
.why-block { border-left: 2px solid var(--line); padding: 6px 0 6px 12px; }
.why-block .wk { font-size: 9px; letter-spacing: 0.2em; color: var(--faint); text-transform: uppercase; }
.why-block .wv { font-size: 11px; color: var(--dim); line-height: 1.55; margin-top: 3px; }

/* ============ ACT IV — GEOMETRY (price corridor) ============ */
#corridor-stage {
  position: relative; height: 380px; perspective: 900px; overflow: hidden;
  background: radial-gradient(80% 90% at 50% 100%, rgba(217,164,65,0.05), transparent 60%);
}
#corridor-planes { position: absolute; inset: 0; transform-style: preserve-3d; transform: rotateX(24deg); }
.c-plane {
  position: absolute; left: 6%; right: 6%; height: 0; border-top: 1px dashed var(--faint);
  transform-style: preserve-3d; transition: transform 1s var(--ease), opacity 1s;
}
.c-plane .c-label {
  position: absolute; right: 0; top: -16px; font-size: 10px; letter-spacing: 0.14em;
  display: flex; gap: 10px; align-items: baseline; background: var(--void); padding: 0 8px;
}
.c-plane .c-price { font-weight: 600; }
.c-plane.pl-spot { border-top: 1px solid var(--gold); }
.c-plane.pl-spot .c-label { color: var(--gold-bright); }
.c-plane.pl-entry { border-top: 1px dashed var(--warn); } .c-plane.pl-entry .c-label { color: var(--warn); }
.c-plane.pl-tp { border-top: 1px dashed var(--bull); } .c-plane.pl-tp .c-label { color: var(--bull); }
.c-plane.pl-sl { border-top: 1px dashed var(--bear); } .c-plane.pl-sl .c-label { color: var(--bear); }
.c-plane.pl-sr { border-top: 1px dashed var(--faint); opacity: 0.75; } .c-plane.pl-sr .c-label { color: var(--dim); }
#corridor-note { position: absolute; left: 0; right: 0; bottom: 12px; text-align: center; font-size: 10px; letter-spacing: 0.22em; color: var(--dim); text-transform: uppercase; }
#corridor-side { display: flex; flex-direction: column; gap: 10px; }
#geometry-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 22px; }
.geo-stat { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px dotted var(--line-soft); font-size: 11px; }
.geo-stat .gk { color: var(--faint); font-size: 9px; letter-spacing: 0.18em; text-transform: uppercase; }
.geo-stat .gv { color: var(--ink-2); }

/* ============ ACT V — MEMORY (history depth ribbon) ============ */
#memory-scene { perspective: 700px; overflow-x: auto; overflow-y: hidden; padding: 30px 4px 26px; }
#memory-track { display: flex; gap: 14px; transform-style: preserve-3d; width: max-content; }
.mem-card {
  min-width: 168px; border: 1px solid var(--line); background: var(--panel-solid);
  padding: 12px 14px; transform-style: preserve-3d; transition: transform 0.5s var(--ease), border-color 0.4s;
}
.mem-card:hover { transform: translateZ(26px) !important; border-color: var(--gold); }
.mem-card .mc-time { font-size: 9px; letter-spacing: 0.14em; color: var(--faint); }
.mem-card .mc-act { font-family: var(--display); font-size: 22px; margin: 4px 0 2px; }
.mem-card .mc-meta { font-size: 10px; color: var(--dim); display: flex; gap: 10px; }
#memory-stats { display: flex; gap: 34px; margin-bottom: 8px; flex-wrap: wrap; }
.mem-stat .ms-v { font-family: var(--display); font-size: 30px; color: var(--ink); }
.mem-stat .ms-k { font-size: 9px; letter-spacing: 0.22em; color: var(--faint); text-transform: uppercase; margin-top: 2px; }

/* ============ ACT VI — TELEMETRY ============ */
#telemetry-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.tele-counts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.tele-cell { border: 1px solid var(--line-soft); padding: 12px; }
.tele-cell .tc-v { font-family: var(--display); font-size: 24px; color: var(--ink); }
.tele-cell .tc-k { font-size: 8px; letter-spacing: 0.2em; color: var(--faint); text-transform: uppercase; margin-top: 3px; }
#engine-runtimes .rt-row { display: flex; justify-content: space-between; font-size: 11px; padding: 5px 0; border-bottom: 1px dotted var(--line-soft); }
#engine-runtimes .rt-row:last-child { border-bottom: none; }
#decision-stamp { font-size: 10px; letter-spacing: 0.1em; color: var(--dim); line-height: 2; }
#decision-stamp b { color: var(--ink-2); font-weight: 400; }

/* ============ FOOTER ============ */
#colophon { text-align: center; padding: 60px 20px 46px; color: var(--faint); font-size: 9px; letter-spacing: 0.26em; text-transform: uppercase; position: relative; z-index: 2; }

/* ============ STALE FOG ============ */
body.is-stale #stage { filter: saturate(0.55) brightness(0.88); }
body.is-stale #stale-stamp { display: block; }
#stale-stamp {
  display: none; position: fixed; top: 66px; right: 16px; z-index: 70;
  pointer-events: none;
  border: 1px solid var(--warn); color: var(--warn); padding: 6px 14px;
  font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase;
  background: rgba(5,6,8,0.8); transform: rotate(2deg);
}

/* value decode flash */
.flash { animation: vflash 0.7s var(--ease); }
@keyframes vflash { 0% { color: var(--gold-bright); text-shadow: 0 0 14px rgba(240,196,99,0.5); } 100% { } }

/* ============ RESPONSIVE ============ */
@media (max-width: 1080px) {
  #verdict-grid, #signal-grid, #geometry-grid { grid-template-columns: 1fr; }
  #pressure-grid, #telemetry-grid { grid-template-columns: 1fr 1fr; }
  #lanes { grid-template-columns: 1fr; }
  .act { padding: 70px 22px 30px; }
}
@media (max-width: 720px) {
  #pressure-grid, #telemetry-grid { grid-template-columns: 1fr; }
  #rail { height: auto; flex-wrap: wrap; }
  .rail-cell { border-right: none; padding: 8px 12px; }
  #rail-nav { width: 100%; overflow-x: auto; }
  #stage { padding-top: 96px; }
  #verdict-word { font-size: clamp(52px, 15vw, 90px); }
  .engine-head { grid-template-columns: 92px 44px 56px 1fr 16px; }
  .engine-bar { display: none; }
  .engine-meta { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  html { scroll-behavior: auto; }
  .act { opacity: 1; transform: none; }
}
</style>
</head>
<body>
""" + """
<!-- ============ BOOT VEIL ============ -->
<div id="veil">
  <div class="glyph">⬡</div>
  <div class="v-title serif">MIOS AURUM</div>
  <div class="v-sub">Calibrating instruments…</div>
</div>

<!-- ============ EMPTY STATE ============ -->
<div id="empty-state" class="hidden">
  <div class="e-ring">⬡</div>
  <div class="e-title serif">The observatory is dark</div>
  <div class="e-sub dimc">No decision exists in the journal yet. Run one intelligence cycle and the theatre will come alive.</div>
  <div class="e-cmd">No decision yet — Run: python -m app.main run-once</div>
</div>

<div id="stale-stamp">Decision stale — awaiting new cycle</div>

<!-- ============ COMMAND RAIL ============ -->
<div id="rail">
  <div class="rail-cell"><span class="brand serif">MIOS <b>//</b> AURUM</span></div>
  <div class="rail-cell"><span class="rail-k">XAU/USD</span><span class="rail-v" id="rail-spot">--</span></div>
  <div class="rail-cell"><div id="rail-live"><span class="dot"></span><span id="rail-live-txt">--</span></div></div>
  <div class="rail-cell"><span class="rail-k">Decision</span><span class="rail-v" id="rail-time">--</span></div>
  <div class="rail-cell grow">
    <span id="provider-strip" title="Provider status">PROVIDERS --</span>
    <div id="provider-detail"></div>
    <nav id="rail-nav">
      <a href="#act-verdict" data-act="act-verdict" class="active">Verdict</a>
      <a href="#act-signal" data-act="act-signal">Signal</a>
      <a href="#act-pressure" data-act="act-pressure">Pressure</a>
      <a href="#act-geometry" data-act="act-geometry">Geometry</a>
      <a href="#act-memory" data-act="act-memory">Memory</a>
      <a href="#act-telemetry" data-act="act-telemetry">Telemetry</a>
    </nav>
  </div>
</div>

<div id="stage">

<!-- ================= ACT I — VERDICT ================= -->
<section class="act" id="act-verdict">
  <div class="act-head">
    <span class="act-no">I</span>
    <div><div class="act-title serif">Verdict</div><div class="act-sub">Canonical outlook — what MIOS currently believes</div></div>
    <div class="act-rule"></div>
  </div>

  <div id="verdict-grid">
    <div class="panel">
      <div class="verdict-word-wrap">
        <div class="verdict-kicker"><b>CANONICAL OUTLOOK</b> · delivered, not executed · decision support only</div>
        <h1 id="verdict-word" class="serif is-wait">--</h1>
        <div id="verdict-meta">
          <div class="vm"><div class="vm-k">Regime</div><div class="vm-v" id="v-regime">--</div></div>
          <div class="vm"><div class="vm-k">Expected move</div><div class="vm-v" id="v-move">--</div></div>
          <div class="vm"><div class="vm-k">Horizon</div><div class="vm-v" id="v-horizon">--</div></div>
          <div class="vm"><div class="vm-k">Opportunity</div><div class="vm-v" id="v-opp">--</div></div>
        </div>
      </div>
      <div class="panel-body" id="thesis-panel" style="border-top:1px solid var(--line-soft);">
        <div class="panel-title" style="padding:0 0 10px;border:none;">Thesis — REASON for the call</div>
        <div id="thesis-text" class="dimc">Awaiting decision…</div>
        <div class="ev-row">
          <div class="ev-count"><b id="ev-for-n" class="bull">0</b> supporting</div>
          <div class="ev-count"><b id="ev-against-n" class="bear">0</b> contradicting</div>
          <div class="ev-count"><b id="ev-risk-n" class="warn">0</b> risks tracked</div>
        </div>
      </div>
    </div>

    <div class="panel" id="conf-wrap">
      <div class="panel-title" style="align-self:stretch;">Conviction</div>
      <div id="conf-ring">
        <svg width="190" height="190" viewBox="0 0 190 190">
          <circle class="ring-bg" cx="95" cy="95" r="82" fill="none" stroke-width="2"/>
          <circle class="ring-val" id="conf-arc" cx="95" cy="95" r="82" fill="none" stroke-width="3"
                  stroke-dasharray="515.2" stroke-dashoffset="515.2"/>
        </svg>
        <div id="conf-num"><span class="big serif" id="conf-val">--</span><span class="cap">% confidence</span></div>
      </div>
      <div id="conf-note">Posterior conviction after engine weighting, evidence penalties and committee adjustment.</div>
    </div>
  </div>

  <!-- MODE EXECUTION BOARD -->
  <div id="modes-board">
    <div id="modes-head">
      <span class="mh-title">Mode execution status</span>
      <span class="mh-note">Distinct from the canonical outlook — each mode decides independently</span>
    </div>
    <div id="lanes">
      <div class="lane is-wait" id="lane-physical">
        <div class="lane-top"><span class="lane-mode serif">Physical</span><span class="lane-badge">--</span></div>
        <div class="lane-body"><div class="lane-reason">Awaiting policy data</div></div>
      </div>
      <div class="lane is-wait" id="lane-forex">
        <div class="lane-top"><span class="lane-mode serif">Forex</span><span class="lane-badge">--</span></div>
        <div class="lane-body"><div class="lane-reason">Awaiting policy data</div></div>
      </div>
      <div class="lane is-wait" id="lane-etf">
        <div class="lane-top"><span class="lane-mode serif">ETF</span><span class="lane-badge">--</span></div>
        <div class="lane-body"><div class="lane-reason">Awaiting policy data</div></div>
      </div>
    </div>
  </div>
</section>

<!-- ================= ACT II — SIGNAL ================= -->
<section class="act" id="act-signal">
  <div class="act-head">
    <span class="act-no">II</span>
    <div><div class="act-title serif">Signal</div><div class="act-sub">What the deterministic engines heard</div></div>
    <div class="act-rule"></div>
  </div>

  <div id="signal-grid">
    <div class="panel">
      <div class="panel-title">Engine constellation — node size = score · hue = persisted analyst bias · outline = bias not on record</div>
      <div id="constellation-wrap">
        <canvas id="constellation"></canvas>
        <div id="regime-strip">REGIME --</div>
        <div id="const-legend">TECH · MACRO · INST · NEWS · GEO · REGIME</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-title">Engine ledger — expand for evidence</div>
      <div id="engine-list"></div>
    </div>
  </div>
</section>

<!-- ================= ACT III — PRESSURE ================= -->
<section class="act" id="act-pressure">
  <div class="act-head">
    <span class="act-no">III</span>
    <div><div class="act-title serif">Pressure</div><div class="act-sub">What challenges the thesis — and what would break it</div></div>
    <div class="act-rule"></div>
  </div>

  <div id="pressure-grid">
    <div class="panel">
      <div class="panel-title">Pullback risk pressure</div>
      <div id="pb-gauge">
        <div id="pb-dial">
          <svg width="200" height="110" viewBox="0 0 200 110">
            <path d="M 12 104 A 88 88 0 0 1 188 104" fill="none" stroke="var(--line)" stroke-width="2"/>
            <path d="M 12 104 A 88 88 0 0 1 100 16" fill="none" stroke="rgba(76,195,138,0.35)" stroke-width="2"/>
            <path d="M 100 16 A 88 88 0 0 1 160 32" fill="none" stroke="rgba(224,163,62,0.4)" stroke-width="2"/>
            <path d="M 160 32 A 88 88 0 0 1 188 104" fill="none" stroke="rgba(229,72,77,0.45)" stroke-width="2"/>
          </svg>
          <div id="pb-needle"></div>
        </div>
        <div id="pb-score-big" class="serif">--</div>
        <div id="pb-level" class="dimc">--</div>
        <ul id="pb-drivers"></ul>
        <ul id="pb-warnings" style="margin:6px 0 0; padding:0; list-style:none; width:100%;"></ul>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">Adversarial committee — the counter-argument</div>
      <div class="panel-body">
        <div id="committee-list"></div>
        <div id="committee-meta"></div>
      </div>
    </div>

    <div style="display:flex; flex-direction:column; gap:20px;">
      <div class="panel">
        <div class="panel-title">What breaks the thesis</div>
        <div class="panel-body"><ul id="invalidation-list"><li class="dimc">--</li></ul></div>
      </div>
      <div class="panel">
        <div class="panel-title">Risk register</div>
        <div class="panel-body"><ul id="risk-list"><li class="dimc">--</li></ul></div>
      </div>
      <div class="panel" id="why-panel" style="display:none;">
        <div class="panel-title">Decision trace — withheld sides</div>
        <div class="panel-body"><div id="why-blocks"></div></div>
      </div>
    </div>
  </div>
</section>

<!-- ================= ACT IV — GEOMETRY ================= -->
<section class="act" id="act-geometry">
  <div class="act-head">
    <span class="act-no">IV</span>
    <div><div class="act-title serif">Geometry</div><div class="act-sub">The trade space — only levels MIOS actually produced</div></div>
    <div class="act-rule"></div>
  </div>

  <div id="geometry-grid">
    <div class="panel">
      <div class="panel-title">Price corridor — perspective across persisted levels</div>
      <div id="corridor-stage">
        <div id="corridor-planes"></div>
        <div id="corridor-note">Awaiting decision…</div>
      </div>
    </div>
    <div class="panel" id="corridor-side">
      <div class="panel-title">Corridor readout</div>
      <div class="panel-body" id="geo-stats"><div class="dimc" style="font-size:11px;">No levels yet.</div></div>
    </div>
  </div>
</section>

<!-- ================= ACT V — MEMORY ================= -->
<section class="act" id="act-memory">
  <div class="act-head">
    <span class="act-no">V</span>
    <div><div class="act-title serif">Memory</div><div class="act-sub">How the mind changed — decisions receding into depth</div></div>
    <div class="act-rule"></div>
  </div>

  <div id="memory-stats"></div>
  <div class="panel">
    <div id="memory-scene"><div id="memory-track"><div class="dimc" style="font-size:11px; padding:20px;">No decisions recorded yet.</div></div></div>
  </div>
</section>

<!-- ================= ACT VI — TELEMETRY ================= -->
<section class="act" id="act-telemetry">
  <div class="act-head">
    <span class="act-no">VI</span>
    <div><div class="act-title serif">Telemetry</div><div class="act-sub">Pipeline, providers and the clock</div></div>
    <div class="act-rule"></div>
  </div>

  <div id="telemetry-grid">
    <div class="panel">
      <div class="panel-title">Pipeline counts</div>
      <div class="panel-body"><div class="tele-counts" id="tele-counts"></div></div>
    </div>
    <div class="panel">
      <div class="panel-title">Engine runtime</div>
      <div class="panel-body"><div id="engine-runtimes"><div class="dimc" style="font-size:11px;">--</div></div></div>
    </div>
    <div class="panel">
      <div class="panel-title">Decision stamp</div>
      <div class="panel-body"><div id="decision-stamp"><b>--</b></div></div>
    </div>
  </div>
</section>

</div>

<div id="colophon">MIOS // AURUM — decision support, not execution · deterministic engines + adversarial committee · gold intelligence</div>

<script>
/* ================================================================
   MIOS AURUM — runtime. Pure presentation over persisted payloads.
   No decision logic is recomputed here; every value is displayed
   exactly as the backend persisted it.
   ================================================================ */
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* Null-safe accessor: one missing optional node never aborts a render. */
const _missingEl = { textContent: '', innerHTML: '', className: '', style: {}, classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, getAttribute() { return null; } };
const el = id => document.getElementById(id) || _missingEl;

const escape = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

function biasClass(a) {
  const s = String(a ?? '').toUpperCase();
  if (s.includes('BUY') || s.includes('LONG') || s.includes('BULL')) return 'bull';
  if (s.includes('SELL') || s.includes('SHORT') || s.includes('BEAR')) return 'bear';
  return 'dimc';
}
function biasHex(a) {
  const s = String(a ?? '').toUpperCase();
  if (s.includes('BUY') || s.includes('LONG') || s.includes('BULL')) return getComputedStyle(document.documentElement).getPropertyValue('--bull').trim() || '#4CC38A';
  if (s.includes('SELL') || s.includes('SHORT') || s.includes('BEAR')) return getComputedStyle(document.documentElement).getPropertyValue('--bear').trim() || '#E5484D';
  return '#8A8F98';
}
function fmtAge(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
  return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
}
const fmt2 = v => (v === null || v === undefined || isNaN(parseFloat(v))) ? '--' : parseFloat(v).toFixed(2);

/* Value decode: write text, flash it when it changed. Data-driven motion only. */
const _prevVals = {};
function setVal(node, text) {
  const n = typeof node === 'string' ? el(node) : node;
  text = String(text ?? '--');
  if (_prevVals[n.textContent === undefined ? '' : ''] === undefined) { /* noop guard */ }
  const key = n.id || text;
  if (_prevVals[key] !== undefined && _prevVals[key] !== text && !REDUCED) {
    n.classList.remove('flash'); void n.offsetWidth; n.classList.add('flash');
  }
  _prevVals[key] = text;
  n.textContent = text;
}

const ENG_ORDER = ['technical', 'fundamental', 'institutional', 'news', 'geopolitical', 'market_regime'];
const ENG_LABEL = { technical: 'Technical', fundamental: 'Macro', institutional: 'Institutional', news: 'News/Sent', geopolitical: 'Geopolitical', market_regime: 'Regime' };
let ENGINE_STATE = ENG_ORDER.map(id => ({ id, score: null, confidence: null, status: null, runtime_ms: null, evidence: [], bias: null }));

let _historyKey; let _historyCache = null;
let POLL_FAILS = 0;

async function loadData() {
  try {
    const [latestRes, policiesRes, researchRes, traceRes, providerRes, healthRes, backtestRes] = await Promise.all([
      fetch('/api/latest').then(r => r.json()).catch(() => null),
      fetch('/api/mode-policies').then(r => r.json()).catch(() => null),
      fetch('/api/research').then(r => r.json()).catch(() => null),
      fetch('/api/decision-trace').then(r => r.json()).catch(() => null),
      fetch('/api/provider-status').then(r => r.json()).catch(() => null),
      fetch('/api/health').then(r => r.json()).catch(() => null),
      fetch('/api/backtesting').then(r => r.json()).catch(() => null),
    ]);
    POLL_FAILS = 0;
    renderProviderStrip(providerRes);

    if (!latestRes || !latestRes.latest) {
      el('veil').classList.add('gone');
      el('empty-state').classList.remove('hidden');
      return;
    }
    el('empty-state').classList.add('hidden');
    const d = latestRes.latest;

    /* History carries full serialized reports: refetch only when the decision changes. */
    let historyRes = _historyCache;
    if (d.timestamp !== _historyKey) {
      _historyKey = d.timestamp;
      historyRes = await fetch('/api/history').then(r => r.json()).catch(() => null);
      _historyCache = historyRes;
    }

    renderRail(d, latestRes.freshness);
    renderVerdict(d);
    renderLanes(policiesRes?.policies || d.mode_policy_results || []);
    ingestEngines(d, healthRes, researchRes);
    renderConstellationTargets(researchRes);
    renderEngineLedger();
    renderPressure(d, researchRes, traceRes);
    renderGeometry(d, policiesRes?.policies || d.mode_policy_results || []);
    renderMemory(historyRes, backtestRes);
    renderTelemetry(d, healthRes);
    el('veil').classList.add('gone');
  } catch (e) {
    POLL_FAILS += 1;
    if (POLL_FAILS === 1) el('rail-time').textContent = 'API unreachable — retrying';
    el('veil').classList.add('gone');
  }
}

/* ============ RAIL: freshness, spot, clock ============ */
function renderRail(d, fr) {
  if (d.spot_price) setVal('rail-spot', fmt2(d.spot_price));
  const live = el('rail-live');
  if (fr) {
    document.body.classList.toggle('is-stale', !fr.fresh);
    setVal('rail-live-txt', fr.fresh ? 'LIVE' : 'STALE');
    if (live.classList) live.classList.toggle('is-stale', !fr.fresh);
    setVal('rail-time', String(fr.timestamp).replace('T', ' ').substring(0, 16) + 'Z · age ' + fmtAge(fr.age_seconds));
  } else {
    setVal('rail-live-txt', '--');
    setVal('rail-time', '--');
  }
}

/* ============ ACT I — VERDICT ============ */
function renderVerdict(d) {
  const rec = d.recommendation?.name || d.recommendation || '--';
  const word = el('verdict-word');
  setVal(word, String(rec).toUpperCase());
  word.classList.remove('is-bull', 'is-bear', 'is-wait');
  word.classList.add(biasClass(rec) === 'bull' ? 'is-bull' : (biasClass(rec) === 'bear' ? 'is-bear' : 'is-wait'));

  setVal('v-regime', d.market_regime?.name || d.market_regime || '--');
  setVal('v-horizon', d.expected_holding_period || '--');
  setVal('v-opp', (d.opportunity_score ?? '--') + ' / 100');

  let moveStr = '--';
  if (d.expected_move) {
    const em = d.expected_move;
    if (em.min_usd !== null && em.min_usd !== undefined) {
      const sign = (em.direction === 'UP' || em.direction === 'BULLISH') ? '+' : ((em.direction === 'DOWN' || em.direction === 'BEARISH') ? '-' : '');
      moveStr = sign + '$' + fmt2(em.min_usd);
      if (em.max_usd !== null && em.max_usd !== undefined) moveStr += ' → $' + fmt2(em.max_usd);
    } else moveStr = em.summary || em.direction;
  }
  setVal('v-move', moveStr);

  setVal('thesis-text', d.explanation || 'No explanation persisted.');
  setVal('ev-for-n', (d.supporting_evidence || []).length);
  setVal('ev-against-n', (d.contradicting_evidence || []).length);
  setVal('ev-risk-n', (d.risk_summary || []).length);

  /* confidence ring */
  const conf = d.confidence ?? 0;
  const CIRC = 515.2;
  el('conf-arc').style.strokeDashoffset = String(CIRC * (1 - conf / 100));
  el('conf-arc').style.stroke = biasHex(rec);
  setVal('conf-val', String(conf));
}

/* ============ MODE LANES — WAIT-safe ============ */
function renderLanes(policies) {
  ['physical', 'forex', 'etf'].forEach(mode => {
    const lane = el('lane-' + mode);
    const p = policies.find(x => x.mode === mode);
    if (!p) {
      lane.innerHTML = '<div class="lane-top"><span class="lane-mode serif">' + mode.charAt(0).toUpperCase() + mode.slice(1) + '</span><span class="lane-badge">--</span></div><div class="lane-body"><div class="lane-reason">Awaiting policy data</div></div>';
      lane.className = 'lane is-wait';
      return;
    }
    const action = String(p.action || 'WAIT').toUpperCase();
    const isWait = !!p.is_wait || action === 'WAIT';
    lane.className = 'lane ' + (isWait ? 'is-wait' : 'is-live');
    const badgeCls = isWait ? '' : ' style="color:' + biasHex(action) + ';border-color:' + biasHex(action) + '"';

    let body;
    if (!isWait && p.actionable && p.entry) {
      /* Actionable mode: show the persisted trade parameters. */
      body = '<div class="lane-levels">'
        + '<div class="lv"><span class="lv-k">Entry</span><span class="lv-v entry">' + fmt2(p.entry) + '</span></div>'
        + '<div class="lv"><span class="lv-k">Take profit</span><span class="lv-v tp">' + fmt2(p.take_profit) + '</span></div>'
        + '<div class="lv"><span class="lv-k">Stop loss</span><span class="lv-v sl">' + fmt2(p.stop_loss) + '</span></div>'
        + '<div class="lv"><span class="lv-k">Risk</span><span class="lv-v">' + escape(p.risk || '--') + '</span></div>'
        + '<div class="lv"><span class="lv-k">Horizon</span><span class="lv-v">' + escape(p.horizon || '--') + '</span></div>'
        + '<div class="lv"><span class="lv-k">Allocate</span><span class="lv-v">' + escape(p.allocation || '--') + '</span></div>'
        + '</div>'
        + '<div class="lane-reason" style="margin-top:8px;">' + escape(p.reason || '') + '</div>';
    } else {
      /* WAIT: reason + conservative guidance only. Never show trade levels. */
      body = '<div class="lane-reason">' + escape(p.reason || 'Holding.') + '</div>'
        + '<div class="lv"><span class="lv-k">Allocation</span><span class="lv-v">' + escape(p.allocation || (mode === 'forex' ? 'Flat' : 'Maintain')) + '</span></div>'
        + '<div class="lane-reason conservative">Conservative posture — no trade parameters while WAIT.</div>';
    }
    lane.innerHTML = '<div class="lane-top"><span class="lane-mode serif">' + mode.charAt(0).toUpperCase() + mode.slice(1) + '</span>'
      + '<span class="lane-badge"' + badgeCls + '>' + escape(action) + '</span></div>'
      + '<div class="lane-body">' + body + '<div class="lane-foot">Confidence ' + (p.confidence ?? '--') + ' · move ' + escape(p.expected_move || '--') + '</div></div>';
  });
}

/* ============ ACT II — SIGNAL ============ */
/* Only roles with an unambiguous engine attribution are mapped. Direction is
   read from the persisted analyst recommendation — never inferred from score. */
const ROLE_ENGINE = {
  technical_analyst: 'technical',
  news_analyst: 'news',
  geopolitical_analyst: 'geopolitical',
  institutional_analyst: 'institutional'
};
function extractEngineBias(researchRes, d) {
  const bias = {};
  const reports = researchRes?.research?.analyst_reports || d.research_desk_report?.analyst_reports || [];
  reports.forEach(r => {
    const eng = ROLE_ENGINE[String(r.role || '')];
    if (!eng || bias[eng]) return;
    const rec = String(r.recommendation?.name || r.recommendation || '').toUpperCase();
    bias[eng] = rec || null;
  });
  return bias;
}
function ingestEngines(d, healthRes, researchRes) {
  const byId = {};
  (d.engine_breakdown || []).forEach(b => { byId[b.engine?.value || b.engine] = b; });
  const hRt = {};
  ((healthRes && healthRes.engines) || []).forEach(h => { hRt[h.engine] = h.runtime_ms; });
  const bias = extractEngineBias(researchRes, d);
  ENGINE_STATE = ENG_ORDER.map(id => {
    const b = byId[id] || {};
    return { id, score: b.score ?? null, confidence: b.confidence ?? null, status: b.status || null, runtime_ms: b.runtime_ms ?? hRt[id] ?? null, evidence: b.evidence || [], bias: bias[id] || null };
  });
}

function renderEngineLedger() {
  const open = new Set(Array.from(document.querySelectorAll('.engine-row.open')).map(r => r.dataset.eng));
  let html = '';
  ENGINE_STATE.forEach(eng => {
    const score = eng.score === null ? '--' : eng.score;
    /* Score is a magnitude: always neutral gold. Direction lives in the bias chip. */
    const biasCls = eng.bias ? biasClass(eng.bias) : 'dimc';
    const biasTxt = eng.bias ? escape(eng.bias) : '—';
    const st = eng.status && eng.status !== 'SUCCESS' ? ' · ' + escape(eng.status) : '';
    let evHtml = '';
    (eng.evidence || []).slice(0, 8).forEach(ev => {
      const cat = String(ev.category || '').toUpperCase();
      const tagCls = cat.includes('CONTRADICT') || cat.includes('AGAINST') || cat.includes('BEAR') ? 'against' : (cat.includes('SUPPORT') || cat.includes('FOR') || cat.includes('BULL') ? 'for' : 'fact');
      evHtml += '<div class="ev-item"><span class="ev-tag ' + tagCls + '">' + escape(cat || 'EVIDENCE') + '</span>'
        + '<div><div class="ev-desc">' + escape(ev.description || '') + '</div>'
        + '<div class="ev-src">' + escape(ev.source || '') + ' · strength ' + escape(ev.strength || '--') + ' · conf ' + (ev.confidence ?? '--') + '</div></div></div>';
    });
    if (!evHtml) evHtml = '<div class="dimc" style="font-size:11px;">No evidence persisted for this engine.</div>';
    html += '<div class="engine-row' + (open.has(eng.id) ? ' open' : '') + '" data-eng="' + eng.id + '">'
      + '<button class="engine-head" type="button" aria-expanded="' + (open.has(eng.id) ? 'true' : 'false') + '">'
      + '<span class="engine-name">' + (ENG_LABEL[eng.id] || eng.id) + '</span>'
      + '<span class="engine-score" style="color:var(--ink-2)">' + score + '</span>'
      + '<span class="bias-chip ' + biasCls + '" title="Persisted analyst bias — score is magnitude, not direction">' + biasTxt + '</span>'
      + '<span class="engine-bar"><i style="width:' + (eng.score === null ? 0 : eng.score) + '%"></i></span>'
      + '<span class="engine-meta">' + (eng.runtime_ms === null ? '--' : eng.runtime_ms + 'ms') + st + '</span>'
      + '<span class="engine-caret">▸</span></button>'
      + '<div class="engine-detail">' + evHtml + '</div></div>';
  });
  el('engine-list').innerHTML = html;
  document.querySelectorAll('.engine-head').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.engine-row').classList.toggle('open'));
  });
}

/* Canvas constellation: node radius = score magnitude, hue = persisted analyst bias, pulse = confidence. */
const CONST = { canvas: null, ctx: null, targets: [], t: 0, raf: null };
function renderConstellationTargets(researchRes) {
  setVal('regime-strip', 'REGIME ' + String(document.getElementById('v-regime')?.textContent || '--'));
  CONST.targets = ENGINE_STATE.map((eng, i) => {
    const angle = -Math.PI / 2 + i * (Math.PI * 2 / ENGINE_STATE.length);
    return { eng, angle, phase: i * 0.9 };
  });
  if (!CONST.canvas) initConstellation();
}
function initConstellation() {
  CONST.canvas = document.getElementById('constellation');
  if (!CONST.canvas) return;
  CONST.ctx = CONST.canvas.getContext('2d');
  const resize = () => {
    const r = CONST.canvas.parentElement.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    CONST.canvas.width = r.width * dpr; CONST.canvas.height = r.height * dpr;
    CONST.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  resize(); window.addEventListener('resize', resize);
  const tick = () => {
    CONST.raf = requestAnimationFrame(tick);
    if (document.hidden) return;
    drawConstellation();
  };
  if (REDUCED) drawConstellation(); else tick();
}
function drawConstellation() {
  const ctx = CONST.ctx, cv = CONST.canvas;
  if (!ctx || !cv) return;
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.36;
  CONST.t += REDUCED ? 0 : 0.016;
  const gold = 'rgba(217,164,65,';
  /* orbit ring */
  ctx.strokeStyle = 'rgba(27,32,41,0.9)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
  /* spokes + nodes */
  CONST.targets.forEach(t => {
    const x = cx + Math.cos(t.angle) * R, y = cy + Math.sin(t.angle) * R;
    const has = t.eng.score !== null;
    /* Hue = real persisted analyst bias. No bias on record -> hollow neutral node. */
    const col = t.eng.bias ? biasHex(t.eng.bias) : '#8A8F98';
    ctx.strokeStyle = 'rgba(86,96,116,0.5)';
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke();
    const base = has ? 4 + (t.eng.score / 100) * 10 : 3;
    const pulse = REDUCED || !has ? 1 : 1 + 0.14 * Math.sin(CONST.t * 2 + t.phase) * ((t.eng.confidence ?? 0) / 100);
    const rad = base * pulse;
    if (t.eng.bias) {
      ctx.save();
      ctx.globalAlpha = 0.22;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(x, y, rad * 2.6, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
    } else {
      /* No persisted bias: outline only — never colour a magnitude as direction. */
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.stroke();
      ctx.lineWidth = 1;
    }
    ctx.strokeStyle = 'rgba(236,231,219,0.18)';
    ctx.beginPath(); ctx.arc(x, y, rad + 4, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = 'rgba(183,178,166,0.9)';
    ctx.font = '9px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    const lx = cx + Math.cos(t.angle) * (R + 26), ly = cy + Math.sin(t.angle) * (R + 26);
    ctx.fillText((ENG_LABEL[t.eng.id] || t.eng.id).toUpperCase(), lx, ly);
    ctx.fillStyle = 'rgba(183,178,166,0.85)';
    ctx.fillText(has ? String(t.eng.score) : '--', lx, ly + 11);
  });
  /* center verdict core */
  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, 30);
  core.addColorStop(0, gold + '0.35)'); core.addColorStop(1, gold + '0)');
  ctx.fillStyle = core; ctx.beginPath(); ctx.arc(cx, cy, 30, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = gold + '0.7)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, 9, 0, Math.PI * 2); ctx.stroke();
}

/* ============ ACT III — PRESSURE ============ */
function renderPressure(d, researchRes, traceRes) {
  const pb = d.pullback_risk_report;
  if (pb) {
    setVal('pb-score-big', String(pb.score ?? '--'));
    const lvl = String(pb.level || '--').toUpperCase();
    setVal('pb-level', lvl);
    el('pb-level').style.color = lvl === 'LOW' ? 'var(--bull)' : (lvl === 'MEDIUM' ? 'var(--warn)' : 'var(--bear)');
    el('pb-score-big').style.color = el('pb-level').style.color;
    /* needle: score 0..100 maps to -90deg..+90deg */
    const deg = -90 + (Math.max(0, Math.min(100, pb.score || 0)) / 100) * 180;
    el('pb-needle').style.transform = 'rotate(' + deg + 'deg)';
    el('pb-drivers').innerHTML = (pb.drivers && pb.drivers.length)
      ? pb.drivers.slice(0, 5).map(x => '<li>' + escape(x) + '</li>').join('')
      : (pb.directional_context ? '<li>' + escape(pb.directional_context) + '</li>' : '<li class="dimc">No drivers persisted.</li>');
    el('pb-warnings').innerHTML = (pb.warnings && pb.warnings.length)
      ? pb.warnings.slice(0, 4).map(x => '<li>' + escape(x) + '</li>').join('') : '';
  } else {
    setVal('pb-score-big', '--'); setVal('pb-level', 'NO REPORT');
    el('pb-drivers').innerHTML = '<li class="dimc">No pullback report persisted.</li>';
  }

  /* committee */
  const cr = researchRes?.research?.committee_report || d.research_desk_report?.committee_report;
  const list = el('committee-list');
  if (cr && cr.committee_votes && cr.committee_votes.length) {
    list.innerHTML = cr.committee_votes.map(v => {
      const dir = String(v.direction || 'NEUTRAL').toUpperCase();
      const conf = Math.max(0, Math.min(1, v.confidence ?? 0));
      const neg = dir.includes('SELL') || dir.includes('SHORT') || dir.includes('BEAR');
      const neutral = !neg && !(dir.includes('BUY') || dir.includes('LONG') || dir.includes('BULL'));
      const widthPct = neutral ? 4 : conf * 46;
      return '<div class="vote-row"><span class="vote-name" title="' + escape(v.member_name || '') + '">' + escape(v.member_name || '--') + '</span>'
        + '<span class="vote-bar"><span class="mid"></span><i class="' + (neg ? 'neg' : '') + '" style="width:' + widthPct + '%"></i></span>'
        + '<span class="vote-val ' + biasClass(dir) + '">' + escape(dir) + ' ' + Math.round(conf * 100) + '%</span></div>';
    }).join('');
    const final = cr.final_recommendation?.name || cr.final_recommendation || '--';
    const usage = cr.usage || {};
    el('committee-meta').innerHTML = 'Consensus <b class="' + biasClass(final) + '">' + escape(String(final).toUpperCase()) + '</b>'
      + (cr.confidence !== undefined ? ' · conviction <b>' + cr.confidence + '%</b>' : '')
      + '<br>Provider <b>' + escape(cr.provider || usage.provider || '--') + '</b>'
      + (usage.model ? ' · model <b>' + escape(usage.model) + '</b>' : '')
      + (usage.runtime_ms ? ' · <b>' + usage.runtime_ms + 'ms</b>' : '')
      + (cr.fallback_reason ? '<br><span class="warn">Deterministic fallback: ' + escape(cr.fallback_reason) + '</span>' : '');
  } else {
    list.innerHTML = '<div class="dimc" style="font-size:11px;">No committee report persisted — deterministic path.</div>';
    el('committee-meta').innerHTML = '';
  }

  /* invalidation + risks */
  const inv = d.invalidation_conditions || [];
  el('invalidation-list').innerHTML = inv.length
    ? inv.slice(0, 6).map(c => '<li>' + escape(c.condition || '') + '</li>').join('')
    : '<li class="dimc">None persisted.</li>';
  const risks = d.risk_summary || [];
  el('risk-list').innerHTML = risks.length
    ? risks.slice(0, 6).map(r => '<li>' + escape(r.risk || '') + '<span class="risk-sev ' + String(r.severity || '').toLowerCase() + '">' + escape(r.severity || '') + ' · ' + (r.probability ?? '--') + '%</span></li>').join('')
    : '<li class="dimc">None persisted.</li>';

  /* decision trace why-not blocks */
  const trace = traceRes?.trace || d.decision_trace;
  const whyPanel = el('why-panel');
  if (trace) {
    let blocks = '';
    if (trace.why_not_buy) blocks += '<div class="why-block"><div class="wk">Why not BUY</div><div class="wv">' + escape(trace.why_not_buy) + '</div></div>';
    if (trace.why_not_sell) blocks += '<div class="why-block"><div class="wk">Why not SELL</div><div class="wv">' + escape(trace.why_not_sell) + '</div></div>';
    if (trace.base_confidence !== undefined) blocks += '<div class="why-block"><div class="wk">Confidence path</div><div class="wv">base ' + trace.base_confidence + ' → posterior ' + trace.posterior_confidence + ' (evidence ' + (trace.evidence_weight_adjustment >= 0 ? '+' : '') + trace.evidence_weight_adjustment + ', contradiction −' + trace.contradiction_penalty + ', committee ' + (trace.committee_adjustment >= 0 ? '+' : '') + trace.committee_adjustment + ')</div></div>';
    if (blocks) { whyPanel.style.display = ''; el('why-blocks').innerHTML = blocks; } else whyPanel.style.display = 'none';
  } else whyPanel.style.display = 'none';
}

/* ============ ACT IV — GEOMETRY ============ */
function renderGeometry(d, policies) {
  const planes = el('corridor-planes');
  const note = el('corridor-note');
  const stats = el('geo-stats');
  const spot = d.spot_price;
  const fx = policies.find(p => p.mode === 'forex');
  const showTradeLevels = !!(fx && !fx.is_wait && fx.actionable && fx.entry);

  const levels = [];
  const sr = d.support_resistance || { support: [], resistance: [] };
  (sr.support || []).slice(0, 2).forEach(s => levels.push({ k: 'SUPPORT', price: parseFloat(s.price), cls: 'pl-sr' }));
  (sr.resistance || []).slice(0, 2).forEach(s => levels.push({ k: 'RESIST', price: parseFloat(s.price), cls: 'pl-sr' }));
  if (spot) levels.push({ k: 'SPOT', price: spot, cls: 'pl-spot' });
  if (showTradeLevels) {
    levels.push({ k: 'ENTRY', price: parseFloat(fx.entry), cls: 'pl-entry' });
    if (fx.take_profit) levels.push({ k: 'TAKE PROFIT', price: parseFloat(fx.take_profit), cls: 'pl-tp' });
    if (fx.stop_loss) levels.push({ k: 'STOP LOSS', price: parseFloat(fx.stop_loss), cls: 'pl-sl' });
  }
  const valid = levels.filter(l => !isNaN(l.price) && l.price > 0);
  if (!valid.length) {
    planes.innerHTML = '';
    note.textContent = 'No price levels persisted — nothing to draw, nothing fabricated.';
    stats.innerHTML = '<div class="dimc" style="font-size:11px;">No levels yet.</div>';
    return;
  }
  const vals = valid.map(l => l.price);
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  const span = (hi - lo) || 1;
  const pad = span * 0.12;
  const min = lo - pad, max = hi + pad;
  planes.innerHTML = valid.map((l, i) => {
    const pct = 8 + (1 - (l.price - min) / (max - min)) * 80;
    const z = -i * 26;
    return '<div class="c-plane ' + l.cls + '" style="top:' + pct + '%; transform: translateZ(' + z + 'px);">'
      + '<span class="c-label">' + l.k + ' <span class="c-price">' + fmt2(l.price) + '</span></span></div>';
  }).join('');
  note.textContent = showTradeLevels
    ? 'Forex actionable — levels are persisted policy output'
    : 'WAIT — corridor shows market structure only, no trade levels';

  let s = '';
  s += '<div class="geo-stat"><span class="gk">Spot</span><span class="gv gold">' + fmt2(spot) + '</span></div>';
  if (showTradeLevels) {
    s += '<div class="geo-stat"><span class="gk">Entry</span><span class="gv" style="color:var(--warn)">' + fmt2(fx.entry) + '</span></div>';
    s += '<div class="geo-stat"><span class="gk">Take profit</span><span class="gv bull">' + fmt2(fx.take_profit) + '</span></div>';
    s += '<div class="geo-stat"><span class="gk">Stop loss</span><span class="gv bear">' + fmt2(fx.stop_loss) + '</span></div>';
    const rr = (fx.take_profit && fx.stop_loss && fx.entry) ? (Math.abs(parseFloat(fx.take_profit) - parseFloat(fx.entry)) / (Math.abs(parseFloat(fx.entry) - parseFloat(fx.stop_loss)) || 1)).toFixed(2) : '--';
    s += '<div class="geo-stat"><span class="gk">Reward / Risk</span><span class="gv">' + rr + '</span></div>';
  } else {
    s += '<div class="geo-stat"><span class="gk">Trade levels</span><span class="gv dimc">None — WAIT</span></div>';
  }
  if ((sr.support || []).length) s += '<div class="geo-stat"><span class="gk">Nearest support</span><span class="gv">' + fmt2(sr.support[0].price) + '</span></div>';
  if ((sr.resistance || []).length) s += '<div class="geo-stat"><span class="gk">Nearest resistance</span><span class="gv">' + fmt2(sr.resistance[0].price) + '</span></div>';
  stats.innerHTML = s;
}

/* ============ ACT V — MEMORY ============ */
function renderMemory(historyRes, backtestRes) {
  const reports = historyRes?.reports || [];
  const statsEl = el('memory-stats');
  const total = backtestRes?.historical_decision_count ?? reports.length;
  const acted = backtestRes?.action_decision_count ?? reports.filter(r => !['WAIT', 'HOLD'].includes(String(r.recommendation?.name || r.recommendation).toUpperCase())).length;
  statsEl.innerHTML = '<div class="mem-stat"><div class="ms-v serif">' + total + '</div><div class="ms-k">Decisions persisted</div></div>'
    + '<div class="mem-stat"><div class="ms-v serif">' + acted + '</div><div class="ms-k">Actionable calls</div></div>'
    + '<div class="mem-stat"><div class="ms-v serif">' + (total - acted) + '</div><div class="ms-k">Wait / hold discipline</div></div>';

  const track = el('memory-track');
  if (!reports.length) {
    track.innerHTML = '<div class="dimc" style="font-size:11px; padding:20px;">No decisions recorded yet.</div>';
    return;
  }
  track.innerHTML = reports.slice(0, 18).map((h, i) => {
    const rec = h.recommendation?.name || h.recommendation || '--';
    const t = new Date(h.timestamp);
    const time = isNaN(t) ? '--' : t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const depth = i * 13, shrink = Math.max(0.72, 1 - i * 0.03), fade = Math.max(0.3, 1 - i * 0.07);
    return '<div class="mem-card" style="transform: translateZ(-' + depth + 'px) scale(' + shrink + '); opacity:' + fade + ';">'
      + '<div class="mc-time">' + time + '</div>'
      + '<div class="mc-act serif ' + biasClass(rec) + '">' + escape(String(rec).toUpperCase()) + '</div>'
      + '<div class="mc-meta"><span>' + (h.confidence ?? '--') + '%</span><span>' + escape(h.market_regime?.name || h.market_regime || '--') + '</span></div></div>';
  }).join('');
}

/* ============ ACT VI — TELEMETRY ============ */
function renderTelemetry(d, healthRes) {
  const tel = d.pipeline_telemetry || {};
  const KEYS = [['sources', 'Sources'], ['articles', 'Articles'], ['events', 'Events'], ['narratives', 'Narratives'], ['engines', 'Engines'], ['committee_members', 'Committee'], ['modes', 'Modes']];
  el('tele-counts').innerHTML = KEYS.map(([k, label]) =>
    '<div class="tele-cell"><div class="tc-v serif">' + (tel[k] ?? '--') + '</div><div class="tc-k">' + label + '</div></div>'
  ).join('');

  const rt = ((healthRes && healthRes.engines) || []).length ? healthRes.engines : ENGINE_STATE;
  el('engine-runtimes').innerHTML = rt.map(e => {
    const name = ENG_LABEL[e.engine?.value || e.engine || e.id] || e.engine?.value || e.engine || e.id;
    return '<div class="rt-row"><span class="dimc">' + escape(String(name)) + '</span><span>' + (e.runtime_ms ?? '--') + 'ms</span></div>';
  }).join('') || '<div class="dimc" style="font-size:11px;">--</div>';

  el('decision-stamp').innerHTML = '<b>Decision</b> ' + escape(d.timestamp || '--')
    + '<br><b>Report</b> ' + escape(d.recommendation_id || '--')
    + '<br><b>Investment score</b> ' + (d.investment_score ?? '--') + ' / 100'
    + (healthRes?.ai?.requests ? '<br><b>AI requests</b> ' + healthRes.ai.requests + ' · ' + healthRes.ai.runtime_ms + 'ms' : '');
}

/* ============ PROVIDER STRIP ============ */
function renderProviderStrip(providerRes) {
  const node = document.getElementById('provider-strip');
  if (!node) return;
  const providers = (providerRes && providerRes.providers) || [];
  node.className = '';
  if (!providers.length) { node.textContent = 'PROVIDERS --'; return; }
  const down = [], degraded = [], ok = [];
  providers.forEach(p => {
    const s = String(p.status || '').toUpperCase();
    if (s === 'SUCCESS') ok.push(p);
    else if (s === 'PARTIAL_SUCCESS' || s === 'STALE_DATA') degraded.push(p);
    else down.push(p);
  });
  if (down.length) { node.classList.add('down'); node.textContent = 'PROVIDERS ' + down.length + ' DOWN'; }
  else if (degraded.length) { node.classList.add('degraded'); node.textContent = 'PROVIDERS DEGRADED ' + degraded.length; }
  else { node.classList.add('ok'); node.textContent = 'PROVIDERS ' + ok.length + ' OK'; }
  const detail = el('provider-detail');
  detail.innerHTML = providers.map(p => {
    const s = String(p.status || '').toUpperCase();
    const cls = s === 'SUCCESS' ? 'bull' : ((s === 'PARTIAL_SUCCESS' || s === 'STALE_DATA') ? 'warn' : 'bear');
    return '<div class="pd-row"><span class="dimc">' + escape(p.provider) + '</span><span class="' + cls + '">' + escape(s) + '</span></div>';
  }).join('');
}
document.getElementById('provider-strip')?.addEventListener('click', () => el('provider-detail').classList.toggle('open'));

/* ============ ACT REVEALS + NAV ============ */
const io = new IntersectionObserver(entries => {
  entries.forEach(en => { if (en.isIntersecting) en.target.classList.add('lit'); });
}, { threshold: 0.12 });
document.querySelectorAll('.act').forEach(a => io.observe(a));

const navIO = new IntersectionObserver(entries => {
  entries.forEach(en => {
    if (!en.isIntersecting) return;
    document.querySelectorAll('#rail-nav a').forEach(a => a.classList.toggle('active', a.dataset.act === en.target.id));
  });
}, { rootMargin: '-40% 0px -50% 0px' });
document.querySelectorAll('.act').forEach(a => navIO.observe(a));

window.addEventListener('keydown', ev => {
  const idx = ['1', '2', '3', '4', '5', '6'].indexOf(ev.key);
  if (idx >= 0) document.querySelectorAll('.act')[idx]?.scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth' });
});

setInterval(loadData, 5000);
loadData();
</script>
</body>
</html>
"""
