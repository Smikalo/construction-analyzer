"""Helpers for normalizing parser-produced table evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.document_elements import DocumentElement

RAGGED_TABLE_WARNING = "ragged_table_rows_normalized"
TableRows = Sequence[Sequence[object | None]]


def normalize_table_rows(rows: TableRows) -> tuple[list[list[str]], tuple[str, ...]]:
    """Normalize structured parser table rows into rectangular text cells.

    Cell content is coerced to text, whitespace is collapsed, and Markdown pipe
    delimiters are escaped so the rendered table remains parseable. Ragged rows
    are padded to the widest row and reported as a warning.
    """
    source_rows = [list(row) for row in rows]
    if not source_rows:
        return [], ()

    column_count = max((len(row) for row in source_rows), default=0)
    if column_count == 0:
        return [], ()

    warnings: list[str] = []
    if any(len(row) != column_count for row in source_rows):
        warnings.append(RAGGED_TABLE_WARNING)

    normalized_rows: list[list[str]] = []
    for row in source_rows:
        normalized = [_normalize_cell(cell) for cell in row]
        normalized.extend("" for _ in range(column_count - len(normalized)))
        normalized_rows.append(normalized)

    if not any(cell for row in normalized_rows for cell in row):
        return [], ()

    return normalized_rows, tuple(warnings)


def table_to_markdown(rows: TableRows) -> str:
    """Render structured rows as deterministic Markdown-style table text."""
    normalized_rows, _warnings = normalize_table_rows(rows)
    if not normalized_rows:
        return ""

    header = normalized_rows[0]
    separator = ["---"] * len(header)
    body_rows = normalized_rows[1:]
    rendered_rows = [_render_markdown_row(header), _render_markdown_row(separator)]
    rendered_rows.extend(_render_markdown_row(row) for row in body_rows)
    return "\n".join(rendered_rows)


def table_element_from_rows(
    rows: TableRows,
    *,
    source: str,
    document_id: str | None = None,
    path: str | None = None,
    page: int | None = None,
    confidence: float | None = None,
    warnings: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
) -> DocumentElement | None:
    """Build a table `DocumentElement` from structured parser output rows."""
    normalized_rows, generated_warnings = normalize_table_rows(rows)
    if not normalized_rows:
        return None

    element_metadata: dict[str, Any] = {
        "table_rows": len(normalized_rows),
        "table_columns": len(normalized_rows[0]),
    }
    if metadata:
        element_metadata.update(metadata)

    return DocumentElement(
        document_id=document_id,
        source=source,
        path=path,
        page=page,
        element_type="table",
        extraction_mode="pdf_table",
        content=_render_normalized_table(normalized_rows),
        confidence=confidence,
        warnings=_merge_warnings(warnings, generated_warnings),
        metadata=element_metadata,
    )


def _normalize_cell(cell: object | None) -> str:
    if cell is None:
        return ""
    collapsed = " ".join(str(cell).split())
    return collapsed.replace("|", r"\|")


def _render_normalized_table(rows: Sequence[Sequence[str]]) -> str:
    header = rows[0]
    separator = ["---"] * len(header)
    body_rows = rows[1:]
    rendered_rows = [_render_markdown_row(header), _render_markdown_row(separator)]
    rendered_rows.extend(_render_markdown_row(row) for row in body_rows)
    return "\n".join(rendered_rows)


def _render_markdown_row(row: Sequence[str]) -> str:
    return f"| {' | '.join(row)} |"


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
    "RAGGED_TABLE_WARNING",
    "normalize_table_rows",
    "table_element_from_rows",
    "table_to_markdown",
]
