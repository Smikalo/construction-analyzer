"""Format parsed document elements for knowledge-base memory writes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.services.document_elements import DocumentElement


def chunk_element(element: DocumentElement, *, size: int, overlap: int) -> Iterator[str]:
    """Yield chunked text for a document element using ingestion chunk semantics."""
    from app.services.ingestion import _chunk

    yield from _chunk(element.content, size, overlap)


def format_provenance_header(element: DocumentElement) -> str:
    """Return the deterministic one-line provenance header for a memory chunk."""
    fields = [
        f"source={element.source}",
    ]
    if element.page is not None:
        fields.append(f"page={element.page}")
    fields.extend(
        [
            f"element={element.element_type}",
            f"extraction={element.extraction_mode}",
        ]
    )
    if element.confidence is not None:
        fields.append(f"confidence={element.confidence}")
    if element.warnings:
        fields.append(f"warnings={','.join(element.warnings)}")
    return f"[{'; '.join(fields)}]\n"


def format_element_for_memory(
    element: DocumentElement,
    chunk_text: str,
) -> tuple[str, dict[str, Any]]:
    """Build remembered content and metadata for one element chunk."""
    content = f"{format_provenance_header(element)}{chunk_text}"
    standard_metadata: dict[str, Any] = {
        "document_id": element.document_id,
        "source": element.source,
        "path": element.path,
        "page": element.page,
        "element_type": element.element_type,
        "extraction_mode": element.extraction_mode,
        "confidence": element.confidence,
        "warnings": list(element.warnings),
    }
    metadata = {
        key: value
        for key, value in standard_metadata.items()
        if key == "page" or value is not None
    }
    metadata.update(element.metadata)
    return content, metadata


def chunk_and_format(
    element: DocumentElement,
    *,
    size: int,
    overlap: int,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield remembered content and metadata for every chunk in an element."""
    for chunk in chunk_element(element, size=size, overlap=overlap):
        yield format_element_for_memory(element, chunk)


__all__ = [
    "chunk_and_format",
    "chunk_element",
    "format_element_for_memory",
    "format_provenance_header",
]
