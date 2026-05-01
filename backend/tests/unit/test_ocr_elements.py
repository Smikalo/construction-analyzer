"""Tests for OCR element normalization helpers."""

from __future__ import annotations

import pytest

from app.services.ocr_elements import is_low_text_page, ocr_element_from_text


@pytest.mark.parametrize("text", [None, "", "   \n\t  "])
def test_none_and_blank_text_are_low_text_pages(text: str | None) -> None:
    assert is_low_text_page(text) is True
    assert is_low_text_page(text, min_chars=0) is True


def test_low_text_page_detection_uses_collapsed_whitespace_length() -> None:
    assert is_low_text_page("ab\n  cd\t ef", min_chars=9) is True
    assert is_low_text_page("ab\n  cd\t ef", min_chars=8) is False
    assert is_low_text_page("ab\n  cd\t ef", min_chars=0) is False


def test_low_text_page_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="min_chars must be >= 0"):
        is_low_text_page("text", min_chars=-1)


def test_ocr_element_from_text_sets_ocr_contract_fields() -> None:
    element = ocr_element_from_text(
        "  Scanned\n page\ttext  ",
        document_id="doc-ocr",
        source="scan.pdf",
        path="backend/data/documents/scan.pdf",
        page=3,
        confidence=0.78,
        warnings=("low_text_page", "ocr_low_confidence"),
        low_text_threshold=20,
        metadata={"ocr_engine": "fake"},
    )

    assert element is not None
    assert element.document_id == "doc-ocr"
    assert element.source == "scan.pdf"
    assert element.path == "backend/data/documents/scan.pdf"
    assert element.page == 3
    assert element.element_type == "ocr_text"
    assert element.extraction_mode == "ocr"
    assert element.content == "Scanned page text"
    assert element.confidence == 0.78
    assert element.warnings == ("low_text_page", "ocr_low_confidence")
    assert element.metadata == {
        "ocr_text_chars": len("Scanned page text"),
        "low_text_threshold": 20,
        "ocr_engine": "fake",
    }


def test_ocr_element_preserves_warning_order_and_duplicates() -> None:
    element = ocr_element_from_text(
        "OCR body",
        source="warnings.pdf",
        warnings=("low_text_page", "low_text_page", "ocr_low_confidence"),
    )

    assert element is not None
    assert element.warnings == ("low_text_page", "low_text_page", "ocr_low_confidence")


@pytest.mark.parametrize("text", [None, "", "  \n\t  "])
def test_blank_ocr_output_returns_no_element(text: str | None) -> None:
    assert ocr_element_from_text(text, source="blank.pdf") is None


def test_ocr_element_without_optional_values_sets_minimal_metadata() -> None:
    element = ocr_element_from_text("OCR text", source="minimal.pdf")

    assert element is not None
    assert element.document_id is None
    assert element.path is None
    assert element.page is None
    assert element.confidence is None
    assert element.warnings == ()
    assert element.metadata == {"ocr_text_chars": len("OCR text")}


def test_ocr_element_rejects_negative_low_text_threshold() -> None:
    with pytest.raises(ValueError, match="low_text_threshold must be >= 0"):
        ocr_element_from_text("OCR text", source="bad.pdf", low_text_threshold=-1)
