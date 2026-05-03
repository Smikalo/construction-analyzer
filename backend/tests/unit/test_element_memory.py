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


def test_header_includes_docx_section_heading_and_normalizes_whitespace() -> None:
    element = DocumentElement(
        source="loads.docx",
        element_type="paragraph",
        extraction_mode="docx_paragraph",
        content="Foundation body",
        metadata={"section_heading": "  Site\nPrep ; Phase 1  "},
    )

    assert format_provenance_header(element) == (
        "[source=loads.docx; section=Site Prep, Phase 1; element=paragraph; "
        "extraction=docx_paragraph]\n"
    )


@pytest.mark.parametrize(
    ("metadata", "element_type", "extraction_mode", "expected_header"),
    [
        (
            {
                "xlsx_sheet": "Loads",
                "xlsx_range": "A1:B2",
                "xlsx_table_name": "LoadTable",
            },
            "table",
            "xlsx_table",
            (
                "[source=loads.xlsx; sheet=Loads; range=A1:B2; table=LoadTable; "
                "element=table; extraction=xlsx_table; confidence=1.0]\n"
            ),
        ),
        (
            {
                "xlsx_sheet": "Loads",
                "xlsx_range": "D1:E2",
                "xlsx_range_name": "RangeBlock",
            },
            "range",
            "xlsx_range",
            (
                "[source=loads.xlsx; sheet=Loads; range=D1:E2; range_name=RangeBlock; "
                "element=range; extraction=xlsx_range; confidence=1.0]\n"
            ),
        ),
    ],
)
def test_header_includes_xlsx_range_and_table_names(
    metadata: dict[str, object],
    element_type: str,
    extraction_mode: str,
    expected_header: str,
) -> None:
    element = DocumentElement(
        source="loads.xlsx",
        element_type=element_type,
        extraction_mode=extraction_mode,
        content="range body",
        confidence=1.0,
        metadata=metadata,
    )

    assert format_provenance_header(element) == expected_header


def test_header_includes_xlsx_sheet_cell_label_unit_certainty_and_missing_cache_warning() -> None:
    element = DocumentElement(
        source="loads.xlsx",
        element_type="formula",
        extraction_mode="xlsx_formula",
        content="formula body",
        confidence=1.0,
        warnings=("missing_cached_value", "missing_cached_value"),
        metadata={
            "xlsx_sheet": "Calculation Sheet",
            "xlsx_cell": "D1",
            "xlsx_label": "North [kN]",
            "xlsx_unit": "kN",
            "extraction_certainty": "exact_formula_cached_value_unknown",
        },
    )

    assert format_provenance_header(element) == (
        "[source=loads.xlsx; sheet=Calculation Sheet; cell=D1; label=North [kN]; unit=kN; "
        "element=formula; extraction=xlsx_formula; "
        "certainty=exact_formula_cached_value_unknown; confidence=1.0; "
        "warnings=missing_cached_value]\n"
    )


def test_header_includes_converted_drawing_summary_layers_views_and_entities() -> None:
    element = DocumentElement(
        source="north.dwg",
        element_type="drawing",
        extraction_mode="converted_drawing_text_summary",
        content="summary body",
        confidence=1.0,
        warnings=("converter_note",),
        metadata={
            "drawing_layers": ["A-WALL", "A-WALL", "  "],
            "drawing_views": ["Level 1", "\nLevel 1  "],
            "drawing_entities": ["Door 7", "Door 7"],
            "drawing_fact_type": "summary",
        },
    )

    assert format_provenance_header(element) == (
        "[source=north.dwg; layers=A-WALL; views=Level 1; entities=Door 7; "
        "element=drawing; extraction=converted_drawing_text_summary; confidence=1.0; "
        "warnings=converter_note]\n"
    )


@pytest.mark.parametrize(
    ("metadata", "expected_fields"),
    [
        (
            {
                "drawing_fact_type": "layer",
                "drawing_fact_value": "A-WALL",
                "drawing_line_number": 12,
            },
            "fact=layer; layer=A-WALL; line=12",
        ),
        (
            {
                "drawing_fact_type": "entity_view",
                "drawing_fact_subtype": "view",
                "drawing_fact_value": "Level 1",
                "drawing_line_number": 13,
            },
            "fact=entity_view; view=Level 1; line=13",
        ),
        (
            {
                "drawing_fact_type": "entity_view",
                "drawing_fact_subtype": "entity",
                "drawing_fact_value": "Door 7",
                "drawing_line_number": 14,
            },
            "fact=entity_view; entity=Door 7; line=14",
        ),
    ],
)
def test_header_includes_converted_drawing_fact_context(
    metadata: dict[str, object],
    expected_fields: str,
) -> None:
    element = DocumentElement(
        source="north.dwg",
        page=2,
        element_type="drawing_fact",
        extraction_mode="converted_drawing_text_fact",
        content="fact body",
        confidence=1.0,
        warnings=("converter_note", "converter_note"),
        metadata=metadata,
    )

    assert format_provenance_header(element) == (
        f"[source=north.dwg; page=2; {expected_fields}; element=drawing_fact; "
        f"extraction=converted_drawing_text_fact; confidence=1.0; "
        f"warnings=converter_note]\n"
    )
