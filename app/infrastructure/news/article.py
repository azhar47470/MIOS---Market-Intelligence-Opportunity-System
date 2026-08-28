"""Normalized article model for the v2 news-engine connector layer."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Article:
    """Normalized article — the universal unit produced by every connector."""

    title: str
    summary: str
    content: str
    source: str
    url: str
    published_at: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    author: str = ""
    language: str = "en"
    symbols: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    region: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Title-based fingerprint for deduplication."""
        normalized = self.title.lower().strip()
        normalized = "".join(c for c in normalized if c.isalnum() or c == " ")
        normalized = " ".join(normalized.split())
        return hashlib.md5(normalized.encode()).hexdigest()