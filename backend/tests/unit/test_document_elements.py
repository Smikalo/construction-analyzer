"""Tests for the shared typed document element model."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.document_elements import DocumentElement


def test_document_element_defaults_cover_optional_provenance_fields() -> None:
    element = DocumentElement(source="plan.pdf", content="page body")

    assert element.document_id is None
    assert element.source == "plan.pdf"
    assert element.path is None
    assert element.page is None
    assert element.element_type == "paragraph"
    assert element.extraction_mode == "text"
    assert element.content == "page body"
    assert element.confidence is None
    assert element.warnings == ()
    assert element.metadata == {}


def test_document_element_is_frozen() -> None:
    element = DocumentElement(source="plan.pdf", content="page body")

    with pytest.raises(FrozenInstanceError):
        element.source = "other.pdf"  # type: ignore[misc]


def test_metadata_defaults_are_independent_instances() -> None:
    first = DocumentElement(source="first.txt", content="first body")
    second = DocumentElement(source="second.txt", content="second body")

    first.metadata["source_id"] = "first"

    assert first.metadata == {"source_id": "first"}
    assert second.metadata == {}
