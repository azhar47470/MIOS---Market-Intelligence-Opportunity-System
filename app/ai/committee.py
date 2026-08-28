"""Adversarial four-member investment committee with weighted consensus voting.

Port of the mios_v2 committee architecture onto the GIP LLM stack. Instead of one
committee-chair LLM synthesis, three adversarial LLM members — a macro strategist, a
tactical trader, and a contrarian risk analyst — vote alongside a rule-based
deterministic anchor, and the advisory output is a confidence-weighted consensus.

Member weights: deterministic 0.25, macro strategist 0.30, tactical trader 0.25,
contrarian risk 0.20. The three AI members keep distinct voices via distinct
temperatures (strategist 0.4, tactical 0.5, contrarian 0.6) and all prefer Groq as
their primary provider. Deliberation runs with cycle-level provider locking: the
committee tries one provider per cycle — Groq-first under normal conditions,
OpenCode/Laguna-first when the research desk escalates for deep reasoning, with
Ollama and Gemini as fallbacks — and if a member's call fails, the entire cycle
switches to the next provider in the chain. If every provider is exhausted, the
affected member abstains (WAIT) rather than re-voting the deterministic desk evidence
already represented by the anchor, so quorum stays intact without double-counting the
desk.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from itertools import chain
import json

from pydantic import Field

from app.ai.agents.llm_client import AIProviderError, LLMJsonClient
from app.ai.validator import AIJsonValidator
from app.application.ai_research_config import AIResearchConfig
from app.domain.ai import (
    AIContext,
    AIProviderUsage,
    AnalystReport,
    CommitteeVoteSnapshot,
    InvestmentCommitteeReport,
    ProviderAttempt,
)
from app.domain.common import DomainModel
from app.domain.enums import Recommendation

_BUY_RECOMMENDATIONS = (Recommendation.STRONG_BUY, Recommendation.BUY)
_SELL_RECOMMENDATIONS = (Recommendation.STRONG_SELL, Recommendation.TAKE_PROFIT)

_AI_PROVIDERS = frozenset({"gemini", "groq", "opencode", "ollama"})

_LEVEL_ADJUSTMENT = {"strong": 8, "moderate": 4, "weak": -2, "fragmented": -6}
_STRONG_THRESHOLD = 0.7
_MODERATE_THRESHOLD = 0.5
_WEAK_THRESHOLD = 0.35

_MEMBER_ROLES = {
    "strategist": (
        "You are a senior macro strategist at a gold-focused hedge fund. Think in "
        "structural shifts, policy regimes, and cross-asset transmission. Weigh evidence "
        "carefully and consider second-order effects. Focus on what moves gold over one "
        "to four weeks."
    ),
    "tactical": (
        "You are a fast tactical trader on a gold desk. React to momentum, positioning, "
        "and near-term catalysts. Think in hours to days. Be decisive. If the setup is "
        "unclear, vote WAIT."
    ),
    "contrarian": (
        "You are a contrarian risk analyst. Challenge consensus, stress-test assumptions, "
        "and identify tail risks. Ask what would make the trade go wrong and what the "
        "market is mispricing."
    ),
}

_VOTE_VALIDATOR = AIJsonValidator()


class CommitteeDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


@dataclass(frozen=True)
class MemberVote:
    member_name: str
    direction: CommitteeDirection
    confidence: float
    reasoning: str
    weight: float
    provider: str
    model: str | None = None
    key_risk: str = ""
    time_horizon: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    runtime_ms: int = 0
    attempts: tuple[ProviderAttempt, ...] = ()


@dataclass(frozen=True)
class CommitteeConsensus:
    direction: CommitteeDirection
    confidence: float
    level: str
    shares: dict[CommitteeDirection, float]
    votes: tuple[MemberVote, ...]


class _MemberVotePayload(DomainModel):
    direction: str = Field(default="WAIT", min_length=1, max_length=10)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=1500)
    key_risk: str = Field(default="", max_length=1000)
    time_horizon: str = Field(default="", max_length=200)


class CommitteeMember(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable member name."""

    @property
    def weight(self) -> float:
        return 0.25

    @abstractmethod
    def vote(self, context: AIContext, reports: tuple[AnalystReport, ...], requires_deep_reasoning: bool = False, force_provider: str | None = None) -> MemberVote:
        """Return this member's vote for the cycle."""


