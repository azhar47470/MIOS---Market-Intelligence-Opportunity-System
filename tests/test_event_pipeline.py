from datetime import UTC, datetime, timedelta

from app.application.events.clusterer import NarrativeClusterer
from app.application.events.detector import EventDetector
from app.application.events.pipeline import EventNarrativePipeline
from app.application.events.verifier import CrossSourceVerifier, SOURCE_TIERS
from app.domain.market_data import DataProviderId, MarketSymbol, NewsArticle

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _article(article_id: str, title: str, source: str, summary: str = "") -> NewsArticle:
    return NewsArticle(
        article_id=article_id,
        title=title,
        url=f"https://example.test/{article_id}",
        source_name=source,
        published_at=_NOW,
        summary=summary or title,
        provider=DataProviderId.NEWSAPI,
    )


def test_detector_merges_same_story_across_sources_and_keeps_unrelated_separate():
    articles = (
        _article(
            "a1",
            "Fed signals rate cut in September as inflation cools",
            "Reuters",
        ),
        _article(
            "a2",
            "Fed signals rate cut in September as inflation cools",
            "Bloomberg",
        ),
        _article("a3", "Gold ETF holdings jump on central bank demand", "Kitco"),
    )

    events = EventDetector().detect(articles)

    assert len(events) == 2
    merged = next(event for event in events if "rate cut" in event.title.lower())
    assert set(merged.sources) == {"Reuters", "Bloomberg"}
    assert set(merged.article_ids) == {"a1", "a2"}
    assert merged.confidence == 0.70  # 0.30 + 0.08 * size(2) + 0.12 * sources(2)


def test_detector_returns_empty_for_no_articles():
    assert EventDetector().detect(()) == ()


def test_detector_singletons_when_articles_share_no_tokens():
    articles = (
        _article("b1", "Fed signals rate cut in September", "Reuters"),
        _article("b2", "Iran launches drone strikes near gulf", "AFP"),
    )

    events = EventDetector().detect(articles)

    assert len(events) == 2
    assert all(len(event.article_ids) == 1 for event in events)


def test_verifier_confirms_authoritative_source_with_corroborator():
    event = EventDetector().detect(
        (
            _article("c1", "Fed signals rate cut in September as inflation cools", "Reuters"),
            _article("c2", "Fed signals rate cut in September as inflation cools", "Kitco"),
        )
    )[0]

    verified = CrossSourceVerifier().verify((event,))[0]

    assert verified.is_confirmed
    assert verified.has_authoritative
    assert verified.best_tier == 1
    assert verified.tier_diversity == 2
    # base 0.70 + source bonus 0.06 + authoritative 0.15 + diversity 0.05
    assert verified.confidence == round(0.70 + 0.06 + 0.15 + 0.05, 3)


def test_verifier_never_confirms_aggregator_only_cluster():
    event = EventDetector().detect(
        (
            _article("d1", "Fed signals rate cut in September", "Aggregator One"),
            _article("d2", "Fed signals rate cut in September", "Aggregator Two"),
        )
    )[0]

    verified = CrossSourceVerifier().verify((event,))[0]

    assert not verified.is_confirmed
    assert not verified.has_authoritative
    assert verified.best_tier == 5
    # No authoritative bonus and no diversity bonus on a single tier.
    assert verified.confidence == 0.70 + 0.06


def test_verifier_is_immune_to_low_trust_volume():
    events = EventDetector().detect(
        tuple(
            _article(f"e{i}", "Fed signals rate cut in September", f"Syndicator {i}")
            for i in range(5)
        )
    )

    verified = CrossSourceVerifier().verify(events)

    assert len(verified) == 1
    assert not verified[0].is_confirmed


def test_tier_map_covers_curated_outlets():
    assert SOURCE_TIERS["reuters"] <= 2
    assert SOURCE_TIERS["bloomberg"] <= 2
    assert SOURCE_TIERS["kitco"] == 3


def test_narrative_clusterer_matches_templates_and_calibrates_strength():
    events = EventDetector().detect(
        (
            _article("f1", "Fed signals rate cut in September as inflation cools", "Reuters"),
            _article("f2", "Fed signals rate cut in September as inflation cools", "Bloomberg"),
        )
    )

    narratives = NarrativeClusterer().cluster(events, ())

    names = {narrative.name for narrative in narratives}
    assert "Rate Cut Cycle" in names
    rate_cut = next(narrative for narrative in narratives if narrative.name == "Rate Cut Cycle")
    assert rate_cut.strength > 0.3
    assert 0.0 <= rate_cut.strength <= 1.0
    assert set(rate_cut.event_ids) == {events[0].event_id}
    assert sorted(narratives, key=lambda n: n.strength, reverse=True) == list(narratives)


def test_narrative_clusterer_ignores_substring_false_positives():
    events = EventDetector().detect(
        (
            _article(
                "i1",
                "Moderate stance as increasing tolerance meets renegotiation",
                "Reuters",
            ),
        )
    )

    narratives = NarrativeClusterer().cluster(events, ())

    # "rate" in "moderate"/"tolerance" and "easing" in "increasing" must not
    # manufacture Higher-for-Longer or Rate-Cut narratives.
    assert narratives == ()


def test_narrative_clusterer_matches_plural_inflections():
    events = EventDetector().detect(
        (
            _article("j1", "Fed signals rate cuts as inflation slows", "Reuters"),
        )
    )

    narratives = NarrativeClusterer().cluster(events, ())

    assert {"Rate Cut Cycle", "Inflation Resurgence"} <= {n.name for n in narratives}


def test_narrative_ids_are_stable():
    articles = (
        _article("g1", "Fed signals rate cut in September as inflation cools", "Reuters"),
        _article("g2", "Fed signals rate cut in September as inflation cools", "Bloomberg"),
    )
    first = NarrativeClusterer().cluster(EventDetector().detect(articles), ())
    second = NarrativeClusterer().cluster(EventDetector().detect(articles), ())
    assert {n.narrative_id for n in first} == {n.narrative_id for n in second}


def test_pipeline_end_to_end_produces_events_and_narratives():
    articles = (
        _article("h1", "Fed signals rate cut in September as inflation cools", "Reuters"),
        _article("h2", "Fed signals rate cut in September as inflation cools", "Kitco"),
        _article("h3", "Iran launches drone strikes near gulf", "AFP"),
    )

    events, narratives = EventNarrativePipeline().run(articles)

    assert len(events) == 2
    confirmed = [event for event in events if event.is_confirmed]
    assert len(confirmed) == 1
    assert confirmed[0].title == "Fed signals rate cut in September as inflation cools"
    names = {narrative.name for narrative in narratives}
    assert "Rate Cut Cycle" in names
    assert "Middle East Escalation" in names
