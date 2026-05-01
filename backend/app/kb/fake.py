"""In-memory KnowledgeBase used by every test that does not need real Postgres.

Recall uses naive case-insensitive substring matching. That is intentional: we
do not want to ship a real embedding stack into unit tests. Tests should pin
behaviour, not similarity scores.
"""

from __future__ import annotations

import uuid
from typing import Any

from .base import KnowledgeBase, MemoryRecord


class FakeKB(KnowledgeBase):
    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []
        self._healthy = True

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = healthy

    def dump(self) -> list[MemoryRecord]:
        return list(self._records)

    async def remember(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        mid = str(uuid.uuid4())
        self._records.append(
            MemoryRecord(
                id=mid,
                content=content,
                metadata=metadata or {},
                score=1.0,
            )
        )
        return mid

    async def recall(self, query: str, k: int = 5) -> list[MemoryRecord]:
        needle = query.lower().strip()
        if not needle:
            return []
        hits = [
            MemoryRecord(
                id=r["id"],
                content=r["content"],
                metadata=dict(r["metadata"]),
                score=1.0,
            )
            for r in self._records
            if needle in r["content"].lower()
        ]
        return hits[:k]

    async def health(self) -> bool:
        return self._healthy
