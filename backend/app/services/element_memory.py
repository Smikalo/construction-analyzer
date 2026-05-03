"""Format parsed document elements for knowledge-base memory writes."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from typing import Any

from app.services.document_elements import DocumentElement


def chunk_element(element: DocumentElement, *, size: int, overlap: int) -> Iterator[str]:
    """Yield chunked text for a document element using ingestion chunk semantics."""
    from app.services.ingestion import _chunk

    yield from _chunk(element.content, size, overlap)


def format_provenance_header(element: DocumentElement) -> str:
    """Return the deterministic one-line provenance header for a memory chunk."""
    fields = [f"source={_normalize_header_scalar(element.source) or ''}"]
    if element.page is not None:
        fields.append(f"page={element.page}")
    fields.extend(_engineering_provenance_fields(element))
    fields.extend(
        [
            f"element={element.element_type}",
            f"extraction={element.extraction_mode}",
        ]
    )

    certainty = _normalize_header_scalar(element.metadata.get("extraction_certainty"))
    if certainty is not None:
        fields.append(f"certainty={certainty}")
    if element.confidence is not None:
        fields.append(f"confidence={element.confidence}")
    warnings = _normalize_header_value(element.warnings)
    if warnings is not None:
        fields.append(f"warnings={warnings}")
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
        key: value for key, value in standard_metadata.items() if key == "page" or value is not None
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


def _engineering_provenance_fields(element: DocumentElement) -> list[str]:
    metadata = element.metadata
    fields: list[str] = []

    _append_field(fields, "section", metadata.get("section_heading"))
    _append_field(fields, "sheet", metadata.get("xlsx_sheet"))
    _append_field(fields, "cell", metadata.get("xlsx_cell"))
    _append_field(fields, "range", metadata.get("xlsx_range"))
    _append_field(fields, "table", metadata.get("xlsx_table_name"))
    _append_field(fields, "range_name", metadata.get("xlsx_range_name"))
    _append_field(fields, "label", metadata.get("xlsx_label"))
    _append_field(fields, "unit", metadata.get("xlsx_unit"))
    _append_list_field(fields, "layers", metadata.get("drawing_layers"))
    _append_list_field(fields, "views", metadata.get("drawing_views"))
    _append_list_field(fields, "entities", metadata.get("drawing_entities"))

    fact_type = _normalize_header_scalar(metadata.get("drawing_fact_type"))
    if fact_type is not None and fact_type != "summary":
        _append_field(fields, "fact", fact_type)
        fact_value_label = _drawing_fact_value_label(
            fact_type, metadata.get("drawing_fact_subtype")
        )
        _append_field(fields, fact_value_label, metadata.get("drawing_fact_value"))
        _append_field(fields, "line", metadata.get("drawing_line_number"))

    return fields


def _drawing_fact_value_label(fact_type: str, fact_subtype: object | None) -> str:
    subtype = _normalize_header_scalar(fact_subtype)
    if subtype == "view":
        return "view"
    if subtype == "entity":
        return "entity"
    if fact_type in {"layer", "label"}:
        return fact_type
    return "value"


def _append_field(fields: list[str], label: str, value: object | None) -> None:
    normalized = _normalize_header_value(value)
    if normalized is not None:
        fields.append(f"{label}={normalized}")


def _append_list_field(fields: list[str], label: str, value: object | None) -> None:
    normalized = _normalize_header_value(value)
    if normalized is not None:
        fields.append(f"{label}={normalized}")


def _normalize_header_value(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = _normalize_header_list(value)
        if not items:
            return None
        return ",".join(items)
    return _normalize_header_scalar(value)


def _normalize_header_list(values: Sequence[object | None]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _normalize_header_scalar(value)
        if item is None or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _normalize_header_scalar(value: object | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    text = re.sub(r"\s*;\s*", ", ", text)
    text = " ".join(text.split())
    return text or None


__all__ = [
    "chunk_and_format",
    "chunk_element",
    "format_element_for_memory",
    "format_provenance_header",
]
