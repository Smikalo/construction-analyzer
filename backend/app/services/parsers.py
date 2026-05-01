"""Document parser seam for uploaded-file ingestion."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from app.services.document_elements import DocumentElement


class DocumentParser(Protocol):
    """Protocol for parser objects that turn files into typed elements."""

    def parse(
        self,
        path: str,
        *,
        source: str,
        document_id: str | None,
    ) -> list[DocumentElement]:
        """Parse a document into normalized text-bearing elements."""


def parse_pdf(
    path: str,
    *,
    source: str,
    document_id: str | None = None,
) -> list[DocumentElement]:
    """Parse a PDF into one paragraph element per non-empty text page."""
    reader = PdfReader(path)
    elements: list[DocumentElement] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            continue
        elements.append(
            DocumentElement(
                document_id=document_id,
                source=source,
                path=path,
                page=page_number,
                element_type="paragraph",
                extraction_mode="pdf_text",
                content=text,
                confidence=None,
                warnings=(),
            )
        )
    return elements


def parse_markdown(
    path: str,
    *,
    source: str,
    document_id: str | None = None,
) -> list[DocumentElement]:
    """Parse Markdown text into a single paragraph element."""
    return _parse_text_file(
        path,
        source=source,
        document_id=document_id,
        extraction_mode="markdown",
    )


def parse_text(
    path: str,
    *,
    source: str,
    document_id: str | None = None,
) -> list[DocumentElement]:
    """Parse plain text into a single paragraph element."""
    return _parse_text_file(path, source=source, document_id=document_id, extraction_mode="text")


def parse_document(
    path: str,
    *,
    source: str,
    document_id: str | None = None,
) -> list[DocumentElement]:
    """Dispatch to a parser by file extension, returning [] for unsupported files."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(path, source=source, document_id=document_id)
    if ext in (".md", ".markdown"):
        return parse_markdown(path, source=source, document_id=document_id)
    if ext == ".txt":
        return parse_text(path, source=source, document_id=document_id)
    return []


def _parse_text_file(
    path: str,
    *,
    source: str,
    document_id: str | None,
    extraction_mode: str,
) -> list[DocumentElement]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    return [
        DocumentElement(
            document_id=document_id,
            source=source,
            path=path,
            page=None,
            element_type="paragraph",
            extraction_mode=extraction_mode,
            content=text,
            confidence=None,
            warnings=(),
        )
    ]


__all__ = [
    "DocumentParser",
    "parse_document",
    "parse_markdown",
    "parse_pdf",
    "parse_text",
]
