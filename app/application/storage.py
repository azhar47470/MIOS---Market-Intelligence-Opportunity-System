from enum import StrEnum
from typing import Protocol

from pydantic import Field

from app.domain.common import DomainModel


class StorageLayer(StrEnum):
    RELATIONAL = "relational"
    CACHE = "cache"
    TIME_SERIES = "time_series"
    OBJECT = "object"
    GRAPH = "graph"


class StorageHealth(DomainModel):
    layer: StorageLayer
    status: str = Field(min_length=1, max_length=80)
    detail: str | None = Field(default=None, max_length=500)


class RelationalStore(Protocol):
    def health(self) -> StorageHealth:
        """Report relational database health."""


class CacheStore(Protocol):
    def health(self) -> StorageHealth:
        """Report cache health."""


class TimeSeriesStore(Protocol):
    def health(self) -> StorageHealth:
        """Report time-series storage health."""


class ObjectStore(Protocol):
    def health(self) -> StorageHealth:
        """Report object storage health."""


class GraphStore(Protocol):
    def health(self) -> StorageHealth:
        """Report knowledge graph storage health."""
