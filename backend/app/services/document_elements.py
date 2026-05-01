"""Typed document element model shared by parser and ingestion services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DocumentElement:
    """Normalized text-bearing element extracted from an uploaded document."""

    document_id: str | None = None
    source: str = ""
    path: str | None = None
    page: int | None = None
    element_type: str = "paragraph"
    extraction_mode: str = "text"
    content: str = ""
    confidence: float | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["DocumentElement"]
