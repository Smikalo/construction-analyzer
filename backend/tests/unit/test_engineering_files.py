"""Tests for engineering file classification helpers."""

from __future__ import annotations

import pytest

from app.services.engineering_files import (
    BACKUP_OR_TEMP_EXTENSIONS,
    SUPPORTED_CAD_EXPORT_EXTENSIONS,
    SUPPORTED_ENGINEERING_DOCUMENT_EXTENSIONS,
    SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS,
    SUPPORTED_ENGINEERING_WORKBOOK_EXTENSIONS,
    SUPPORTED_INGEST_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    ClassificationResult,
    classify,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "notes.pdf",
            ClassificationResult(
                role="text_document",
                route="parser",
                reason=None,
                extension=".pdf",
            ),
        ),
        (
            "report.docx",
            ClassificationResult(
                role="engineering_document",
                route="parser",
                reason=None,
                extension=".docx",
            ),
        ),
        (
            "sheet.xlsx",
            ClassificationResult(
                role="engineering_workbook",
                route="skip",
                reason="xlsx_extractor_pending",
                extension=".xlsx",
            ),
        ),
        (
            "drawing.dwg",
            ClassificationResult(
                role="cad_export",
                route="skip",
                reason="converter_pending",
                extension=".dwg",
            ),
        ),
        (
            "photo.png",
            ClassificationResult(
                role="engineering_image",
                route="skip",
                reason="image_extractor_pending",
                extension=".png",
            ),
        ),
        (
            "backup.bak",
            ClassificationResult(
                role="backup_or_temp",
                route="skip",
                reason="backup_or_temp",
                extension=".bak",
            ),
        ),
    ],
)
def test_classify_maps_supported_roles_deterministically(
    filename: str,
    expected: ClassificationResult,
) -> None:
    assert classify(filename) == expected


@pytest.mark.parametrize(
    "filename",
    ["Plan.PDF", "report.DOCX", "Drawing.Dwg"],
)
def test_classify_is_case_insensitive_for_extensions(filename: str) -> None:
    result = classify(filename)

    assert result.extension == filename[filename.rfind(".") :].lower()
    assert result == classify(filename.lower())


def test_classify_folder_segments_override_extension() -> None:
    result = classify("sheet.xlsx", folder_segments=("project", "archive", "q1"))

    assert result == ClassificationResult(
        role="backup_or_temp",
        route="skip",
        reason="backup_or_temp",
        extension=".xlsx",
    )


def test_classify_office_lock_files_are_backup_or_temp() -> None:
    assert classify("~$lock.docx") == ClassificationResult(
        role="backup_or_temp",
        route="skip",
        reason="backup_or_temp",
        extension=".docx",
    )


@pytest.mark.parametrize("filename", ["mystery.exe", "README"])
def test_classify_marks_unsupported_inputs_as_unsupported(filename: str) -> None:
    assert classify(filename) == ClassificationResult(
        role="unsupported",
        route="skip",
        reason="unsupported_extension",
        extension=".exe" if "." in filename else "",
    )


def test_supported_ingest_extensions_include_existing_text_set() -> None:
    assert {".pdf", ".md", ".markdown", ".txt"}.issubset(SUPPORTED_INGEST_EXTENSIONS)
    assert SUPPORTED_TEXT_EXTENSIONS <= SUPPORTED_INGEST_EXTENSIONS
    assert SUPPORTED_ENGINEERING_DOCUMENT_EXTENSIONS <= SUPPORTED_INGEST_EXTENSIONS
    assert SUPPORTED_ENGINEERING_WORKBOOK_EXTENSIONS <= SUPPORTED_INGEST_EXTENSIONS
    assert SUPPORTED_CAD_EXPORT_EXTENSIONS <= SUPPORTED_INGEST_EXTENSIONS
    assert SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS <= SUPPORTED_INGEST_EXTENSIONS
    assert BACKUP_OR_TEMP_EXTENSIONS <= SUPPORTED_INGEST_EXTENSIONS
