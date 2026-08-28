from app.domain.features import InstitutionalFeatureSet
from app.domain.market_data import CotPositioningSnapshot, EtfFlowSnapshot


def build_institutional_features(
    cot_positioning: tuple[CotPositioningSnapshot, ...],
    gld_flow: EtfFlowSnapshot | None,
    provider_errors: dict[str, str] | None = None,
) -> InstitutionalFeatureSet:
    errors = provider_errors or {}
    latest_net = None
    if cot_positioning:
        latest_net = sorted(cot_positioning, key=lambda item: item.report_date)[
            -1
        ].managed_money_net
    return InstitutionalFeatureSet(
        source_count=int(bool(cot_positioning)) + int(gld_flow is not None),
        latest_managed_money_net=latest_net,
        gld_daily_ounce_change=gld_flow.daily_ounce_change if gld_flow else None,
        gld_total_ounces=gld_flow.total_ounces if gld_flow else None,
        gld_total_tonnes=gld_flow.total_tonnes if gld_flow else None,
        gld_total_nav_usd=gld_flow.total_nav_usd if gld_flow else None,
        gld_shares_outstanding=gld_flow.shares_outstanding if gld_flow else None,
        gld_date=gld_flow.date.date().isoformat() if gld_flow else None,
        cot_error=errors.get("cot"),
        gld_error=errors.get("gld"),
    )