class DeterministicMember(CommitteeMember):
    """Rule-based anchor that votes from the eight deterministic desk reports."""

    @property
    def name(self) -> str:
        return "Deterministic Anchor"

    def vote(self, context: AIContext, reports: tuple[AnalystReport, ...], requires_deep_reasoning: bool = False, force_provider: str | None = None) -> MemberVote:
        return _desk_vote(self.name, self.weight, reports, fallback_reason=None)


class _LLMVotingMember(CommitteeMember):
    """An adversarial AI member with one preferred provider, one temperature, one role."""

    def __init__(
        self,
        *,
        client: LLMJsonClient,
        name: str,
        provider: str,
        weight: float,
        temperature: float,
        role: str,
    ) -> None:
        self._client = client
        self._name = name
        self._provider = provider
        self._weight = weight
        self._temperature = temperature
        self._role = role

    @property
    def name(self) -> str:
        return self._name

    @property
    def weight(self) -> float:
        return self._weight

    def vote(self, context: AIContext, reports: tuple[AnalystReport, ...], requires_deep_reasoning: bool = False, force_provider: str | None = None) -> MemberVote:
        system_prompt = _voting_system_prompt(self._role)
        max_prompt_tokens = 8000 - _approx_tokens_str(system_prompt)
        
        user_prompt = _compress_user_prompt(context, max_prompt_tokens)
        if _approx_tokens_str(user_prompt) > max_prompt_tokens:
            return _unavailable_vote(
                self._name,
                self._weight,
                "Context exceeds MAX_INPUT_TOKENS after compression."
            )
            
        try:
            completion = self._client.complete(
                system_prompt,
                user_prompt,
                is_valid=lambda raw: _VOTE_VALIDATOR.validate(raw, _MemberVotePayload)[0]
                is not None,
                requires_deep_reasoning=requires_deep_reasoning,
                preferred_provider=self._provider,
                force_provider=force_provider,
                temperature=self._temperature,
            )

        except AIProviderError as error:
            return _unavailable_vote(
                self._name,
                self._weight,
                str(error)[:300],
            )
        payload, _validation_error = _VOTE_VALIDATOR.validate(
            completion.raw_json, _MemberVotePayload
        )
        if payload is None:
            return _unavailable_vote(
                self._name,
                self._weight,
                "LLM vote JSON failed contract validation.",
            )
        usage = completion.usage
        return MemberVote(
            member_name=self._name,
            direction=_direction_from_string(payload.direction),
            confidence=_clamp01(payload.confidence),
            reasoning=payload.reasoning or "No reasoning supplied.",
            weight=self._weight,
            provider=completion.provider,
            model=usage.model,
            key_risk=payload.key_risk,
            time_horizon=payload.time_horizon,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            runtime_ms=usage.runtime_ms,
            attempts=completion.attempts,
        )


