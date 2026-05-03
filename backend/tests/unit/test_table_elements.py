"""Tests for table element normalization helpers."""

from __future__ import annotations

from app.services.table_elements import (
    RAGGED_TABLE_WARNING,
    normalize_table_rows,
    table_element_from_rows,
    table_to_markdown,
)


def test_table_to_markdown_renders_header_separator_and_rows() -> None:
    rows = [
        ["Spec", "Value"],
        ["Height", "10 m"],
        ["Load", "5 kN"],
    ]

    assert table_to_markdown(rows) == (
        "| Spec | Value |\n| --- | --- |\n| Height | 10 m |\n| Load | 5 kN |"
    )


def test_normalize_table_rows_collapses_whitespace_and_escapes_pipes() -> None:
    rows = [["Item", "Notes"], ["A | B", "line one\nline two"]]

    normalized, warnings = normalize_table_rows(rows)

    assert warnings == ()
    assert normalized == [["Item", "Notes"], [r"A \| B", "line one line two"]]
    assert table_to_markdown(rows) == (
        "| Item | Notes |\n"
        "| --- | --- |\n"
        r"| A \| B | line one line two |"
    )


def test_table_element_from_rows_sets_table_contract_fields() -> None:
    element = table_element_from_rows(
        [["Room", "Area"], ["A101", "42 m2"]],
        document_id="doc-table",
        source="schedule.pdf",
        path="backend/data/documents/schedule.pdf",
        page=7,
        confidence=0.86,
        warnings=("merged_cells",),
        metadata={"caption": "Room schedule"},
    )

    assert element is not None
    assert element.document_id == "doc-table"
    assert element.source == "schedule.pdf"
    assert element.path == "backend/data/documents/schedule.pdf"
    assert element.page == 7
    assert element.element_type == "table"
    assert element.extraction_mode == "pdf_table"
    assert element.content == "| Room | Area |\n| --- | --- |\n| A101 | 42 m2 |"
    assert element.confidence == 0.86
    assert element.warnings == ("merged_cells",)
    assert element.metadata == {
        "table_rows": 2,
        "table_columns": 2,
        "caption": "Room schedule",
    }


def test_ragged_rows_are_padded_and_warned() -> None:
    element = table_element_from_rows(
        [["Item", "Count", "Notes"], ["Door", 4], ["Window", 2, "tempered"]],
        source="takeoff.pdf",
        page=3,
    )

    assert element is not None
    assert element.content == (
        "| Item | Count | Notes |\n| --- | --- | --- |\n| Door | 4 |  |\n| Window | 2 | tempered |"
    )
    assert element.warnings == (RAGGED_TABLE_WARNING,)
    assert element.metadata == {"table_rows": 3, "table_columns": 3}


def test_table_element_deduplicates_explicit_and_generated_warnings() -> None:
    element = table_element_from_rows(
        [["A", "B"], ["only-a"]],
        source="warn.pdf",
        warnings=(RAGGED_TABLE_WARNING, "low_confidence"),
    )

    assert element is not None
    assert element.warnings == (RAGGED_TABLE_WARNING, "low_confidence")


def test_empty_or_blank_tables_return_no_content_or_element() -> None:
    assert table_to_markdown([]) == ""
    assert table_to_markdown([[" ", None], []]) == ""
    assert table_element_from_rows([], source="empty.pdf") is None
    assert table_element_from_rows([[" ", None], []], source="empty.pdf") is None
