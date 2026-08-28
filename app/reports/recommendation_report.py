from app.domain.intelligence import DecisionReport


class RecommendationReportGenerator:
    def generate_markdown(self, report: DecisionReport) -> str:
        evidence = "\n".join(
            f"- {item.category}: {item.description}" for item in report.supporting_evidence
        )
        contradictions = "\n".join(
            f"- {item.category}: {item.description}" for item in report.contradicting_evidence
        )
        risks = "\n".join(f"- {item.risk} [{item.severity.value}]" for item in report.risk_summary)
        invalidation = "\n".join(
            f"- {item.condition} [{item.severity.value}]" for item in report.invalidation_conditions
        )
        return f"""# MIOS Recommendation Report

Recommendation ID: {report.recommendation_id}
Timestamp: {report.timestamp.isoformat()}

## Recommendation

{report.recommendation.value}

## Scores

- Investment Score: {report.investment_score}/100
- Opportunity Score: {report.opportunity_score}/100
- Confidence: {report.confidence}/100
- Market Regime: {report.market_regime.value}
- Expected Holding Period: {report.expected_holding_period}

## Expected Move

{report.expected_move.summary}

## Explanation

{report.explanation}

## Supporting Evidence

{evidence}

## Contradicting Evidence

{contradictions or "- None identified"}

## Risk Summary

{risks}

## Invalidation Conditions

{invalidation}
"""