class AdversarialCommittee:
    """Runs the four members, aggregates their weighted votes, and maps the consensus
    onto the same InvestmentCommitteeReport contract the DecisionEngine consumes."""

    def __init__(
        self,
        *,
        client: LLMJsonClient,
        config: AIResearchConfig,
        members: tuple[CommitteeMember, ...] | None = None,
    ) -> None:
        self._config = config
        self._members = (
            members
            if members is not None
            else (
                DeterministicMember(),
                _LLMVotingMember(
                    client=client,
                    name="Macro Strategist",
                    provider="groq",
                    weight=0.30,
                    temperature=0.4,
                    role=_MEMBER_ROLES["strategist"],
                ),
                _LLMVotingMember(
                    client=client,
                    name="Tactical Trader",
                    provider="groq",
                    weight=0.25,
                    temperature=0.5,
                    role=_MEMBER_ROLES["tactical"],
                ),
                _LLMVotingMember(
                    client=client,
                    name="Contrarian Risk",
                    provider="groq",
                    weight=0.20,
                    temperature=0.6,
                    role=_MEMBER_ROLES["contrarian"],
                ),
            )
        )

    def deliberate(
        self,
        context: AIContext,
        reports: tuple[AnalystReport, ...],
        requires_deep_reasoning: bool = False,
    ) -> InvestmentCommitteeReport:
        import logging
        logger = logging.getLogger(__name__)
        
        client = None
        for m in self._members:
            if hasattr(m, "_client"):
                client = m._client
                break
                
        provider_chain = client.get_provider_chain(requires_deep_reasoning) if client else []
        
        votes = []
        for provider in provider_chain:
            logger.info(f'[COMMITTEE] Provider locked = {provider}')
            cycle_failed = False
            cycle_votes = []
            
            for member in self._members:
                if isinstance(member, DeterministicMember):
                    vote_obj = member.vote(context, reports)
                else:
                    vote_obj = member.vote(context, reports, requires_deep_reasoning=requires_deep_reasoning, force_provider=provider)
                
                cycle_votes.append(vote_obj)
                if vote_obj.provider == "fallback":
                    logger.info(f'[COMMITTEE] Provider failed = {provider}')
                    cycle_failed = True
                    break
                    
                if vote_obj.provider != "deterministic_fallback" and vote_obj.provider != "fallback":
                    logger.info(f'[COMMITTEE] {member.name} -> {vote_obj.provider}/{vote_obj.model}')
            
            if not cycle_failed:
                votes = cycle_votes
                break
            else:
                next_idx = provider_chain.index(provider) + 1
                if next_idx < len(provider_chain):
                    next_prov = provider_chain[next_idx]
                    logger.info(f'[COMMITTEE] Switching entire committee cycle to {next_prov}')
                    if next_prov == "gemini":
                        logger.info(f'[COMMITTEE] Emergency fallback = {next_prov}')
                
        if not votes:
            # Fallback if all providers fail
            for member in self._members:
                votes.append(member.vote(context, reports))
                
        votes = tuple(votes)
        consensus = _consensus(votes)
        logger.info(f'[COMMITTEE] Final consensus generated = {consensus.direction.value}')
        return _to_committee_report(context.context_id, consensus, self._config)


def _consensus(votes: tuple[MemberVote, ...]) -> CommitteeConsensus:
    total_weight = sum(vote.weight for vote in votes) or 1.0
    shares: dict[CommitteeDirection, float] = {}
    for direction in CommitteeDirection:
        weighted = sum(
            vote.confidence * vote.weight for vote in votes if vote.direction == direction
        )
        shares[direction] = weighted / total_weight
    best = max(CommitteeDirection, key=lambda direction: shares[direction])
    confidence = min(0.95, shares[best])
    if confidence >= _STRONG_THRESHOLD:
        level = "strong"
    elif confidence >= _MODERATE_THRESHOLD:
        level = "moderate"
    elif confidence >= _WEAK_THRESHOLD:
        level = "weak"
    else:
        level = "fragmented"
    return CommitteeConsensus(
        direction=best,
        confidence=confidence,
        level=level,
        shares=shares,
        votes=votes,
    )


