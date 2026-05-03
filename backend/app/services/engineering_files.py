"""Pure engineering-file classification helpers for ingestion routing."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

SUPPORTED_TEXT_EXTENSIONS = frozenset({".pdf", ".md", ".markdown", ".txt"})
SUPPORTED_ENGINEERING_DOCUMENT_EXTENSIONS = frozenset({".docx"})
SUPPORTED_ENGINEERING_WORKBOOK_EXTENSIONS = frozenset({".xlsx"})
SUPPORTED_CAD_EXPORT_EXTENSIONS = frozenset({".dwg", ".vwx", ".dbn", ".ern", ".p2n", ".pln"})
SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
BACKUP_OR_TEMP_EXTENSIONS = frozenset({".bak", ".tmp"})
SUPPORTED_INGEST_EXTENSIONS = (
    SUPPORTED_TEXT_EXTENSIONS
    | SUPPORTED_ENGINEERING_DOCUMENT_EXTENSIONS
    | SUPPORTED_ENGINEERING_WORKBOOK_EXTENSIONS
    | SUPPORTED_CAD_EXPORT_EXTENSIONS
    | SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS
    | BACKUP_OR_TEMP_EXTENSIONS
)
BACKUP_FOLDER_TOKENS = frozenset({"backup", "backups", "archive", "archives", "old", "superseded"})

EngineeringRole = Literal[
    "text_document",
    "engineering_document",
    "engineering_workbook",
    "cad_export",
    "engineering_image",
    "backup_or_temp",
    "unsupported",
]
IngestionRoute = Literal["parser", "skip"]
SkipReason = Literal[
    "docx_extractor_pending",
    "xlsx_extractor_pending",
    "converter_pending",
    "image_extractor_pending",
    "backup_or_temp",
    "unsupported_extension",
]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    role: EngineeringRole
    route: IngestionRoute
    reason: SkipReason | None
    extension: str


def classify(filename: str, *, folder_segments: Sequence[str] = ()) -> ClassificationResult:
    basename = os.path.basename(filename)
    extension = os.path.splitext(basename)[1].lower()

    normalized_segments = tuple(segment.lower() for segment in folder_segments)
    if any(segment in BACKUP_FOLDER_TOKENS for segment in normalized_segments):
        return ClassificationResult(
            role="backup_or_temp",
            route="skip",
            reason="backup_or_temp",
            extension=extension,
        )

    if basename.startswith("~$"):
        return ClassificationResult(
            role="backup_or_temp",
            route="skip",
            reason="backup_or_temp",
            extension=extension,
        )

    if extension in SUPPORTED_TEXT_EXTENSIONS:
        return ClassificationResult(
            role="text_document",
            route="parser",
            reason=None,
            extension=extension,
        )
    if extension in SUPPORTED_ENGINEERING_DOCUMENT_EXTENSIONS:
        return ClassificationResult(
            role="engineering_document",
            route="parser",
            reason=None,
            extension=extension,
        )
    if extension in SUPPORTED_ENGINEERING_WORKBOOK_EXTENSIONS:
        return ClassificationResult(
            role="engineering_workbook",
            route="skip",
            reason="xlsx_extractor_pending",
            extension=extension,
        )
    if extension in SUPPORTED_CAD_EXPORT_EXTENSIONS:
        return ClassificationResult(
            role="cad_export",
            route="skip",
            reason="converter_pending",
            extension=extension,
        )
    if extension in SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS:
        return ClassificationResult(
            role="engineering_image",
            route="skip",
            reason="image_extractor_pending",
            extension=extension,
        )
    if extension in BACKUP_OR_TEMP_EXTENSIONS:
        return ClassificationResult(
            role="backup_or_temp",
            route="skip",
            reason="backup_or_temp",
            extension=extension,
        )
    return ClassificationResult(
        role="unsupported",
        route="skip",
        reason="unsupported_extension",
        extension=extension,
    )


__all__ = [
    "BACKUP_FOLDER_TOKENS",
    "BACKUP_OR_TEMP_EXTENSIONS",
    "ClassificationResult",
    "EngineeringRole",
    "IngestionRoute",
    "SkipReason",
    "SUPPORTED_CAD_EXPORT_EXTENSIONS",
    "SUPPORTED_ENGINEERING_DOCUMENT_EXTENSIONS",
    "SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS",
    "SUPPORTED_ENGINEERING_WORKBOOK_EXTENSIONS",
    "SUPPORTED_INGEST_EXTENSIONS",
    "SUPPORTED_TEXT_EXTENSIONS",
    "classify",
]
