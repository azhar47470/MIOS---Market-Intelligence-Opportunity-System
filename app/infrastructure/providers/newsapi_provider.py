from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import NewsEventSnapshot
from app.infrastructure.providers.base import ProviderBase, logger, parse_datetime

GOLD_RELEVANT_QUERY = 'gold OR XAU/USD OR "gold price"'


class NewsAPIProvider(ProviderBase):
    """Adapt NewsAPI articles to the provider-neutral news snapshot contract."""

    async def news_events(self, query: str) -> ProviderResult[tuple[NewsEventSnapshot, ...]]:
        status, payload, error = self._get_json(
            "everything",
            {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "20",
            },
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            events = tuple(
                NewsEventSnapshot(
                    headline=str(row["title"]),
                    url=str(row["url"]),
                    # NewsAPI does not provide GDELT's numeric tone field.
                    tone=None,
                    date=parse_datetime(row["publishedAt"]),
                )
                for row in payload.get("articles", ())
                if row.get("title") not in (None, "", "[Removed]")
                and row.get("url")
                and row.get("publishedAt")
            )
            return self._result(ContractStatus.SUCCESS, data=events)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
