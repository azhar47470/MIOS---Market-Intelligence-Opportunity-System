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
  <title>MIOS Quant Terminal</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #0B0E11;
      --bg-surface: #12171D;
      --bg-surface-alt: #181E26;
      --bg-inset: #0E1217;
      --border-subtle: #242C37;
      --border-muted: #1C2430;

      --text-primary: #E8EDF2;
      --text-secondary: #9BA5B2;
      --text-tertiary: #5C6672;
      --text-inverse: #0B0E11;

      --color-gold: #D4A84B;
      --color-gold-dim: #A88838;
      --color-bullish: #3FBA76;
      --color-bearish: #E06860;
      --color-neutral: #6B7685;
      --color-warning: #D4A032;
      --color-info: #4A9BD9;

      --risk-low: #3FBA76;
      --risk-medium: #D4A032;
      --risk-high: #E06860;
      --risk-extreme: #C4384C;

      --font-sans: 'Inter', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;

      --transition: all 0.3s ease;
    }

    * { box-sizing: border-box; }

    body {
      background: var(--bg-base);
      color: var(--text-primary);
      font-family: var(--font-sans);
      margin: 0;
      padding: 0;
      font-size: 13px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    /* Background grid */
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(var(--border-muted) 1px, transparent 1px),
        linear-gradient(90deg, var(--border-muted) 1px, transparent 1px);
      background-size: 32px 32px;
      opacity: 0.1;
      z-index: -1;
      pointer-events: none;
    }

    .mono { font-family: var(--font-mono); }
    .uppercase { text-transform: uppercase; letter-spacing: 0.04em; }

    .text-bullish { color: var(--color-bullish); }
    .text-bearish { color: var(--color-bearish); }
    .text-gold { color: var(--color-gold); }
    .text-neutral { color: var(--color-neutral); }
    .text-warning { color: var(--color-warning); }
    .text-info { color: var(--color-info); }
    .text-secondary { color: var(--text-secondary); }
    .text-tertiary { color: var(--text-tertiary); }

    header {
      border-bottom: 1px solid var(--border-subtle);
      background: var(--bg-base);
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 600;
      letter-spacing: 0.02em;
      font-size: 14px;
    }

    .brand-icon { color: var(--color-gold); }

    .header-ticker {
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 14px;
    }

    .price-value { font-size: 16px; font-weight: 700; }

    .header-meta {
      display: flex;
      align-items: center;
      gap: 24px;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-secondary);
    }

    .system-pulse {
      display: inline-block;
      width: 8px; height: 8px;
      background: var(--color-bullish);
      border-radius: 50%;
      margin-left: 8px;
      box-shadow: 0 0 8px var(--color-bullish);
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.8); }
      100% { opacity: 1; transform: scale(1); }
    }

    .container {
      display: grid;
      grid-template-columns: 1fr;
    }

    .nav-rail {
      border-right: 1px solid var(--border-subtle);
      padding: 24px 16px;
      display: flex;
      flex-direction: column;
      gap: 32px;
    }

    .nav-menu {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .nav-item {
      padding: 10px 12px;
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 12px;
      border-radius: var(--radius-sm);
      transition: var(--transition);
      outline: none;
    }

    .nav-item:hover, .nav-item:focus {
      background: var(--bg-surface-alt);
      color: var(--text-primary);
    }

    .nav-item.active {
      color: var(--color-gold);
      background: rgba(212, 168, 75, 0.1);
    }

    .main-content {
      padding: 16px 24px;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
    }

    .view { display: none; animation: fadein 0.3s ease; }
    .view.active { display: block; }

    @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }

    .panel {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .panel-header {
      padding: 12px 16px;
      border-bottom: 1px solid var(--border-muted);
      font-size: 11px;
      font-weight: 600;
      color: var(--text-secondary);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .panel-body { padding: 16px; }

    /* Layouts */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }

    /* Typographic components */
    .kpi-huge { font-size: 48px; font-weight: 700; line-height: 1.1; letter-spacing: -0.02em; }
    .kpi-lg { font-size: 28px; font-weight: 700; line-height: 1.1; }

    .badge {
      display: inline-block;
      padding: 4px 8px;
      border-radius: var(--radius-sm);
      font-size: 11px;
      font-weight: 600;
      background: var(--bg-inset);
      border: 1px solid var(--border-muted);
    }

    .badge-outline { background: transparent; border-color: currentColor; }

    /* Specific components */
    .hero-card { display: flex; flex-direction: column; justify-content: center; min-height: 200px; }

    .market-chart-container {
      height: 200px;
      position: relative;
      background: var(--bg-inset);
      border: 1px solid var(--border-muted);
      margin-top: 12px;
      border-radius: 4px;
    }

    .chart-line {
      position: absolute; left: 0; right: 0; height: 1px;
      border-top: 1px dashed var(--text-tertiary);
    }

    .chart-label {
      position: absolute; right: 8px;
      transform: translateY(-50%);
      font-size: 11px; font-weight: 600;
      padding: 2px 6px;
      border-radius: 2px;
      background: var(--bg-surface);
      z-index: 2;
      transition: top 0.3s ease;
    }

    .committee-vote-card {
      background: var(--bg-inset);
      border: 1px solid var(--border-muted);
      padding: 12px;
      border-radius: var(--radius-sm);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--border-muted); color: var(--text-secondary); font-size: 11px; font-weight: 600; }
    td { padding: 12px 16px; border-bottom: 1px solid var(--border-muted); font-size: 13px; }

    .constellation-wrapper {
      position: relative;
      height: 300px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .mode-card {
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      display: flex; flex-direction: column;
    }
    .mode-card-header { padding: 16px; border-bottom: 1px solid var(--border-muted); display:flex; justify-content:space-between; }
    .mode-card-body { padding: 16px; flex: 1; }

    .data-row {
      display: flex; justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid var(--border-muted);
      font-size: 11px;
    }
    .data-row:last-child { border-bottom: none; }

    .pipeline-track {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding: 24px 0;
      position: relative;
    }
    .pipeline-track::before {
      content: '';
      position: absolute;
      top: 48px; left: 40px; right: 40px;
      height: 2px;
      background: var(--border-muted);
      z-index: 0;
    }
    .pipeline-node {
      display: flex; flex-direction: column; align-items: center; text-align: center;
      z-index: 1; gap: 12px; width: 100px;
    }
    .pipeline-icon {
      width: 48px; height: 48px;
      border-radius: 50%;
      background: var(--bg-surface);
      border: 2px solid var(--border-subtle);
      display: flex; align-items: center; justify-content: center;
      font-size: 18px; color: var(--color-gold);
    }

    #loader {
      position: fixed; inset: 0; background: var(--bg-base);
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      z-index: 1000; transition: opacity 0.3s ease;
    }
    .hidden { display: none !important; }

    #empty-state {
      position: fixed; inset: 0; background: var(--bg-base);
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      z-index: 999; text-align: center; padding: 24px;
    }

    .status-live.status-stale { color: var(--color-warning); }
    .status-live.status-stale::before { background: var(--color-warning); box-shadow: 0 0 8px var(--color-warning); }

    @media (max-width: 1200px) {
      .grid-3 { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 960px) {
      .container { grid-template-columns: 1fr; }
      .nav-rail {
        flex-direction: row; align-items: center; justify-content: space-between;
        padding: 12px 16px; border-right: none; border-bottom: 1px solid var(--border-subtle);
      }
      .nav-menu { flex-direction: row; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
      .nav-menu::-webkit-scrollbar { display: none; }
      .grid-2, .grid-3 { grid-template-columns: 1fr; }
      .pipeline-track { flex-direction: column; align-items: flex-start; gap: 24px; padding-left: 24px; }
      .pipeline-track::before { top: 24px; bottom: 24px; left: 47px; right: auto; width: 2px; height: auto; }
      .pipeline-node { flex-direction: row; width: auto; text-align: left; }
    }

  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap');

  :root {
    --bg: #020408;
    --fg: #E2E8F0;
    --dim: #475569;
    --border: #1E293B;
    --line: #334155;
    --accent: #F59E0B;
    --accent-dim: rgba(245, 158, 11, 0.1);
    --bull: #10B981;
    --bull-dim: rgba(16, 185, 129, 0.1);
    --bear: #EF4444;
    --bear-dim: rgba(239, 68, 68, 0.1);
    --font: 'JetBrains Mono', monospace;
  }

  body {
    background: var(--bg);
    color: var(--fg);
    font-family: var(--font);
    font-size: 11px;
    margin: 0;
    padding: 0;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow-x: hidden;
  }

  * { box-sizing: border-box; }

  /* Utils */
  .bull { color: var(--bull); }
  .bear { color: var(--bear); }
  .dim { color: var(--dim); }
  .accent { color: var(--accent); }
  .uppercase { text-transform: uppercase; }

  /* Shell Header */
  .sys-header {
    display: flex; justify-content: space-between; align-items: stretch;
    border-bottom: 1px solid var(--border); background: #010204;
    padding: 0 24px; height: 48px;
  }
  .brand { display: flex; align-items: center; font-weight: 700; color: var(--accent); letter-spacing: 1px; }
  .sys-nav { display: flex; gap: 32px; }
  .sys-nav a {
    color: var(--dim); text-decoration: none; display: flex; align-items: center;
    border-bottom: 2px solid transparent; transition: 0.2s;
  }
  .sys-nav a:hover { color: var(--fg); }
  .sys-nav a.active { color: var(--fg); border-bottom-color: var(--bull); }
  .status-strip { display: flex; align-items: center; gap: 16px; color: var(--dim); }
  .status-live { color: var(--bull); display: flex; align-items: center; gap: 6px; }
  .status-live::before { content: ''; width: 6px; height: 6px; background: var(--bull); border-radius: 50%; box-shadow: 0 0 8px var(--bull); }

  /* Main Surface */
  .main-surface {
    display: flex; flex: 1; padding: 24px; gap: 32px;
    overflow-y: auto; overflow-x: auto;
  }

  .stage-label {
    font-size: 12px; font-weight: 700; color: var(--dim); letter-spacing: 2px;
    margin-bottom: 24px; border-bottom: 1px dotted var(--line); padding-bottom: 8px;
    display: flex; gap: 8px; align-items: baseline;
  }
  .stage-label span.num { color: var(--accent); }

  /* Flow Connectors */
  .flow-down {
    display: flex; justify-content: center; padding: 12px 0; color: var(--line); font-size: 14px;
  }

  /* Col 1: Sense & Reason */
  .col-input { flex: 0 0 280px; display: flex; flex-direction: column; }

  .f-node {
    display: flex; justify-content: space-between;
    padding: 12px 16px; border: 1px solid var(--border); background: rgba(255,255,255,0.02);
    margin-bottom: 8px;
  }
  .f-node.eng { border-right: 2px solid var(--dim); padding: 8px 12px; }
  .f-node.eng.bullish { border-right-color: var(--bull); }
  .f-node.eng.bearish { border-right-color: var(--bear); }

  /* Col 2: Challenge & Adapt */
  .col-synthesis { flex: 0 0 340px; display: flex; flex-direction: column; }

  .risk-pressure {
    padding: 16px; border: 1px solid var(--bear); background: var(--bear-dim);
    box-shadow: inset 0 0 15px rgba(239,68,68,0.05);
    margin-bottom: 16px;
  }

  .committee-tree {
    display: flex; gap: 16px; align-items: center; border: 1px solid var(--border);
    padding: 16px; background: rgba(255,255,255,0.02);
  }
  .c-members {
    display: flex; flex-direction: column; gap: 12px; flex: 1; position: relative;
  }
  .c-members::after {
    content: ''; position: absolute; right: -8px; top: 12px; bottom: 12px; border-right: 1px solid var(--line);
  }
  .c-mem {
    display: flex; justify-content: space-between; font-size: 9px; position: relative;
  }
  .c-mem::after {
    content: ''; position: absolute; right: -8px; top: 50%; width: 8px; border-top: 1px solid var(--line);
  }

  .c-consensus {
    display: flex; flex-direction: column; align-items: center; gap: 4px; position: relative;
    padding-left: 8px;
  }
  .c-consensus::before {
    content: ''; position: absolute; left: 0; top: 50%; width: 8px; border-top: 1px solid var(--line);
  }

  .lenses-wrapper { margin-top: 0px; display: flex; flex-direction: column; }
  .shared-int {
    display: flex; flex-direction: column; padding: 12px; align-items: center; gap: 8px;
    border: 1px solid var(--border); background: rgba(255,255,255,0.02);
  }
  .s-val-row { display: flex; gap: 24px; }
  .s-val { display: flex; flex-direction: column; align-items: center; gap: 2px; }
  .s-val span:first-child { font-size: 9px; color: var(--dim); }

  .branch-connector {
    height: 20px; position: relative; margin: 0 16.66%;
    border-left: 1px solid var(--line); border-right: 1px solid var(--line); border-top: 1px solid var(--line);
  }
  .branch-connector::before {
    content: ''; position: absolute; left: 50%; bottom: 100%; height: 20px; border-left: 1px solid var(--line);
  }
  .branch-connector::after {
    content: ''; position: absolute; left: 50%; top: 0; bottom: 0; border-left: 1px solid var(--line);
  }

  .lenses-grid {
    display: grid; grid-template-columns: 1fr 1fr 1fr;
    border: 1px solid var(--border); background: #010204;
  }
  .l-branch {
    padding: 12px 8px; border-right: 1px solid var(--border);
    display: flex; flex-direction: column; gap: 8px;
  }
  .l-branch:last-child { border-right: none; }
  .l-branch.action { background: var(--bull-dim); position: relative; }
  .l-branch.action::after {
    content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 2px; background: var(--bull);
  }
  .l-lbl { font-size: 10px; color: var(--dim); display: flex; justify-content: space-between; }
  .l-lbl span.bull { font-weight: 700; }
  .l-param { font-size: 9px; display: flex; justify-content: space-between; border-bottom: 1px dotted var(--line); padding-bottom: 4px; }
  .l-param:last-child { border-bottom: none; }

  /* Col 3: Output */
  .col-output { flex: 1; display: flex; flex-direction: column; min-width: 400px; }

  .mega-output {
    display: flex; align-items: center; justify-content: space-between;
    padding: 24px; border: 1px solid var(--border); background: rgba(0,0,0,0.3);
    margin-bottom: 24px;
  }
  .m-rec { font-size: 10px; color: var(--dim); letter-spacing: 2px; margin-bottom: 8px; }
  .m-act { font-size: 64px; font-weight: 300; line-height: 0.9; letter-spacing: -2px; }
  .m-sub { font-size: 12px; font-weight: 500; }

  .market-chart {
    flex: 1; border: 1px solid var(--border); background: #03060C;
    position: relative; margin-bottom: 24px; overflow: hidden;
    min-height: 250px;
  }
  .mc-header { position: absolute; top: 12px; left: 16px; z-index: 10; color: var(--dim); font-size: 10px; }

  .history-log {
    border: 1px solid var(--border); background: rgba(0,0,0,0.3);
    padding: 12px; height: 160px; overflow-y: auto;
  }
  .h-row { display: grid; grid-template-columns: 50px 60px 40px 80px 1fr; padding: 6px 0; border-bottom: 1px dotted var(--line); color: var(--dim); }
  .h-row:last-child { border-bottom: none; }
  .h-row.active { color: var(--fg); }

  /* Data Flow Anim */
  .animated-flow {
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0% { opacity: 0.5; }
    50% { opacity: 1; box-shadow: 0 0 8px var(--bull); }
    100% { opacity: 0.5; }
  }

  /* Responsive Stacking */
  @media (max-width: 1200px) {
    .main-surface { flex-direction: column; }
    .col-input, .col-synthesis, .col-output { flex: none; width: 100%; }
  }


  .view { display: none; }
  .view.active { display: flex; flex-direction: column; }
</style>
</head>
<body>
  <div id="loader"><div style="font-size: 24px; color: var(--accent); margin-bottom: 16px;">⬡</div><div class="dim uppercase">Loading MIOS V5...</div></div>

  <div id="empty-state" class="hidden">
    <div style="font-size: 24px; color: var(--accent); margin-bottom: 16px;">⬡</div>
    <div class="uppercase" style="font-size: 18px; font-weight: 700; margin-bottom: 8px;">No decision yet</div>
    <div class="dim" style="margin-bottom: 16px;">The decision journal is empty. Run one intelligence cycle to populate the dashboard.</div>
    <div class="mono" style="padding: 8px 12px; border: 1px solid var(--border); background: rgba(255,255,255,0.02);">Run: python -m app.main run-once</div>
  </div>

  <header>
    <div class="brand">
      <span class="brand-icon">⬡</span>
      <span>MIOS // QUANT TERMINAL</span>
    </div>
    <div class="header-ticker mono">
      <span class="text-secondary">XAU/USD</span>
      <span class="price-value" id="hdr-spot">--</span>
    </div>
    <div class="header-meta">
      <div class="uppercase">System <span id="hdr-live" class="text-bullish">LIVE</span><span class="system-pulse"></span></div>
      <div id="hdr-time" class="mono">DECISION -- · AGE --</div>
    </div>
  </header>

  <div class="container">

  <header class="sys-header">
     <div class="brand">MIOS //</div>
     <nav class="sys-nav">
        <a href="#overview" class="nav-item active" data-view="view-overview">Overview</a>
        <a href="#modes" class="nav-item" data-view="view-modes">Execution Modes</a>
        <a href="#intelligence" class="nav-item" data-view="view-intel">Intelligence</a>
        <a href="#pipeline" class="nav-item" data-view="view-pipeline">Pipeline Trace</a>
        <a href="#history" class="nav-item" data-view="view-history">History</a>
     </nav>
     <div class="status-strip">
        <div class="status-live js-live">LIVE</div>
        <div id="hdr-sys-time">SYS: --:--Z</div>
        <div><span class="accent">XAU/USD <span id="hdr-spot-strip">--</span></span></div>
        <div id="provider-strip" class="dim">PROVIDERS: --</div>
     </div>
  </header>



    <main class="main-content">
      <!-- 1. OVERVIEW -->
      <div id="view-overview" class="view active">
<div class="main-surface">

     <!-- COGNITIVE SENSORS -->
     <section class="col-input">
        <div class="stage-label"><span class="num">01 /</span> SENSE</div>

        <div class="f-node"><span>MARKET DATA</span><span class="accent" id="val-spot">--</span></div>
        <div class="f-node"><span>EVENTS</span><span class="dim" id="val-events">--</span></div>

        <div class="flow-down">↓</div>

        <div class="stage-label"><span class="num">02 /</span> REASON</div>

        <div id="engine-array">
          <div class="f-node eng"><span>TECHNICAL</span><span class="dim">--</span></div>
          <div class="f-node eng"><span>MACRO</span><span class="dim">--</span></div>
          <div class="f-node eng"><span>INSTITUTIONAL</span><span class="dim">--</span></div>
          <div class="f-node eng"><span>NEWS/SENT</span><span class="dim">--</span></div>
          <div class="f-node eng"><span>GEOPOLITICAL</span><span class="dim">--</span></div>
          <div class="f-node eng"><span>REGIME</span><span class="dim">--</span></div>
        </div>
     </section>

     <!-- SYNTHESIS & EXECUTION -->
     <section class="col-synthesis">
        <div class="stage-label"><span class="num">03 /</span> CHALLENGE</div>

        <div class="risk-pressure" id="pullback-node">
           <div class="bear uppercase" style="font-size:10px; display:flex; justify-content:space-between;">
              <span id="pb-lbl">PULLBACK RISK PRESSURE</span> <span id="pb-score">--</span>
           </div>
           <ul id="pb-drivers" style="margin:8px 0 0 16px; padding:0; font-size:9px; color:var(--dim);">
             <li>--</li>
           </ul>
        </div>

        <div class="flow-down">↓</div>

        <div class="committee-tree">
           <div class="c-members" id="c-members-container">
              <div class="c-mem"><span class="dim">--</span> <span class="dim">--</span></div>
              <div class="c-mem"><span class="dim">--</span> <span class="dim">--</span></div>
              <div class="c-mem"><span class="dim">--</span> <span class="dim">--</span></div>
           </div>
           <div class="c-consensus">
              <div class="dim" style="font-size:9px;">CONSENSUS</div>
              <div class="dim" id="consensus-val" style="font-weight:700;">--</div>
              <div class="dim" id="consensus-conf">--</div>
           </div>
        </div>

        <div class="flow-down">↓</div>

        <div class="stage-label"><span class="num">04 /</span> ADAPT</div>

        <div class="lenses-wrapper">
           <div class="shared-int">
              <div class="dim" style="font-size:9px; letter-spacing:1px;">ONE MARKET STATE</div>
              <div class="s-val-row">
                 <div class="s-val"><span>BIAS</span><span class="dim" id="shared-bias">--</span></div>
                 <div class="s-val"><span>MOVE</span><span class="dim" id="shared-move">--</span></div>
                 <div class="s-val"><span>REGIME</span><span class="dim" id="shared-regime">--</span></div>
                 <div class="s-val"><span>RISK</span><span class="dim" id="shared-risk">--</span></div>
              </div>
           </div>

           <div class="branch-connector"></div>

           <div class="lenses-grid" id="lenses-container">
              <div class="l-branch">
                 <div class="l-lbl">PHYSICAL <span class="dim">--</span></div>
                 <div class="dim" style="font-size:9px; margin-top:8px;">Awaiting policy data</div>
              </div>
              <div class="l-branch">
                 <div class="l-lbl">FOREX <span class="dim">--</span></div>
                 <div class="dim" style="font-size:9px; margin-top:8px;">Awaiting policy data</div>
              </div>
              <div class="l-branch">
                 <div class="l-lbl">ETF <span class="dim">--</span></div>
                 <div class="dim" style="font-size:9px; margin-top:8px;">Awaiting policy data</div>
              </div>
           </div>
        </div>
     </section>

     <!-- OUTPUT & LOG -->
     <section class="col-output">
        <div class="stage-label"><span class="num">05 /</span> DECIDE</div>

        <div class="mega-output">
           <div>
             <div class="m-rec">CANONICAL OUTLOOK</div>
             <div class="m-act dim" id="mega-action">--</div>
           </div>
           <div style="text-align:right;">
             <div class="m-sub" id="mega-conf">--</div>
             <div class="dim" style="font-size:10px; margin-top:4px;" id="mega-move">EXPECTED MOVE: --</div>
             <div class="m-rec" style="margin-top:10px;">EXECUTION STATUS</div>
             <div class="dim" style="font-size:10px;" id="mega-actionable">--</div>
           </div>
        </div>

        <div class="market-chart" id="chart-area">
           <div class="mc-header">XAU/USD // MARKET STRUCTURE</div>
           <div class="dim" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:10px;">Market structure renders after the first decision</div>
        </div>

        <div class="history-log">
           <div class="dim uppercase" style="margin-bottom:8px; font-weight:700;">Chronological Trace Log</div>
           <div id="v5-history-body">
             <div class="h-row"><span>--:--</span><span class="dim">--</span><span>--</span><span>--</span><span>--</span></div>
           </div>
        </div>
     </section>

  </div>
</div>
      </div>

      <!-- 2. EXECUTION MODES --><!-- 2. EXECUTION MODES -->
      <div id="view-modes" class="view">
        <h2 class="uppercase text-secondary" style="font-size:14px; margin-top:0;">Shared Market Intelligence</h2>
        <div class="panel" style="margin-bottom:24px;">
          <div class="panel-body grid-3" style="grid-template-columns: repeat(4, 1fr); text-align:center;">
            <div>
              <div class="uppercase text-secondary" style="font-size:11px; font-weight:600;">Bias</div>
              <div class="mono text-bullish mt-xs" id="modes-bias" style="font-size:14px; font-weight:600; margin-top:4px;">--</div>
            </div>
            <div>
              <div class="uppercase text-secondary" style="font-size:11px; font-weight:600;">Confidence</div>
              <div class="mono text-bullish mt-xs" id="modes-conf" style="font-size:14px; font-weight:600; margin-top:4px;">--</div>
            </div>
            <div>
              <div class="uppercase text-secondary" style="font-size:11px; font-weight:600;">Expected Move</div>
              <div class="mono text-info mt-xs" id="modes-move" style="font-size:14px; font-weight:600; margin-top:4px;">--</div>
            </div>
            <div>
              <div class="uppercase text-secondary" style="font-size:11px; font-weight:600;">Regime</div>
              <div class="mono text-info mt-xs" id="modes-regime" style="font-size:14px; font-weight:600; margin-top:4px;">--</div>
            </div>
          </div>
        </div>
        <div class="grid-3" id="modes-grid">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- 3. INTELLIGENCE & COMMITTEE -->
      <div id="view-intel" class="view">
        <div class="grid-2">
          <div class="panel">
            <div class="panel-header uppercase">Intelligence Constellation</div>
            <div class="panel-body">
              <div id="constellation" style="display:flex; flex-direction:column; gap:16px;">
                <!-- Fallback to list/bars if complex radial graph is overkill for HTML without libraries -->
              </div>
            </div>
          </div>
          <div class="panel">
            <div class="panel-header uppercase">AI Committee Detailed View</div>
            <div style="overflow-x:auto;">
              <table id="intel-committee-table">
                <thead>
                  <tr>
                    <th>Member</th>
                    <th>Vote</th>
                    <th>Conf</th>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody id="intel-committee-body">
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- 4. PIPELINE TRACE -->
      <div id="view-pipeline" class="view">
        <h2 class="uppercase text-secondary" style="font-size:14px; margin-top:0;">Pipeline Trace (Live Flow)</h2>
        <div class="panel">
          <div class="panel-body pipeline-track" id="pipeline-track">
            <!-- Populated by JS -->
          </div>
        </div>
      </div>

      <!-- 5. HISTORY -->
      <div id="view-history" class="view">
        <div class="panel">
          <div class="panel-header uppercase">Decision Journal</div>
          <div style="overflow-x:auto;">
            <table id="history-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Confidence</th>
                  <th>Regime</th>
                </tr>
              </thead>
              <tbody id="history-body">
              </tbody>
            </table>
          </div>
        </div>
      </div>

    </main>
  </div>

  <script>
    const _missingEl = { textContent: '', innerHTML: '', className: '', style: {}, classList: { add() {}, remove() {} }, setAttribute() {}, getAttribute() { return null; } };
    const el = id => document.getElementById(id) || _missingEl;
    const escape = s => String(s??'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

    function actionColor(a) {
      if(!a) return 'var(--text-secondary)';
      const s = String(a).toUpperCase();
      if(s.includes('BUY') || s.includes('LONG') || s.includes('BULL')) return 'var(--color-bullish)';
      if(s.includes('SELL') || s.includes('SHORT') || s.includes('BEAR')) return 'var(--color-bearish)';
      if(s.includes('WAIT') || s.includes('HOLD') || s.includes('NEUTRAL') || s.includes('CAUTION')) return 'var(--color-neutral)';
      return 'var(--text-secondary)';
    }

    function actionColorCls(a) {
      const s = String(a ?? '').toUpperCase();
      if(s.includes('BUY') || s.includes('LONG') || s.includes('BULL')) return 'bull';
      if(s.includes('SELL') || s.includes('SHORT') || s.includes('BEAR')) return 'bear';
      return 'dim';
    }

    function fmtAge(seconds) {
      const s = Math.max(0, Math.floor(seconds || 0));
      if(s < 60) return s + 's';
      if(s < 3600) return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
      return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
    }

    let _historyKey; let _historyCache = null;
    async function loadData() {
      try {
        const [latestRes, policiesRes, traceRes, researchRes, providerRes] = await Promise.all([
          fetch('/api/latest').then(r => r.json()).catch(() => null),
          fetch('/api/mode-policies').then(r => r.json()).catch(() => null),
          fetch('/api/decision-trace').then(r => r.json()).catch(() => null),
          fetch('/api/research').then(r => r.json()).catch(() => null),
          fetch('/api/provider-status').then(r => r.json()).catch(() => null),
        ]);
        renderProviderStrip(providerRes);

        if(!latestRes || !latestRes.latest) {
          el('loader').style.opacity = '0';
          setTimeout(() => el('loader').classList.add('hidden'), 300);
          el('empty-state').classList.remove('hidden');
          return;
        }
        const d = latestRes.latest;
        el('empty-state').classList.add('hidden');

        // History serializes full reports: fetch once per decision, not per poll.
        let historyRes = _historyCache;
        if(d.timestamp !== _historyKey) {
          _historyKey = d.timestamp;
          historyRes = await fetch('/api/history').then(r => r.json()).catch(() => null);
          _historyCache = historyRes;
        }

        el('loader').style.opacity = '0';
        setTimeout(() => el('loader').classList.add('hidden'), 300);

        // Decision timestamp + age; LIVE only while within the configured cycle.
        const fr = latestRes.freshness;
        if(fr) {
          el('hdr-time').textContent = 'DECISION ' + String(fr.timestamp).replace('T', ' ').substring(0, 16) + 'Z · AGE ' + fmtAge(fr.age_seconds);
          [document.getElementById('hdr-live'), ...document.querySelectorAll('.js-live')].forEach(n => {
            if(!n) return;
            n.textContent = fr.fresh ? 'LIVE' : 'STALE';
            if(n.id === 'hdr-live') {
              n.classList.toggle('text-bullish', !!fr.fresh);
              n.classList.toggle('text-warning', !fr.fresh);
            } else {
              n.classList.toggle('status-stale', !fr.fresh);
            }
          });
        } else {
          el('hdr-time').textContent = 'DECISION -- · AGE --';
        }

        const spot = d.spot_price;
        if(spot) {
          el('hdr-spot').textContent = spot.toFixed(2);
          el('hdr-spot-strip').textContent = spot.toFixed(2);
        }

        // 1. OVERVIEW (hero values are bound in the V5 overview section below)
        const rec = d.recommendation.name || d.recommendation;

        let moveStr = '--';
        if(d.expected_move) {
          const em = d.expected_move;
          if(em.min_usd !== null) moveStr = (em.direction === 'UP' || em.direction === 'BULLISH' ? '+' : (em.direction === 'DOWN' || em.direction === 'BEARISH' ? '-' : '')) + '$' + parseFloat(em.min_usd).toFixed(2);
          else moveStr = em.direction;
        }

        // AI Committee
        const research = researchRes?.research_desk_report || d.research_desk_report;
        if(research && research.committee_report && research.committee_report.committee_votes) {
          const cr = research.committee_report;
          const votes = cr.committee_votes || [];
          const usage = cr.usage || {};
          const provider = cr.provider || usage.provider || '--';
          const model = usage.model || '--';
          const runtime = usage.runtime_ms ? usage.runtime_ms + 'ms' : '--';

          // Populate table for Intel view
          let itHtml = `
            <tr style="background:var(--bg-inset);">
              <td colspan="6" class="text-tertiary" style="font-size:11px; text-align:right;">
                Aggregate Execution: ${escape(provider)} / ${escape(model)} / ${runtime}
              </td>
            </tr>
          `;
          votes.forEach(v => {
             const rvote = v.direction;
             itHtml += `
             <tr>
               <td style="font-weight:500; color:var(--text-primary);"><span style="color:var(--color-gold);">⬡</span> ${escape(v.member_name)}</td>
               <td class="mono" style="color:${actionColor(rvote)}">${escape(rvote)}</td>
               <td class="mono">${Math.round(v.confidence * 100)}%</td>
               <td class="mono text-secondary">--</td>
               <td class="mono text-secondary">--</td>
               <td class="mono text-tertiary">--</td>
             </tr>`;
          });
          el('intel-committee-body').innerHTML = itHtml;
        }

        // Mode Policies
        const policies = policiesRes?.policies || d.mode_policy_results || [];
        if(policies.length > 0) {
          el('modes-bias').textContent = rec.toUpperCase();
          el('modes-bias').style.color = actionColor(rec);
          el('modes-conf').textContent = d.confidence + '%';
          el('modes-conf').style.color = d.confidence >= 80 ? 'var(--color-bullish)' : d.confidence >= 60 ? 'var(--color-warning)' : 'var(--color-bearish)';
          el('modes-move').textContent = moveStr;
          el('modes-regime').textContent = d.market_regime.name || d.market_regime;

          let mHtml = '';
          policies.forEach(p => {
             const action = (p.action || 'WAIT').toUpperCase();
             const isWait = p.is_wait || action === 'WAIT';

             mHtml += `
             <div class="mode-card">
               <div class="mode-card-header">
                 <div class="uppercase text-secondary" style="font-weight:600; display:flex; align-items:center; gap:8px;"><span style="color:var(--color-gold);">⬡</span> ${escape(p.mode)}</div>
                 <div class="badge badge-outline" style="color:${actionColor(action)}; padding:2px 8px;">${escape(action)}</div>
               </div>
               <div class="mode-card-body">
                 <div class="text-secondary" style="font-size:12px; min-height:40px; margin-bottom:16px;">
                   ${escape(p.reason)}
                 </div>

                 <div class="data-row">
                   <span class="text-tertiary uppercase">Threshold</span>
                   <span class="mono text-primary">${p.mode==='physical'?'$50.00':(p.mode==='etf'?'$40.00':'$10.00')}</span>
                 </div>
                 <div class="data-row">
                   <span class="text-tertiary uppercase">Allocate</span>
                   <span class="text-primary">${escape(p.allocation || 'Maintain')}</span>
                 </div>
                 <div class="data-row">
                   <span class="text-tertiary uppercase">Horizon</span>
                   <span class="text-primary">${escape(p.horizon || '2-4 weeks')}</span>
                 </div>

                 ${p.mode==='forex' && p.actionable && p.entry ? `
                   <div style="margin-top:16px; border-top:1px dashed var(--border-muted); padding-top:16px;">
                     <div class="data-row"><span class="text-tertiary uppercase">Entry</span><span class="mono text-secondary">${parseFloat(p.entry).toFixed(2)}</span></div>
                     <div class="data-row"><span class="text-tertiary uppercase">Take Profit</span><span class="mono text-bullish">${parseFloat(p.take_profit).toFixed(2)}</span></div>
                     <div class="data-row"><span class="text-tertiary uppercase">Stop Loss</span><span class="mono text-bearish">${parseFloat(p.stop_loss).toFixed(2)}</span></div>
                     <div class="data-row"><span class="text-tertiary uppercase">Risk Level</span><span class="text-primary">${escape(p.risk||'High')}</span></div>
                   </div>
                 ` : ''}
               </div>
             </div>`;
          });
          el('modes-grid').innerHTML = mHtml;

          // Market Structure Chart
          const fx = policies.find(p => p.mode==='forex');
          renderChart(spot, fx?.entry, fx?.take_profit, fx?.stop_loss, d.support_resistance);
        }

        // Intelligence Constellation (Linear bars for this iteration)
        if(d.engine_breakdown) {
           let eHtml = '';
           d.engine_breakdown.forEach(e => {
              eHtml += `
              <div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                  <span class="uppercase text-secondary" style="font-size:11px; font-weight:600;">${escape(e.engine_id)}</span>
                  <span class="mono text-primary">${e.score}/100</span>
                </div>
                <div style="height:4px; background:var(--bg-inset); border-radius:2px; overflow:hidden;">
                  <div style="height:100%; width:${e.score}%; background:var(--color-gold);"></div>
                </div>
              </div>`;
           });
           el('constellation').innerHTML = eHtml;
        }

        // Pipeline Trace
        const tel = d.pipeline_telemetry || {};
        let plHtml = `
          ${pNode('SOURCES', tel.sources, 'Connected')}
          ${pNode('ARTICLES', tel.articles, 'Fetched')}
          ${pNode('EVENTS', tel.events, 'Detected')}
          ${pNode('VERIFIED', 'Unavail', 'Confirmed')}
          ${pNode('NARRATIVES', tel.narratives, 'Identified')}
          ${pNode('ENGINES', tel.engines, 'Evaluated')}
          ${pNode('PULLBACK RISK', d.pullback_risk_report?.score, d.pullback_risk_report?.level)}
          ${pNode('AI COMMITTEE', tel.committee_members, 'Members')}
          ${pNode('MODE POLICY', tel.modes, 'Modes')}
          ${pNode('FINAL ACTION', rec, 'Delivered', actionColor(rec))}
        `;
        el('pipeline-track').innerHTML = plHtml;

        // History
        if(historyRes?.reports) {
           let hHtml = '';
           historyRes.reports.slice(0, 20).forEach(h => {
              const hrec = h.recommendation.name || h.recommendation;
              hHtml += `
              <tr>
                <td class="mono text-tertiary">${new Date(h.timestamp).toLocaleTimeString()}</td>
                <td class="uppercase mono" style="color:${actionColor(hrec)}; font-weight:600;">${escape(hrec)}</td>
                <td class="mono">${h.confidence}%</td>
                <td class="text-secondary" style="font-size:11px;">${escape(h.market_regime.name || h.market_regime)}</td>
              </tr>`;
           });
           el('history-body').innerHTML = hHtml;
        }


        // --- V5 OVERVIEW JS ---
        // Shell (hdr-spot / hdr-spot-strip are already bound above)
        el('hdr-sys-time').textContent = 'SYS: ' + new Date().toISOString().substring(11, 16) + 'Z';
        if(spot) {
           el('val-spot').textContent = spot.toFixed(2);
        }

        if(d.pipeline_telemetry && d.pipeline_telemetry.events !== undefined) {
           el('val-events').textContent = d.pipeline_telemetry.events;
        }

        // Reason (Engines)
        if(d.engine_breakdown) {
           let eHtml = '';
           d.engine_breakdown.forEach(e => {
              let cls = '';
              let numScore = parseFloat(e.score);
              let bias = 'NEUTRAL';
              if(!isNaN(numScore)) {
                  if(numScore > 50) { cls = 'bullish'; bias = 'BULL'; }
                  else if(numScore < 50) { cls = 'bearish'; bias = 'BEAR'; }
              } else {
                  if(String(e.score).toUpperCase().includes('RISK_ON')) { cls='bullish'; }
                  if(String(e.score).toUpperCase().includes('RISK_OFF')) { cls='bearish'; }
              }

              let scoreStr = isNaN(numScore) ? escape(e.score) : numScore;
              let txtCls = cls === 'bullish' ? 'bull' : (cls === 'bearish' ? 'bear' : 'dim');

              eHtml += `<div class="f-node eng ${cls}"><span>${escape(e.engine_id).toUpperCase()}</span><span class="${txtCls}">${scoreStr}</span></div>`;
           });
           if(el('engine-array')) el('engine-array').innerHTML = eHtml;
        }

        // Challenge (Pullback Risk)
        if(d.pullback_risk_report) {
          const pb = d.pullback_risk_report;
          const pbLevel = pb.level;
          if(el('pb-score')) el('pb-score').textContent = pb.score + ' ' + pbLevel;

          let pcol = 'bear';
          if(pbLevel === 'LOW') {
              pcol = 'bull';
              if(el('pullback-node')) {
                  el('pullback-node').classList.add('level-LOW');
                  el('pullback-node').classList.remove('bear');
              }
              if(el('pb-lbl')) el('pb-lbl').className = 'bull';
              if(el('pb-score')) el('pb-score').className = 'bull';
          } else {
              if(el('pullback-node')) el('pullback-node').classList.remove('level-LOW');
              if(el('pb-lbl')) el('pb-lbl').className = 'bear';
              if(el('pb-score')) el('pb-score').className = 'bear';
          }

          let dHtml = '';
          if (pb.directional_context) {
             dHtml = `<li>${escape(pb.directional_context)}</li>`;
          }
          if(el('pb-drivers')) el('pb-drivers').innerHTML = dHtml;
          if(el('shared-risk')) {
              el('shared-risk').textContent = pb.score + ' ' + pbLevel;
              el('shared-risk').className = pcol;
          }
        }

        // Committee Convergence
        if(research && research.committee_report && research.committee_report.committee_votes) {
          const cr = research.committee_report;
          const votes = cr.committee_votes || [];

          let cHtml = '';
          votes.slice(0,3).forEach(v => {
             const rvote = v.direction;
             const vCls = actionColorCls(rvote);
             cHtml += `<div class="c-mem"><span class="dim">${escape(v.member_name).toUpperCase()}</span> <span class="${vCls}">${escape(rvote)} ${Math.round(v.confidence * 100)}%</span></div>`;
          });
          if(el('c-members-container')) el('c-members-container').innerHTML = cHtml;

          const cvote = cr.final_recommendation.name || cr.final_recommendation;
          const cvCls = actionColorCls(cvote);
          if(el('consensus-val')) {
              el('consensus-val').textContent = cvote.toUpperCase();
              el('consensus-val').className = cvCls;
          }
          if(el('consensus-conf')) el('consensus-conf').textContent = cr.confidence + '% CONF';
        }

        // Final Decision & Shared State
        const recName = d.recommendation.name || d.recommendation;
        const mainCls = actionColorCls(recName);
        if(el('mega-action')) {
            el('mega-action').textContent = recName.toUpperCase();
            el('mega-action').className = 'm-act ' + mainCls;
        }
        if(el('mega-conf')) el('mega-conf').textContent = d.confidence + '% CONFIDENCE';

        if(el('shared-bias')) {
            el('shared-bias').textContent = recName.toUpperCase();
            el('shared-bias').className = mainCls;
        }

        const regimeStr = escape(d.market_regime.name || d.market_regime);
        if(el('shared-regime')) el('shared-regime').textContent = regimeStr;

        moveStr = '--';
        if(d.expected_move) {
          const em = d.expected_move;
          if(em.min_usd !== null) moveStr = (em.direction === 'UP' || em.direction === 'BULLISH' ? '+' : (em.direction === 'DOWN' || em.direction === 'BEARISH' ? '-' : '')) + '$' + parseFloat(em.min_usd).toFixed(2);
          else moveStr = em.direction;
        }
        if(el('mega-move')) el('mega-move').textContent = 'EXPECTED MOVE: ' + moveStr;
        if(el('shared-move')) {
            el('shared-move').textContent = moveStr;
            el('shared-move').className = moveStr.includes('+') ? 'bull' : (moveStr.includes('-') ? 'bear' : 'dim');
        }

        // Execution Lenses
        const pol = policiesRes?.policies || d.mode_policy_results || [];
        let actionableModes = [];
        if(pol.length > 0) {
          let pHtml = '';
          pol.forEach(p => {
             const action = (p.action || 'WAIT').toUpperCase();
             const isWait = p.is_wait || action === 'WAIT';
             const mCls = actionColorCls(action);

             let activeCls = '';
             let statusCls = 'dim';
             if(!isWait) {
                activeCls = 'action ' + (mCls === 'bear' ? 'bearish' : '');
                statusCls = mCls;
                actionableModes.push(p.mode);
             }

             let bodyHtml = `
               <div class="l-param"><span class="dim">THRESH</span><span>${p.mode==='physical'?'$50.00':(p.mode==='etf'?'$40.00':'$10.00')}</span></div>
               <div class="l-param"><span class="dim">ALLOC</span><span>${escape(p.allocation || 'MAINTAIN').toUpperCase()}</span></div>
             `;

             if(!isWait && p.entry) {
                 bodyHtml = `
                   <div class="l-param"><span class="dim">ENTRY</span><span class="accent">${parseFloat(p.entry).toFixed(2)}</span></div>
                   <div class="l-param"><span class="dim">TP</span><span class="bull">${parseFloat(p.take_profit).toFixed(2)}</span></div>
                   <div class="l-param"><span class="dim">SL</span><span class="bear">${parseFloat(p.stop_loss).toFixed(2)}</span></div>
                   <div class="l-param" style="border:none;"><span class="dim">RISK</span><span>${escape(p.risk||'HIGH').toUpperCase()}</span></div>
                 `;
             }

             pHtml += `
             <div class="l-branch ${activeCls}">
                 <div class="l-lbl">${escape(p.mode).toUpperCase()} <span class="${statusCls}">${escape(action)}</span></div>
                 <div style="margin-top:8px; display:flex; flex-direction:column; gap:4px;">
                    ${bodyHtml}
                 </div>
             </div>`;
          });
          if(el('lenses-container')) el('lenses-container').innerHTML = pHtml;

          if(el('mega-actionable')) {
              if(actionableModes.length > 0) {
                  el('mega-actionable').textContent = 'ACTIONABLE IN: ' + actionableModes.join(', ').toUpperCase();
              } else {
                  el('mega-actionable').textContent = 'NO MODES ACTIONABLE';
              }
          }

          // Market Structure Chart
          const fx = pol.find(p => p.mode==='forex');
          if(typeof renderChart === 'function') renderChart(spot, fx?.entry, fx?.take_profit, fx?.stop_loss, d.support_resistance);
        }

        // History
        if(historyRes?.reports) {
           let hHtml = '';
           historyRes.reports.slice(0, 15).forEach((h, i) => {
              const hrec = h.recommendation.name || h.recommendation;
              const cl = actionColorCls(hrec);
              const time = new Date(h.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
              hHtml += `
              <div class="h-row ${i===0?'active':''}">
                <span>${time}</span>
                <span class="${cl}">${escape(hrec).toUpperCase()}</span>
                <span>${h.confidence}%</span>
                <span>${escape(h.market_regime.name || h.market_regime)}</span>
              </div>`;
           });
           if(el('v5-history-body')) el('v5-history-body').innerHTML = hHtml;
        }

      } catch(e) {
        console.error(e);
      }
    }

    function pNode(title, val, sub, col = 'var(--text-primary)') {
      const v = (val===undefined || val===null) ? '--' : val;
      return `
      <div class="pipeline-node">
        <div class="pipeline-icon">⬡</div>
        <div class="uppercase text-secondary" style="font-size:10px; font-weight:600; line-height:1.2;">${escape(title)}</div>
        <div class="mono" style="font-size:24px; font-weight:600; color:${col}; margin:-4px 0;">${escape(v)}</div>
        <div class="text-tertiary" style="font-size:11px;">${escape(sub)}</div>
      </div>`;
    }

    function renderProviderStrip(providerRes) {
      const node = document.getElementById('provider-strip');
      if(!node) return;
      const providers = (providerRes && providerRes.providers) || [];
      if(!providers.length) { node.textContent = 'PROVIDERS: --'; node.className = 'dim'; return; }
      const down = [], degraded = [];
      providers.forEach(p => {
        const s = String(p.status || '').toUpperCase();
        if(s === 'SUCCESS') return;
        if(s === 'PARTIAL_SUCCESS' || s === 'STALE_DATA') degraded.push(p.provider);
        else down.push(p.provider);
      });
      if(down.length) {
        node.textContent = 'PROVIDERS: ' + (providers.length - down.length) + '/' + providers.length + ' UP · ' + down.length + ' DOWN';
        node.className = 'bear';
      } else if(degraded.length) {
        node.textContent = 'PROVIDERS: ' + (providers.length - degraded.length) + '/' + providers.length + ' UP · DEGRADED';
        node.className = 'accent';
      } else {
        node.textContent = 'PROVIDERS: ' + providers.length + ' OK';
        node.className = 'bull';
      }
    }

    // Tab switching
    const navItems = document.querySelectorAll('.nav-item');

    function switchView(hash) {
      const targetHash = hash || '#overview';
      const targetBtn = Array.from(navItems).find(btn => btn.getAttribute('href') === targetHash) || navItems[0];
      if(!targetBtn) return;

      navItems.forEach(n => { n.classList.remove('active'); n.setAttribute('aria-selected', 'false'); });
      targetBtn.classList.add('active');
      targetBtn.setAttribute('aria-selected', 'true');

      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      const viewId = targetBtn.dataset.view;
      if(el(viewId)) el(viewId).classList.add('active');
    }

    window.addEventListener('hashchange', () => {
       switchView(window.location.hash);
    });

    // Initialize hash route on load
    if(window.location.hash) {
       switchView(window.location.hash);
    }

    navItems.forEach(btn => {
      btn.addEventListener('click', (e) => {
         // click handles href automatically
      });
    });


    function renderChart(spot, entry, tp, sl, sr) {
       const chart = el('chart-area');
       if(!spot) { chart.innerHTML = '<div style="padding:16px; color:var(--dim);">Market data unavailable</div>'; return; }

       const lines = [];
       lines.push({ name: 'SPOT', val: spot, cls: 'spot' });
       if(tp) lines.push({ name: 'TP', val: parseFloat(tp), cls: 'tp' });
       if(sl) lines.push({ name: 'SL', val: parseFloat(sl), cls: 'sl' });

       if(sr && sr.support && sr.support.length > 0) {
          lines.push({ name: 'SUP', val: parseFloat(sr.support[0].price), cls: 'sup' });
       }
       if(sr && sr.resistance && sr.resistance.length > 0) {
          lines.push({ name: 'RES', val: parseFloat(sr.resistance[0].price), cls: 'res' });
       }

       const maxVal = Math.max(...lines.map(l=>l.val)) * 1.002;
       const minVal = Math.min(...lines.map(l=>l.val)) * 0.998;
       const range = maxVal - minVal;

       lines.forEach(l => l.y = 100 - ((l.val - minVal) / range * 100));
       lines.sort((a, b) => a.y - b.y);

       lines.forEach(l => l.labelY = l.y);
       for(let i=1; i<lines.length; i++) {
         if (lines[i].labelY - lines[i-1].labelY < 15) lines[i].labelY = lines[i-1].labelY + 15;
       }
       for(let i=lines.length-2; i>=0; i--) {
         if (lines[i+1].labelY - lines[i].labelY < 15) lines[i].labelY = lines[i+1].labelY - 15;
       }

       let svgHtml = `
       <svg width="100%" height="100%" preserveAspectRatio="none" style="position:absolute; inset:0;">
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
             <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="1"/>
          </pattern>
          <rect width="100%" height="100%" fill="url(#grid)" />
       `;

       lines.forEach(l => {
         let yPct = l.y + '%';
         let strColor = l.cls === 'spot' ? 'var(--accent)' : (l.cls === 'tp' ? 'var(--bull)' : (l.cls === 'sl' ? 'var(--bear)' : 'var(--dim)'));
         let dash = l.cls === 'spot' ? '' : 'stroke-dasharray="4"';

         svgHtml += `<line x1="0" y1="${yPct}" x2="100%" y2="${yPct}" stroke="${strColor}" ${dash} />`;

         let xPos = l.name === 'SPOT' ? 'calc(100% - 90px)' : 'calc(100% - 70px)';
         svgHtml += `<text x="${xPos}" y="calc(${yPct} - 4px)" fill="${strColor}" font-size="10" font-family="JetBrains Mono">${l.name} ${l.val.toFixed(2)}</text>`;
       });

       svgHtml += `</svg>`;
       chart.innerHTML = svgHtml;
    }

        setInterval(loadData, 5000);
    loadData();
  </script>
</body>
</html>"""
