from datetime import UTC, datetime, timedelta
import threading
from typing import Protocol

from pydantic import Field

from app.domain.common import DomainModel


class CacheEntry(DomainModel):
    key: str = Field(min_length=1, max_length=240)
    payload: dict
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


class CacheRepository(Protocol):
    def get(self, key: str) -> CacheEntry | None:
        """Return a cache entry if present."""

    def set(self, key: str, payload: dict, ttl_seconds: int) -> None:
        """Store a serializable payload with a TTL."""


class InMemoryCacheRepository(CacheRepository):
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            # Proactively evict expired entries to prevent memory leak
            self._evict_expired_locked()
            entry = self._entries.get(key)
            if entry is None or entry.is_expired:
                if entry is not None:
                    # Remove it immediately if expired
                    self._entries.pop(key, None)
                return None
            return entry

    def set(self, key: str, payload: dict, ttl_seconds: int) -> None:
        with self._lock:
            # Proactively evict expired entries to prevent memory leak
            self._evict_expired_locked()
            self._entries[key] = CacheEntry(
                key=key,
                payload=payload,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )

    def _evict_expired_locked(self) -> None:
        now = datetime.now(UTC)
        # Find all expired keys
        expired_keys = [k for k, v in self._entries.items() if now >= v.expires_at]
        for k in expired_keys:
            self._entries.pop(k, None)
