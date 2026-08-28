from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.features import MacroFeatureSet, MacroSeriesFeature
from app.domain.market_data import EconomicCalendarEvent, MacroSeriesObservation


def build_macro_features(
    observations: tuple[MacroSeriesObservation, ...],
    events: tuple[EconomicCalendarEvent, ...],
    provider_errors: dict[str, str] | None = None,
    macro_observations: tuple[MacroSeriesObservation, ...] = (),
) -> MacroFeatureSet:
    usable = [
        item for item in sorted(observations, key=lambda item: item.date) if item.value is not None
    ]
    dxy_change = None
    if len(usable) >= 2:
        first = usable[-2].value or Decimal("0")
        last = usable[-1].value or Decimal("0")
        dxy_change = ((last - first) / first) * Decimal("100") if first else Decimal("0")
    return MacroFeatureSet(
        observation_count=len(usable),
        dxy_change_percent=dxy_change,
        high_impact_us_event_count=_high_impact_us_events(events),
        macro_series=_series_features(macro_observations),
        macro_surprise_count=_macro_surprise_count(events),
        dxy_error=(provider_errors or {}).get("dxy"),
        macro_error=(provider_errors or {}).get("macro"),
    )


def _high_impact_us_events(events: tuple[EconomicCalendarEvent, ...]) -> int:
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=6)
    window_end = now + timedelta(hours=24)
    return sum(
        1
        for event in events
        if event.country.upper() == "US"
        and event.impact.lower() == "high"
        and window_start <= event.event_time <= window_end
    )


def _series_features(
    observations: tuple[MacroSeriesObservation, ...],
) -> dict[str, MacroSeriesFeature]:
    grouped: dict[str, list[MacroSeriesObservation]] = {}
    for observation in observations:
        if observation.value is not None:
            grouped.setdefault(observation.series_id, []).append(observation)
    features: dict[str, MacroSeriesFeature] = {}
    for series_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item.date)
        latest = ordered[-1].value
        previous = ordered[-2].value if len(ordered) >= 2 else None
        change = None
        if latest is not None and previous is not None and previous != 0:
            change = ((latest - previous) / abs(previous)) * Decimal("100")
        features[series_id] = MacroSeriesFeature(
            observation_count=len(ordered),
            latest_value=latest,
            change_percent=change,
        )
    return features


def _macro_surprise_count(events: tuple[EconomicCalendarEvent, ...]) -> int:
    return sum(
        1
        for event in events
        if event.actual is not None
        and event.forecast is not None
        and _numeric_value(event.actual) != _numeric_value(event.forecast)
    )


def _numeric_value(value: str) -> Decimal | None:
    cleaned = value.replace("%", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except Exception:
        return None
