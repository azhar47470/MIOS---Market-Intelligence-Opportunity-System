import json
from datetime import datetime
from app.domain.ai import AIContext, AgentRole
from app.domain.intelligence import AnalysisBundle
from app.domain.common import EvidenceRecord, RiskRecord, EvidenceStrength

from app.ai.token_estimate import approx_tokens

# We alias it to keep compatibility within the file
def _approx_tokens(data: dict | list | str) -> int:
    return approx_tokens(data)

class AIContextBuilder:
    def __init__(self):
        self.max_tokens = 7000
        self.hard_limit = 8000

    def for_specialist(self, role: AgentRole, bundle: AnalysisBundle) -> AIContext:
        facts = _specialist_facts(role, bundle)
        return AIContext(
            context_id=f"{role.value}-{bundle.market_data.collected_at.isoformat()}",
            objective=f"Produce a bounded {role.value} report for physical gold investors.",
            facts=facts,
        )

    def for_committee(self, reports: tuple, context_id: str) -> AIContext:
        return AIContext(
            context_id=f"committee-{context_id}",
            objective="Challenge specialist reports and form an advisory gold recommendation.",
            facts={
                "specialist_reports": [
                    {
                        "role": report.role.value,
                        "summary": report.summary,
                        "bullish_arguments": report.bullish_arguments,
                        "bearish_arguments": report.bearish_arguments,
                        "confidence": report.confidence,
                        "risks": report.risks,
                        "recommendation": report.recommendation.value,
                        "missing_evidence": report.missing_evidence,
                        "required_confirmations": report.required_confirmations,
                    }
                    for report in reports
                ]
            },
        )

    def _rank_evidence(self, bundle: AnalysisBundle) -> list[EvidenceRecord]:
        all_evidence = []
        for analysis in [bundle.technical, bundle.fundamental, bundle.institutional, bundle.news, bundle.geopolitical, bundle.regime]:
            if analysis:
                all_evidence.extend(analysis.evidence)
        strength_map = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        return sorted(
            all_evidence,
            key=lambda e: (strength_map.get(e.strength.value, 1), getattr(e, 'confidence', 0)),
            reverse=True
        )
        
    def _rank_risks(self, bundle: AnalysisBundle) -> list[RiskRecord]:
        all_risks = []
        for analysis in [bundle.technical, bundle.fundamental, bundle.institutional, bundle.news, bundle.geopolitical, bundle.regime]:
            if analysis:
                all_risks.extend(analysis.risks)
        return all_risks

    def for_research_desk(self, bundle: AnalysisBundle) -> AIContext:
        base_facts = {
            "price_context": {
                "quote": bundle.market_data.quote.model_dump(mode="json") if bundle.market_data.quote else None,
                "bar_count": len(bundle.market_data.bars),
            },
            "data_status": {
                "technical": bundle.technical.status.value if bundle.technical else "unknown",
                "fundamental": bundle.fundamental.status.value if bundle.fundamental else "unknown",
                "institutional": bundle.institutional.status.value if bundle.institutional else "unknown",
                "news": bundle.news.status.value if bundle.news else "unknown",
                "geopolitical": bundle.geopolitical.status.value if bundle.geopolitical else "unknown",
                "regime": bundle.regime.status.value if bundle.regime else "unknown",
            },
            "engine_summaries": {
                "technical": _analysis_summary(bundle.technical),
                "fundamental": _analysis_summary(bundle.fundamental),
                "institutional": _analysis_summary(bundle.institutional),
                "news": _analysis_summary(bundle.news),
                "geopolitical": _analysis_summary(bundle.geopolitical),
                "regime": _analysis_summary(bundle.regime),
            },
            "evidence": [],
            "risks": [],
            "narratives": [],
            "events": []
        }
        
        current_tokens = _approx_tokens(base_facts)
        
        # Rankings
        ranked_evidence = self._rank_evidence(bundle)
        ranked_risks = self._rank_risks(bundle)
        narratives = bundle.market_data.narratives
        events = bundle.market_data.economic_events + bundle.market_data.events
        
        selected_evidence = 0
        dropped_evidence = 0
        selected_narratives = 0
        dropped_items = 0
        
        # 1. Add top narratives (up to 3)
        for n in narratives[:3]:
            n_json = n.model_dump(mode="json")
            n_tokens = _approx_tokens(n_json)
            if current_tokens + n_tokens < self.max_tokens:
                base_facts["narratives"].append(n_json)
                current_tokens += n_tokens
                selected_narratives += 1
            else:
                dropped_items += 1
        
        # 2. Add top risks (up to 5)
        for r in ranked_risks[:5]:
            r_json = r.model_dump(mode="json")
            r_tokens = _approx_tokens(r_json)
            if current_tokens + r_tokens < self.max_tokens:
                base_facts["risks"].append(r_json)
                current_tokens += r_tokens
            else:
                dropped_items += 1
                
        # 3. Add evidence by rank
        for ev in ranked_evidence:
            ev_json = ev.model_dump(mode="json")
            ev_tokens = _approx_tokens(ev_json)
            if current_tokens + ev_tokens < self.max_tokens:
                base_facts["evidence"].append(ev_json)
                current_tokens += ev_tokens
                selected_evidence += 1
            else:
                dropped_evidence += 1
                dropped_items += 1
                
        # 4. Add top events if budget allows
        for ev in events:
            ev_json = ev.model_dump(mode="json")
            ev_tokens = _approx_tokens(ev_json)
            if current_tokens + ev_tokens < self.max_tokens:
                base_facts["events"].append(ev_json)
                current_tokens += ev_tokens
            else:
                dropped_items += 1
                
        # Record telemetry in the context object for later extraction
        base_facts["_telemetry"] = {
            "tokens_before": _approx_tokens(bundle.model_dump(mode="json")) if hasattr(bundle, "model_dump") else 20000,
            "tokens_after": current_tokens,
            "evidence_selected": selected_evidence,
            "evidence_dropped": dropped_evidence,
            "narratives_selected": selected_narratives,
            "items_dropped_by_budget": dropped_items,
        }

        return AIContext(
            context_id=f"research-desk-{bundle.market_data.collected_at.isoformat()}",
            objective=(
                "Synthesize technical, macro, institutional, news, geopolitical, and regime "
                "evidence into one committee-style bull/bear case, key risks, and a bounded "
                "confidence adjustment."
            ),
            facts=base_facts,
        )

