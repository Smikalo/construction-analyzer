"""KnowledgeBase interface.

Anything that can store text and recall it semantically can be a KnowledgeBase.
This abstraction lets us swap MemoryPalace for the in-memory Fake under test, and
keeps the agent decoupled from the concrete persistence layer.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class MemoryRecord(TypedDict):
    id: str
    content: str
    metadata: dict[str, Any]
    score: float


@runtime_checkable
class KnowledgeBase(Protocol):
    async def remember(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a piece of text and return a stable id."""

    async def recall(self, query: str, k: int = 5) -> list[MemoryRecord]:
        """Return up to `k` semantically related memories for `query`."""

    async def health(self) -> bool:
        """Return True if the underlying store is reachable."""
