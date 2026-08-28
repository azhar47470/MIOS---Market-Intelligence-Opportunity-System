from typing import Protocol

from app.domain.knowledge import KnowledgeCategory, KnowledgeRecord, RelationshipRecord


class KnowledgeRepository(Protocol):
    def upsert(self, record: KnowledgeRecord) -> None:
        """Create or update a knowledge record."""

    def get(self, record_id: str) -> KnowledgeRecord | None:
        """Load a record by ID."""

    def search(
        self,
        query: str,
        category: KnowledgeCategory | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeRecord, ...]:
        """Search records by simple text query and optional category."""


class RelationshipRepository(Protocol):
    def upsert_relationship(self, relationship: RelationshipRecord) -> None:
        """Create or update a relationship edge."""

    def list_relationships(self, entity: str | None = None) -> tuple[RelationshipRecord, ...]:
        """List relationship edges, optionally scoped to an entity."""


class KnowledgeBaseService:
    def __init__(
        self,
        knowledge_repository: KnowledgeRepository,
        relationship_repository: RelationshipRepository,
    ) -> None:
        self._knowledge_repository = knowledge_repository
        self._relationship_repository = relationship_repository

    def remember(self, record: KnowledgeRecord) -> None:
        self._knowledge_repository.upsert(record)

    def connect(self, relationship: RelationshipRecord) -> None:
        self._relationship_repository.upsert_relationship(relationship)

    def recall(
        self,
        query: str,
        category: KnowledgeCategory | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeRecord, ...]:
        return self._knowledge_repository.search(query=query, category=category, limit=limit)

    def relationships_for(self, entity: str) -> tuple[RelationshipRecord, ...]:
        return self._relationship_repository.list_relationships(entity=entity)
