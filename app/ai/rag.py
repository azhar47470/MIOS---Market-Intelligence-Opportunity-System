import re

from app.application.knowledge_base import KnowledgeRepository
from app.domain.ai import AIContext
from app.domain.knowledge import KnowledgeCategory, KnowledgeRecord


class KnowledgeRetriever:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    def enrich(
        self,
        context: AIContext,
        query: str,
        category: KnowledgeCategory | None = None,
        limit: int = 5,
    ) -> AIContext:
        """Retrieve knowledge records relevant to ``query`` and embed them into the
        context facts.

        The repository does single-substring matching, but callers pass long combined
        queries (regime + themes + drivers), which would never match as a whole. So the
        query is tokenized into meaningful words and any record matching *any* token is
        a candidate; full-query matches are ranked first, then token matches.
        """
        candidates: dict[str, KnowledgeRecord] = {}
        for record in self._repository.search(
            query=query, category=category, limit=limit * 4
        ):
            candidates[record.record_id] = record
        tokens = [
            token
            for token in re.split(r"\W+", query.lower())
            if len(token) > 2
        ]
        if not tokens and not candidates:
            return context.model_copy(
                update={
                    "retrieved_record_ids": (),
                    "facts": dict(context.facts),
                }
            )
        if not candidates:
            for token in tokens:
                for record in self._repository.search(
                    query=token, category=category, limit=limit * 2
                ):
                    candidates.setdefault(record.record_id, record)
        records = tuple(candidates.values())[:limit]
        updated_facts = dict(context.facts)
        if records:
            updated_facts["knowledge_records"] = [_record_facts(record) for record in records]
        return context.model_copy(
            update={
                "retrieved_record_ids": tuple(record.record_id for record in records),
                "facts": updated_facts,
            }
        )


def _record_facts(record: KnowledgeRecord) -> dict:
    return {
        "record_id": record.record_id,
        "category": record.category.value,
        "title": record.title,
        "body": record.body,
        "tags": list(record.tags),
        "confidence": record.confidence,
        "source": record.source,
    }