def _to_committee_report(
    context_id: str,
    consensus: CommitteeConsensus,
    config: AIResearchConfig,
) -> InvestmentCommitteeReport:
    votes = consensus.votes
    ai_votes = [vote for vote in votes if vote.provider in _AI_PROVIDERS]
    has_ai = bool(ai_votes)
    level = consensus.level
    direction = consensus.direction
    opposing = [vote for vote in votes if vote.direction != direction]
    disagreement_lines = _vote_lines(opposing)
    conflicting = _opposing_evidence(votes)
    weak_lines = tuple(
        f"{vote.member_name}: {vote.reasoning} (confidence {vote.confidence:.0%})"
        for vote in votes
        if vote.confidence < 0.5
    )
    missing_lines = tuple(
        f"{vote.member_name}: LLM reasoning unavailable; this member abstained."
        for vote in votes
        if vote.provider == "fallback"
    )
    alternatives = []
    for vote in votes:
        if vote.member_name == "Contrarian Risk" and vote.provider in _AI_PROVIDERS:
            if vote.key_risk:
                alternatives.append(f"Contrarian tail risk: {vote.key_risk}")
            alternatives.append(f"Contrarian scenario: {vote.reasoning}")
    alternatives.extend(disagreement_lines[:4])
    return InvestmentCommitteeReport(
        report_id=_report_id(context_id, consensus),
        context_id=context_id,
        provider="adversarial_committee" if has_ai else "deterministic_fallback",
        final_recommendation=_to_recommendation(direction, consensus.confidence),
        confidence=round(consensus.confidence * 100),
        summary=(
            f"{level.capitalize()} consensus: buy {consensus.shares[CommitteeDirection.BUY]:.0%}, "
            f"sell {consensus.shares[CommitteeDirection.SELL]:.0%}, "
            f"wait {consensus.shares[CommitteeDirection.WAIT]:.0%} "
            f"across {len(votes)} committee members."
        ),
        disagreements=disagreement_lines,
        missing_evidence=missing_lines,
        weak_evidence=weak_lines,
        conflicting_evidence=conflicting,
        required_confirmations=_required_confirmations(level, direction, has_ai),
        confidence_adjustment=(
            _LEVEL_ADJUSTMENT[level]
            if has_ai
            else config.committee_fallback_confidence_adjustment
        ),
        why_not_buy=_counter_case(votes, CommitteeDirection.BUY),
        why_not_sell=_counter_case(votes, CommitteeDirection.SELL),
        alternative_scenarios=tuple(dict.fromkeys(alternatives))[:8],
        fallback_reason=(
            None
            if has_ai
            else "Every LLM committee member failed; the committee voted from "
            "deterministic desk evidence."
        ),
        usage=_aggregate_usage(ai_votes),
        provider_attempts=tuple(chain.from_iterable(vote.attempts for vote in votes))[-20:],
        committee_votes=tuple(
            CommitteeVoteSnapshot(
                member_name=vote.member_name,
                direction=vote.direction.value,
                confidence=vote.confidence,
                weight=vote.weight,
                reasoning=vote.reasoning,
            )
            for vote in votes
        ),
    )


def _desk_vote(
    name: str,
    weight: float,
    reports: tuple[AnalystReport, ...],
    *,
    fallback_reason: str | None,
) -> MemberVote:
    """Aggregate the deterministic desk reports into the anchor member's vote."""
    bullish = sum(
        report.confidence
        for report in reports
        if report.recommendation in _BUY_RECOMMENDATIONS
    )
    bearish = sum(
        report.confidence
        for report in reports
        if report.recommendation in _SELL_RECOMMENDATIONS
    )
    provider = "fallback" if fallback_reason else "deterministic"
    total = bullish + bearish
    if total == 0:
        suffix = f" LLM unavailable: {fallback_reason}" if fallback_reason else ""
        if not reports:
            return MemberVote(
                name,
                CommitteeDirection.WAIT,
                0.3,
                f"No deterministic desk evidence.{suffix}".strip(),
                weight,
                provider,
            )
        return MemberVote(
            name,
            CommitteeDirection.WAIT,
            0.4,
            f"Desk evidence is neutral (no directional votes across {len(reports)} reports).{suffix}".strip(),
            weight,
            provider,
        )
    net = (bullish - bearish) / total
    suffix = f" (LLM unavailable: {fallback_reason})" if fallback_reason else ""
    if net > 0.15:
        return MemberVote(
            name,
            CommitteeDirection.BUY,
            min(0.9, 0.5 + net * 0.4),
            f"Weighted desk evidence is bullish (net={net:.2f}).{suffix}".strip(),
            weight,
            provider,
        )
    if net < -0.15:
        return MemberVote(
            name,
            CommitteeDirection.SELL,
            min(0.9, 0.5 + abs(net) * 0.4),
            f"Weighted desk evidence is bearish (net={net:.2f}).{suffix}".strip(),
            weight,
            provider,
        )
    return MemberVote(
        name,
        CommitteeDirection.WAIT,
        0.4,
        f"Desk evidence is mixed (net={net:.2f}).{suffix}".strip(),
        weight,
        provider,
    )


