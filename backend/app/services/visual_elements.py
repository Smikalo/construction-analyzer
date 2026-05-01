"""Helpers for normalizing parser-produced visual summaries."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.document_elements import DocumentElement

VISUAL_ELEMENT_TYPES = ("chart", "diagram", "drawing", "image")
VISUAL_EXTRACTION_MODE = "visual_summary"
APPROXIMATE_VALUE_WARNING = "approximate_values"
_VISUAL_ELEMENT_TYPE_SET = set(VISUAL_ELEMENT_TYPES)


def visual_element_from_summary(
    summary: str | None,
    *,
    element_type: str,
    source: str,
    document_id: str | None = None,
    path: str | None = None,
    page: int | None = None,
    confidence: float | None = None,
    labels: Sequence[object | None] = (),
    relationships: Sequence[object | None] = (),
    uncertainty: str | None = None,
    approximate: bool = False,
    warnings: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
) -> DocumentElement | None:
    """Build a visual-summary ``DocumentElement`` from parser output.

    The helper is intentionally pure: it only normalizes already-produced visual
    evidence into the shared document-element contract, without calling a parser
    runtime, registry, knowledge base, or image-processing dependency.
    """
    if element_type not in _VISUAL_ELEMENT_TYPE_SET:
        raise ValueError(f"unsupported visual element type: {element_type}")

    summary_text = _collapse_whitespace(summary)
    normalized_labels = _normalize_text_items(labels)
    normalized_relationships = _normalize_text_items(relationships)
    uncertainty_text = _collapse_whitespace(uncertainty)

    if (
        not summary_text
        and not normalized_labels
        and not normalized_relationships
        and not uncertainty_text
    ):
        return None

    rendered_lines: list[str] = []
    if summary_text:
        rendered_lines.append(summary_text)
    if normalized_labels:
        rendered_lines.append(f"Labels: {'; '.join(normalized_labels)}")
    if normalized_relationships:
        rendered_lines.append(f"Relationships: {'; '.join(normalized_relationships)}")
    if uncertainty_text:
        rendered_lines.append(f"Uncertainty: {uncertainty_text}")

    element_metadata: dict[str, Any] = {
        "visual_summary_chars": len(summary_text),
    }
    if normalized_labels:
        element_metadata["labels"] = normalized_labels
    if normalized_relationships:
        element_metadata["relationships"] = normalized_relationships
    if uncertainty_text:
        element_metadata["uncertainty"] = uncertainty_text
    if approximate:
        element_metadata["approximate"] = True
    if metadata:
        element_metadata.update(metadata)

    return DocumentElement(
        document_id=document_id,
        source=source,
        path=path,
        page=page,
        element_type=element_type,
        extraction_mode=VISUAL_EXTRACTION_MODE,
        content="\n".join(rendered_lines),
        confidence=confidence,
        warnings=_merge_warnings(
            warnings,
            (APPROXIMATE_VALUE_WARNING,) if approximate else (),
        ),
        metadata=element_metadata,
    )


def _collapse_whitespace(text: object | None) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split())


def _normalize_text_items(values: Sequence[object | None]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        text = _collapse_whitespace(value)
        if text:
            normalized.append(text)
    return normalized


def _merge_warnings(
    explicit_warnings: Sequence[str],
    generated_warnings: Sequence[str],
) -> tuple[str, ...]:
    merged: list[str] = []
    for warning in (*explicit_warnings, *generated_warnings):
        if warning and warning not in merged:
            merged.append(warning)
    return tuple(merged)


__all__ = [
    "APPROXIMATE_VALUE_WARNING",
    "VISUAL_ELEMENT_TYPES",
    "VISUAL_EXTRACTION_MODE",
    "visual_element_from_summary",
]
