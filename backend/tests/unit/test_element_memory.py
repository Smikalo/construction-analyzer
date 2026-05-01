"""Tests for formatting document elements into remembered KB content."""

from __future__ import annotations

import pytest

from app.services.document_elements import DocumentElement
from app.services.element_memory import (
    chunk_and_format,
    chunk_element,
    format_element_for_memory,
    format_provenance_header,
)


def test_header_includes_source_page_element_and_extraction() -> None:
    element = DocumentElement(
        source="plan.pdf",
        page=2,
        element_type="paragraph",
        extraction_mode="pdf_text",
        content="page body",
    )

    assert (
        format_provenance_header(element)
        == "[source=plan.pdf; page=2; element=paragraph; extraction=pdf_text]\n"
    )


def test_header_omits_page_for_unpaged_element() -> None:
    element = DocumentElement(
        source="scope.md",
        page=None,
        element_type="paragraph",
        extraction_mode="markdown",
        content="scope body",
    )

    assert format_provenance_header(element) == (
        "[source=scope.md; element=paragraph; extraction=markdown]\n"
    )


def test_header_includes_confidence_and_warnings_when_present() -> None:
    element = DocumentElement(
        source="scan.pdf",
        page=1,
        element_type="paragraph",
        extraction_mode="ocr",
        content="scanned body",
        confidence=0.87,
        warnings=("rotated", "low_contrast"),
    )

    assert format_provenance_header(element) == (
        "[source=scan.pdf; page=1; element=paragraph; extraction=ocr; "
        "confidence=0.87; warnings=rotated,low_contrast]\n"
    )


def test_header_omits_confidence_and_empty_warnings() -> None:
    element = DocumentElement(
        source="notes.txt",
        element_type="paragraph",
        extraction_mode="text",
        content="notes body",
        confidence=None,
        warnings=(),
    )

    header = format_provenance_header(element)

    assert "confidence=" not in header
    assert "warnings=" not in header
    assert header == "[source=notes.txt; element=paragraph; extraction=text]\n"


def test_format_element_for_memory_merges_metadata_last_and_drops_none_values() -> None:
    element = DocumentElement(
        document_id="doc-123",
        source="plan.pdf",
        path="stored/plan.pdf",
        page=2,
        element_type="paragraph",
        extraction_mode="pdf_text",
        content="page body",
        confidence=None,
        warnings=("faint",),
        metadata={"key": "val", "source": "override.pdf", "confidence": 0.5},
    )

    content, metadata = format_element_for_memory(element, "chunk body")

    assert content == (
        "[source=plan.pdf; page=2; element=paragraph; extraction=pdf_text; warnings=faint]\n"
        "chunk body"
    )
    assert metadata == {
        "document_id": "doc-123",
        "source": "override.pdf",
        "path": "stored/plan.pdf",
        "page": 2,
        "element_type": "paragraph",
        "extraction_mode": "pdf_text",
        "warnings": ["faint"],
        "key": "val",
        "confidence": 0.5,
    }


def test_format_element_for_memory_keeps_page_none_but_drops_other_none_values() -> None:
    element = DocumentElement(
        document_id=None,
        source="scope.md",
        path=None,
        page=None,
        element_type="paragraph",
        extraction_mode="markdown",
        content="scope body",
        confidence=None,
    )

    _content, metadata = format_element_for_memory(element, "scope body")

    assert metadata == {
        "source": "scope.md",
        "page": None,
        "element_type": "paragraph",
        "extraction_mode": "markdown",
        "warnings": [],
    }


def test_chunk_and_format_repeats_header_and_metadata_for_each_chunk() -> None:
    element = DocumentElement(
        document_id="doc-long",
        source="long.txt",
        path="stored/long.txt",
        page=None,
        element_type="paragraph",
        extraction_mode="text",
        content="abcdefgh",
        metadata={"key": "val"},
    )

    formatted = list(chunk_and_format(element, size=4, overlap=0))

    assert [content for content, _metadata in formatted] == [
        "[source=long.txt; element=paragraph; extraction=text]\nabcd",
        "[source=long.txt; element=paragraph; extraction=text]\nefgh",
    ]
    assert [metadata for _content, metadata in formatted] == [
        {
            "document_id": "doc-long",
            "source": "long.txt",
            "path": "stored/long.txt",
            "page": None,
            "element_type": "paragraph",
            "extraction_mode": "text",
            "warnings": [],
            "key": "val",
        },
        {
            "document_id": "doc-long",
            "source": "long.txt",
            "path": "stored/long.txt",
            "page": None,
            "element_type": "paragraph",
            "extraction_mode": "text",
            "warnings": [],
            "key": "val",
        },
    ]


@pytest.mark.parametrize("content", ["", "  \n\t  "])
def test_empty_or_whitespace_only_element_content_yields_nothing(content: str) -> None:
    element = DocumentElement(source="empty.txt", content=content)

    assert list(chunk_and_format(element, size=10, overlap=0)) == []


def test_chunk_element_uses_ingestion_chunk_validation() -> None:
    element = DocumentElement(source="bad.txt", content="content")

    with pytest.raises(ValueError, match="chunk size must be > 0"):
        list(chunk_element(element, size=0, overlap=0))