def _unavailable_vote(name: str, weight: float, reason: str) -> MemberVote:
    """An AI member whose provider chain is exhausted abstains instead of re-voting
    the deterministic desk evidence. The anchor already represents that evidence, so
    repeating it would double-count the desk and inflate committee confidence during
    an outage."""
    return MemberVote(
        name,
        CommitteeDirection.WAIT,
        0.3,
        f"{reason} The deterministic anchor already represents the desk evidence, so "
        "this member abstains from direction rather than duplicating it.",
        weight,
        "fallback",
    )


def _vote_lines(votes: tuple[MemberVote, ...]) -> tuple[str, ...]:
    return tuple(f"{vote.member_name}: {vote.reasoning}" for vote in votes)[:12]


def _opposing_evidence(votes: tuple[MemberVote, ...]) -> tuple[str, ...]:
    buys = [vote for vote in votes if vote.direction == CommitteeDirection.BUY]
    sells = [vote for vote in votes if vote.direction == CommitteeDirection.SELL]
    if not buys or not sells:
        return ()
    return tuple(
        f"{vote.member_name} argues {vote.direction.value}: {vote.reasoning}"
        for vote in buys + sells
    )[:12]


def _counter_case(votes: tuple[MemberVote, ...], side: CommitteeDirection) -> str:
    """Why not to take the given side: the strongest explicit opposing vote the
    committee heard, otherwise the contrarian's tail risk, otherwise a plain
    statement of the resulting bias."""
    opposite = (
        CommitteeDirection.SELL
        if side == CommitteeDirection.BUY
        else CommitteeDirection.BUY
    )
    opposing = [vote for vote in votes if vote.direction == opposite]
    if opposing:
        top = max(opposing, key=lambda vote: vote.confidence)
        if top.member_name == "Contrarian Risk":
            parts = [f"Contrarian risk view: {top.reasoning}"]
            if top.key_risk:
                parts.append(f"Key risk: {top.key_risk}")
            return " ".join(parts)
        return f"{top.member_name}: {top.reasoning}"
    contrarian = next(
        (
            vote
            for vote in votes
            if vote.member_name == "Contrarian Risk" and vote.provider in _AI_PROVIDERS
        ),
        None,
    )
    if contrarian is not None and contrarian.key_risk:
        return f"Contrarian tail risk: {contrarian.key_risk}"
    if any(vote.direction == side for vote in votes):
        return (
            f"The committee's weighted vote is {side.value.lower()} gold; no member "
            "voiced a direct counter-case."
        )
    return f"The committee's weighted vote is not {side.value.lower()} gold."


def _required_confirmations(
    level: str,
    direction: CommitteeDirection,
    has_ai: bool,
) -> tuple[str, ...]:
    if not has_ai:
        return (
            "Validated committee reasoning is unavailable; confirm with the deterministic "
            "desk evidence.",
        )
    if level == "strong":
        return ()
    if level in {"moderate", "weak"}:
        return (f"Reassess the {direction.value.lower()} vote at the next cycle before acting.",)
    return ("Wait for renewed cross-member agreement before acting.",)


