import json
from pathlib import Path

from app.application.knowledge_base import KnowledgeRepository, RelationshipRepository
from app.domain.knowledge import KnowledgeCategory, KnowledgeRecord, RelationshipRecord


class JsonKnowledgeRepository(KnowledgeRepository, RelationshipRepository):
    def __init__(self, root: str | Path = "knowledge") -> None:
        self._root = Path(root)
        self._relationships_path = self._root / "relationships" / "relationships.json"

    def upsert(self, record: KnowledgeRecord) -> None:
        records = {item.record_id: item for item in self._load_category(record.category)}
        records[record.record_id] = record
        self._write_category(record.category, tuple(records.values()))

    def get(self, record_id: str) -> KnowledgeRecord | None:
        for category in KnowledgeCategory:
            for record in self._load_category(category):
                if record.record_id == record_id:
                    return record
        return None

    def search(
        self,
        query: str,
        category: KnowledgeCategory | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeRecord, ...]:
        query_lower = query.lower()
        categories = (category,) if category else tuple(KnowledgeCategory)
        matches: list[KnowledgeRecord] = []
        for current_category in categories:
            for record in self._load_category(current_category):
                haystack = f"{record.title} {record.body} {' '.join(record.tags)}".lower()
                if query_lower in haystack:
                    matches.append(record)
        return tuple(matches[:limit])

    def upsert_relationship(self, relationship: RelationshipRecord) -> None:
        relationships = {item.relationship_id: item for item in self.list_relationships()}
        relationships[relationship.relationship_id] = relationship
        self._write_relationships(tuple(relationships.values()))

    def list_relationships(self, entity: str | None = None) -> tuple[RelationshipRecord, ...]:
        if not self._relationships_path.exists():
            return ()
        with self._relationships_path.open("r", encoding="utf-8") as handle:
            raw_relationships = json.load(handle)
        relationships = tuple(RelationshipRecord.model_validate(item) for item in raw_relationships)
        if entity is None:
            return relationships
        entity_lower = entity.lower()
        return tuple(
            item
            for item in relationships
            if item.from_entity.lower() == entity_lower or item.to_entity.lower() == entity_lower
        )

    def _category_path(self, category: KnowledgeCategory) -> Path:
        return self._root / category.value / "records.json"

    def _load_category(self, category: KnowledgeCategory) -> tuple[KnowledgeRecord, ...]:
        path = self._category_path(category)
        if not path.exists():
            return ()
        with path.open("r", encoding="utf-8") as handle:
            raw_records = json.load(handle)
        return tuple(KnowledgeRecord.model_validate(item) for item in raw_records)

    def _write_category(
        self, category: KnowledgeCategory, records: tuple[KnowledgeRecord, ...]
    ) -> None:
        path = self._category_path(category)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump([record.model_dump(mode="json") for record in records], handle, indent=2)

    def _write_relationships(self, relationships: tuple[RelationshipRecord, ...]) -> None:
        self._relationships_path.parent.mkdir(parents=True, exist_ok=True)
        with self._relationships_path.open("w", encoding="utf-8") as handle:
            json.dump(
                [relationship.model_dump(mode="json") for relationship in relationships],
                handle,
                indent=2,
            )
