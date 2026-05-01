"""Helpers for normalizing parser-produced OCR evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.document_elements import DocumentElement

OCR_ELEMENT_TYPE = "ocr_text"
OCR_EXTRACTION_MODE = "ocr"


def is_low_text_page(text: str | None, *, min_chars: int = 20) -> bool:
    """Return whether parser text is too sparse to trust without OCR fallback.

    Text is measured after whitespace collapse so line/page-layout artifacts do
    not make a scanned page look text-rich. ``None`` and blank text are always
    low-text pages, even when ``min_chars`` is zero.
    """
    if min_chars < 0:
        raise ValueError("min_chars must be >= 0")

    collapsed = _collapse_whitespace(text)
    if not collapsed:
        return True
    return len(collapsed) < min_chars


def ocr_element_from_text(
    text: str | None,
    *,
    source: str,
    document_id: str | None = None,
    path: str | None = None,
    page: int | None = None,
    confidence: float | None = None,
    warnings: Sequence[str] = (),
    low_text_threshold: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentElement | None:
    """Build an OCR text ``DocumentElement`` from OCR runtime output.

    The helper intentionally has no OCR runtime side effects. It only
    normalizes already-extracted OCR text into the shared parser-to-ingestion
    element contract.
    """
    if low_text_threshold is not None and low_text_threshold < 0:
        raise ValueError("low_text_threshold must be >= 0")

    content = _collapse_whitespace(text)
    if not content:
        return None

    element_metadata: dict[str, Any] = {
        "ocr_text_chars": len(content),
    }
    if low_text_threshold is not None:
        element_metadata["low_text_threshold"] = low_text_threshold
    if metadata:
        element_metadata.update(metadata)

    return DocumentElement(
        document_id=document_id,
        source=source,
        path=path,
        page=page,
        element_type=OCR_ELEMENT_TYPE,
        extraction_mode=OCR_EXTRACTION_MODE,
        content=content,
        confidence=confidence,
        warnings=tuple(warnings),
        metadata=element_metadata,
    )


def _collapse_whitespace(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(text.split())


__all__ = [
    "OCR_ELEMENT_TYPE",
    "OCR_EXTRACTION_MODE",
    "is_low_text_page",
    "ocr_element_from_text",
]