def _to_recommendation(direction: CommitteeDirection, confidence: float) -> Recommendation:
    if direction == CommitteeDirection.BUY:
        return (
            Recommendation.STRONG_BUY
            if confidence >= _STRONG_THRESHOLD
            else Recommendation.BUY
        )
    if direction == CommitteeDirection.SELL:
        return (
            Recommendation.STRONG_SELL
            if confidence >= _STRONG_THRESHOLD
            else Recommendation.TAKE_PROFIT
        )
    return Recommendation.WAIT


def _aggregate_usage(votes: list[MemberVote]) -> AIProviderUsage | None:
    if not votes:
        return None
    providers = ", ".join(dict.fromkeys(vote.provider for vote in votes))
    models = ", ".join(
        dict.fromkeys(vote.model for vote in votes if vote.model)
    ) or "multi-member"
    return AIProviderUsage(
        provider=providers,
        model=models[:160],
        prompt_tokens=sum(vote.prompt_tokens for vote in votes),
        completion_tokens=sum(vote.completion_tokens for vote in votes),
        runtime_ms=sum(vote.runtime_ms for vote in votes),
    )



def _approx_tokens_str(s: str) -> int:
    return len(s) // 4

def _compress_user_prompt(context: AIContext, max_tokens: int) -> str:
    prompt = _voting_user_prompt(context)
    if _approx_tokens_str(prompt) <= max_tokens:
        return prompt
        
    # Compress again: remove arrays
    compressed_facts = dict(context.facts)
    if "evidence" in compressed_facts:
        compressed_facts["evidence"] = compressed_facts["evidence"][:2]
    if "risks" in compressed_facts:
        compressed_facts["risks"] = compressed_facts["risks"][:2]
    if "narratives" in compressed_facts:
        compressed_facts["narratives"] = compressed_facts["narratives"][:1]
    if "events" in compressed_facts:
        compressed_facts["events"] = compressed_facts["events"][:1]
        
    compressed_context = AIContext(
        context_id=context.context_id,
        objective=context.objective,
        facts=compressed_facts
    )
    return _voting_user_prompt(compressed_context)

def _voting_system_prompt(role: str) -> str:
    return (
        f"{role}\n\n"
        "You are one member of an adversarial four-member gold committee; other members may "
        "legitimately disagree with you. Vote decisively based only on the supplied facts.\n\n"
        "Return ONLY valid JSON matching this exact structure:\n"
        "{\n"
        '  "direction": "LONG",\n'
        '  "confidence": 0.85,\n'
        '  "reasoning": "Detailed explanation...",\n'
        '  "key_risk": "Primary invalidation risk...",\n'
        '  "time_horizon": "Expected duration..."\n'
        "}\n\n"
        "Rules:\n"
        '- direction MUST be exactly "LONG", "SHORT", or "WAIT".\n'
        '- confidence MUST be a float from 0.0 to 1.0.\n'
        '- NO MARKDOWN FORMATTING.\n'
        '- NO PROSE.\n'
        '- NO ```json WRAPPERS.'
    )


def _voting_user_prompt(context: AIContext) -> str:
    return (
        f"Objective: {context.objective}\n"
        "Scoped facts JSON:\n"
        f"{json.dumps(context.facts, ensure_ascii=True, default=str)}"
    )


def _direction_from_string(value: str) -> CommitteeDirection:
    normalized = value.strip().upper()
    if normalized == "LONG":
        return CommitteeDirection.BUY
    if normalized == "SHORT":
        return CommitteeDirection.SELL
    return CommitteeDirection.WAIT


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _report_id(context_id: str, consensus: CommitteeConsensus) -> str:
    digest = sha256(
        "|".join(
            (
                "ADV-COMMITTEE",
                context_id,
                consensus.level,
                consensus.direction.value,
                str(len(consensus.votes)),
            )
        ).encode()
    ).hexdigest()
    return f"AI-ADVCOMMITTEE-{digest[:20]}"
