"""v2 news-engine connector registry — all available source connectors.

Connectors are injected with the platform `HttpClient` (stdlib urllib) so the
port stays dependency-free.
"""

from __future__ import annotations

from app.application.http import HttpClient
from app.infrastructure.news.base import BaseConnector
from app.infrastructure.news.discovery_apis import (
    TheNewsAPIConnector,
    WorldNewsAPIConnector,
)
from app.infrastructure.news.ecb import ECBConnector
from app.infrastructure.news.fed import FedConnector
from app.infrastructure.news.finnhub import FinnhubConnector
from app.infrastructure.news.google_rss import GoogleRSSConnector
from app.infrastructure.news.marketaux import MarketAuxConnector
from app.infrastructure.news.official_sources import (
    BISConnector,
    CFTCConnector,
    IMFConnector,
    LBMAConnector,
    TreasuryConnector,
    WGCConnector,
)
from app.infrastructure.news.reuters import ReutersConnector
from app.infrastructure.news.rss_bridge import RSSBridgeConnector


def build_all_connectors(http_client: HttpClient) -> list[BaseConnector]:
    """Construct all 15 connectors in tier order (1=authoritative … 5=emergency)."""
    return [
        ReutersConnector(http_client),
        FedConnector(http_client),
        ECBConnector(http_client),
        IMFConnector(http_client),
        BISConnector(http_client),
        TreasuryConnector(http_client),
        WGCConnector(http_client),
        CFTCConnector(http_client),
        LBMAConnector(http_client),
        MarketAuxConnector(http_client),
        FinnhubConnector(http_client),
        GoogleRSSConnector(http_client),
        TheNewsAPIConnector(http_client),
        WorldNewsAPIConnector(http_client),
        RSSBridgeConnector(http_client),
    ]


def build_tier_map(http_client: HttpClient) -> dict[str, int]:
    return {connector.name: connector.tier for connector in build_all_connectors(http_client)}


def build_trust_map(http_client: HttpClient) -> dict[str, float]:
    return {
        connector.name: connector.trust_score for connector in build_all_connectors(http_client)
    }


__all__ = [
    "BaseConnector",
    "build_all_connectors",
    "build_tier_map",
    "build_trust_map",
]