def _analysis_summary(analysis) -> dict:
    if not analysis:
        return {}
    return {
        "status": analysis.status.value,
        "score": analysis.score,
        "confidence": analysis.confidence.value,
        "bias": analysis.bias.value,
    }

def _specialist_facts(role: AgentRole, bundle: AnalysisBundle) -> dict:
    if role == AgentRole.TECHNICAL_ANALYST:
        return {
            "technical": _analysis_summary(bundle.technical),
            "evidence": [e.model_dump(mode="json") for e in bundle.technical.evidence[:10]] if bundle.technical else [],
            "price_context": {
                "quote": bundle.market_data.quote.model_dump(mode="json") if bundle.market_data.quote else None,
                "bar_count": len(bundle.market_data.bars),
            },
        }
    if role in {AgentRole.MACRO_ECONOMIST, AgentRole.FEDERAL_RESERVE_ANALYST}:
        us_events = [
            event.model_dump(mode="json")
            for event in bundle.market_data.economic_events
            if event.country.upper() == "US"
        ][:10]
        return {"fundamental": _analysis_summary(bundle.fundamental), "evidence": [e.model_dump(mode="json") for e in bundle.fundamental.evidence[:10]] if bundle.fundamental else [], "us_events": us_events}
    if role == AgentRole.INSTITUTIONAL_ANALYST:
        return {"institutional": _analysis_summary(bundle.institutional), "evidence": [e.model_dump(mode="json") for e in bundle.institutional.evidence[:10]] if bundle.institutional else []}
    if role == AgentRole.ETF_FLOW_ANALYST:
        return {
            "etf_flow": bundle.market_data.gld_flow.model_dump(mode="json") if bundle.market_data.gld_flow else None,
            "institutional_evidence": [e.model_dump(mode="json") for e in bundle.institutional.evidence[:10]] if bundle.institutional else [],
            "institutional_risks": [r.model_dump(mode="json") for r in bundle.institutional.risks[:5]] if bundle.institutional else [],
        }
    if role == AgentRole.NEWS_ANALYST:
        return {
            "news": _analysis_summary(bundle.news),
            "evidence": [e.model_dump(mode="json") for e in bundle.news.evidence[:10]] if bundle.news else [],
            "articles": [article.model_dump(mode="json") for article in bundle.market_data.news_articles[:10]],
        }
    if role == AgentRole.GEOPOLITICAL_ANALYST:
        return {
            "geopolitical": _analysis_summary(bundle.geopolitical),
            "evidence": [e.model_dump(mode="json") for e in bundle.geopolitical.evidence[:10]] if bundle.geopolitical else [],
            "articles": [article.model_dump(mode="json") for article in bundle.market_data.geopolitical_articles[:10]],
        }
    if role == AgentRole.RISK_ANALYST:
        return {
            "risks": {
                "technical": [r.model_dump(mode="json") for r in bundle.technical.risks[:5]] if bundle.technical else [],
                "fundamental": [r.model_dump(mode="json") for r in bundle.fundamental.risks[:5]] if bundle.fundamental else [],
                "institutional": [r.model_dump(mode="json") for r in bundle.institutional.risks[:5]] if bundle.institutional else [],
                "news": [r.model_dump(mode="json") for r in bundle.news.risks[:5]] if bundle.news else [],
                "geopolitical": [r.model_dump(mode="json") for r in bundle.geopolitical.risks[:5]] if bundle.geopolitical else [],
                "regime": [r.model_dump(mode="json") for r in bundle.regime.risks[:5]] if bundle.regime else [],
            },
            "data_status": {
                "technical": bundle.technical.status.value if bundle.technical else "unknown",
                "fundamental": bundle.fundamental.status.value if bundle.fundamental else "unknown",
                "institutional": bundle.institutional.status.value if bundle.institutional else "unknown",
                "news": bundle.news.status.value if bundle.news else "unknown",
                "geopolitical": bundle.geopolitical.status.value if bundle.geopolitical else "unknown",
                "regime": bundle.regime.status.value if bundle.regime else "unknown",
            },
        }
    raise ValueError(f"Unsupported specialist role: {role.value}")

