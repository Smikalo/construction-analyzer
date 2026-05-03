"""Helpers for normalizing converted drawing evidence into typed document elements."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.services.document_elements import DocumentElement
from app.services.engineering_converters import ConversionResult
from app.services.engineering_files import SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS

CONVERTED_DRAWING_SUBJECT = "converted_drawing"
CONVERTED_DRAWING_SUMMARY_ELEMENT_TYPE = "drawing"
CONVERTED_DRAWING_FACT_ELEMENT_TYPE = "drawing_fact"
CONVERTED_DRAWING_TEXT_SUMMARY_MODE = "converted_drawing_text_summary"
CONVERTED_DRAWING_VISUAL_SUMMARY_MODE = "converted_drawing_visual_summary"
CONVERTED_DRAWING_TEXT_FACT_MODE = "converted_drawing_text_fact"
CONVERTED_DRAWING_NO_TEXT_LAYER_WARNING = "converted_artifact_no_text_layer"
CONVERTED_DRAWING_PARTIAL_TEXT_LAYER_WARNING = "converted_artifact_partial_text_layer"

_SUPPORTED_TEXTLESS_ARTIFACT_EXTENSIONS = frozenset(
    extension.lower() for extension in SUPPORTED_ENGINEERING_IMAGE_EXTENSIONS
)

_FACT_PATTERNS: tuple[tuple[str, re.Pattern[str], str | None], ...] = (
    (
        "label",
        re.compile(r"^(?:label|labels)\s*[:\-]\s*(?P<value>.+)$", re.IGNORECASE),
        None,
    ),
    (
        "annotation",
        re.compile(r"^(?:annotation|annotations)\s*[:\-]\s*(?P<value>.+)$", re.IGNORECASE),
        None,
    ),
    (
        "dimension",
        re.compile(
            r"^(?:dimension|dimensions|dim|dims)\s*[:\-]\s*(?P<value>.+)$",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        "revision_marker",
        re.compile(
            r"^(?:revision marker|revision markers|revision|rev)\s*[:\-]\s*(?P<value>.+)$",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        "layer",
        re.compile(r"^(?:layer|layers)\s*[:\-]\s*(?P<value>.+)$", re.IGNORECASE),
        None,
    ),
    (
        "entity_view",
        re.compile(r"^(?:entity|entities)\s*[:\-]\s*(?P<value>.+)$", re.IGNORECASE),
        "entity",
    ),
    (
        "entity_view",
        re.compile(r"^(?:view|views)\s*[:\-]\s*(?P<value>.+)$", re.IGNORECASE),
        "view",
    ),
    (
        "visible_note",
        re.compile(
            r"^(?:note|notes|visible note|visible notes)\s*[:\-]\s*(?P<value>.+)$",
            re.IGNORECASE,
        ),
        None,
    ),
)

_SENSITIVE_DIAGNOSTIC_KEY_PARTS = (
    "stdout",
    "stderr",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
)


@dataclass(frozen=True, slots=True)
class _DrawingFact:
    page: int
    line_number: int
    fact_type: str
    fact_subtype: str | None
    fact_value: str
    content: str


@dataclass(frozen=True, slots=True)
class _ConversionContext:
    status: str
    source_extension: str
    warnings: tuple[str, ...]
    diagnostics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _FactClassification:
    fact_type: str
    fact_subtype: str | None
    fact_value: str


def extract_converted_drawing(
    path: str,
    *,
    source: str,
    document_id: str | None = None,
    source_path: str | None = None,
    conversion: ConversionResult | None = None,
) -> list[DocumentElement]:
    """Extract a converted drawing summary plus exact text-layer facts."""
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise FileNotFoundError(path)

    artifact_extension = artifact_path.suffix.lower()
    provenance = _conversion_context(
        conversion,
        source=source,
        source_path=source_path,
    )
    common_metadata = _common_metadata(
        source=source,
        source_path=source_path,
        artifact_path=artifact_path,
        artifact_extension=artifact_extension,
        provenance=provenance,
    )

    if artifact_extension == ".pdf":
        return _extract_pdf_converted_drawing(
            str(artifact_path),
            document_id=document_id,
            common_metadata=common_metadata,
            provenance=provenance,
        )

    if artifact_extension in _SUPPORTED_TEXTLESS_ARTIFACT_EXTENSIONS:
        return _build_textless_summary(
            document_id=document_id,
            common_metadata=common_metadata,
            provenance=provenance,
        )

    raise ValueError(
        f"unsupported converted drawing artifact extension: {artifact_extension or '<none>'}"
    )


def _extract_pdf_converted_drawing(
    artifact_path: str,
    *,
    document_id: str | None,
    common_metadata: dict[str, Any],
    provenance: _ConversionContext,
) -> list[DocumentElement]:
    reader = PdfReader(artifact_path)
    facts, page_count, blank_page_count = _extract_pdf_facts(reader)
    drawing_layers, drawing_views, drawing_entities = _collect_context_lists(
        facts,
        provenance=provenance,
    )
    fact_types = _unique_values(fact.fact_type for fact in facts)
    text_page_count = len(_unique_values(fact.page for fact in facts))
    warnings = _artifact_warnings(
        provenance.warnings,
        fact_count=len(facts),
        blank_page_count=blank_page_count,
    )
    summary_confidence = 1.0 if facts else 0.35
    summary_mode = (
        CONVERTED_DRAWING_TEXT_SUMMARY_MODE if facts else CONVERTED_DRAWING_VISUAL_SUMMARY_MODE
    )
    summary_metadata = {
        **common_metadata,
        "drawing_fact_type": "summary",
        "drawing_page_count": page_count,
        "drawing_text_page_count": text_page_count,
        "drawing_fact_count": len(facts),
        "drawing_fact_types": fact_types,
    }
    if blank_page_count:
        summary_metadata["drawing_blank_page_count"] = blank_page_count
    if drawing_layers:
        summary_metadata["drawing_layers"] = drawing_layers
    if drawing_views:
        summary_metadata["drawing_views"] = drawing_views
    if drawing_entities:
        summary_metadata["drawing_entities"] = drawing_entities

    elements = [
        DocumentElement(
            document_id=document_id,
            source=common_metadata["source_cad_file"],
            path=common_metadata["derived_artifact_path"],
            page=None,
            element_type=CONVERTED_DRAWING_SUMMARY_ELEMENT_TYPE,
            extraction_mode=summary_mode,
            content=_render_summary_content(
                common_metadata=common_metadata,
                provenance=provenance,
                page_count=page_count,
                text_page_count=text_page_count,
                fact_count=len(facts),
                fact_types=fact_types,
                drawing_layers=drawing_layers,
                drawing_views=drawing_views,
                drawing_entities=drawing_entities,
                warnings=warnings,
                summary_mode=summary_mode,
                blank_page_count=blank_page_count,
            ),
            confidence=summary_confidence,
            warnings=warnings,
            metadata=summary_metadata,
        )
    ]

    for fact in facts:
        fact_metadata = {
            **common_metadata,
            "drawing_fact_type": fact.fact_type,
            "drawing_fact_value": fact.fact_value,
            "drawing_line_number": fact.line_number,
        }
        if fact.fact_subtype is not None:
            fact_metadata["drawing_fact_subtype"] = fact.fact_subtype
        elements.append(
            DocumentElement(
                document_id=document_id,
                source=common_metadata["source_cad_file"],
                path=common_metadata["derived_artifact_path"],
                page=fact.page,
                element_type=CONVERTED_DRAWING_FACT_ELEMENT_TYPE,
                extraction_mode=CONVERTED_DRAWING_TEXT_FACT_MODE,
                content=fact.content,
                confidence=1.0,
                warnings=warnings,
                metadata=fact_metadata,
            )
        )

    return elements


def _build_textless_summary(
    *,
    document_id: str | None,
    common_metadata: dict[str, Any],
    provenance: _ConversionContext,
) -> list[DocumentElement]:
    warnings = _artifact_warnings(provenance.warnings, fact_count=0, blank_page_count=0)
    summary_metadata = {
        **common_metadata,
        "drawing_fact_type": "summary",
        "drawing_page_count": 1,
        "drawing_text_page_count": 0,
        "drawing_fact_count": 0,
        "drawing_fact_types": [],
    }
    drawing_layers = _list_from_diagnostic_value(common_metadata.get("drawing_layers"))
    drawing_views = _list_from_diagnostic_value(common_metadata.get("drawing_views"))
    drawing_entities = _list_from_diagnostic_value(common_metadata.get("drawing_entities"))
    content = _render_summary_content(
        common_metadata=common_metadata,
        provenance=provenance,
        page_count=1,
        text_page_count=0,
        fact_count=0,
        fact_types=[],
        drawing_layers=drawing_layers,
        drawing_views=drawing_views,
        drawing_entities=drawing_entities,
        warnings=warnings,
        summary_mode=CONVERTED_DRAWING_VISUAL_SUMMARY_MODE,
        blank_page_count=0,
    )
    return [
        DocumentElement(
            document_id=document_id,
            source=common_metadata["source_cad_file"],
            path=common_metadata["derived_artifact_path"],
            page=None,
            element_type=CONVERTED_DRAWING_SUMMARY_ELEMENT_TYPE,
            extraction_mode=CONVERTED_DRAWING_VISUAL_SUMMARY_MODE,
            content=content,
            confidence=0.35,
            warnings=warnings,
            metadata=summary_metadata,
        )
    ]


def _extract_pdf_facts(reader: PdfReader) -> tuple[list[_DrawingFact], int, int]:
    facts: list[_DrawingFact] = []
    pages = list(getattr(reader, "pages", []))
    blank_page_count = 0

    for page_number, page in enumerate(pages, start=1):
        page_text = page.extract_text() or ""
        page_fact_count = 0

        for line_number, raw_line in enumerate(page_text.splitlines(), start=1):
            normalized_line = _normalize_text(raw_line)
            if not normalized_line:
                continue
            if not any(character.isalnum() for character in normalized_line):
                continue

            classification = _classify_drawing_line(normalized_line)
            facts.append(
                _DrawingFact(
                    page=page_number,
                    line_number=line_number,
                    fact_type=classification.fact_type,
                    fact_subtype=classification.fact_subtype,
                    fact_value=classification.fact_value,
                    content=normalized_line,
                )
            )
            page_fact_count += 1

        if page_fact_count == 0:
            blank_page_count += 1

    return facts, len(pages), blank_page_count


def _classify_drawing_line(line: str) -> _FactClassification:
    for fact_type, pattern, fact_subtype in _FACT_PATTERNS:
        match = pattern.match(line)
        if match is None:
            continue
        value = _normalize_text(match.group("value"))
        if not value:
            value = line
        return _FactClassification(
            fact_type=fact_type,
            fact_subtype=fact_subtype,
            fact_value=value,
        )

    return _FactClassification(
        fact_type="visible_note",
        fact_subtype=None,
        fact_value=line,
    )


def _render_summary_content(
    *,
    common_metadata: dict[str, Any],
    provenance: _ConversionContext,
    page_count: int,
    text_page_count: int,
    fact_count: int,
    fact_types: Sequence[str],
    drawing_layers: Sequence[str],
    drawing_views: Sequence[str],
    drawing_entities: Sequence[str],
    warnings: tuple[str, ...],
    summary_mode: str,
    blank_page_count: int,
) -> str:
    text_layer_mode = (
        "exact" if summary_mode == CONVERTED_DRAWING_TEXT_SUMMARY_MODE else "visual-only"
    )
    lines = [
        f"Subject: {common_metadata['subject']}",
        f"Source CAD file: {common_metadata['source_cad_file']}",
    ]
    source_cad_path = common_metadata.get("source_cad_path")
    if source_cad_path:
        lines.append(f"Source CAD path: {source_cad_path}")
    lines.extend(
        [
            f"Derived artifact path: {common_metadata['derived_artifact_path']}",
            f"Conversion status: {common_metadata['conversion_status']}",
            f"Conversion source extension: {common_metadata['conversion_source_extension']}",
            f"Artifact extension: {common_metadata['drawing_artifact_extension']}",
            f"Text layer mode: {text_layer_mode}",
            f"Pages: {page_count}",
            f"Text pages: {text_page_count}",
            f"Exact facts: {fact_count}",
            f"Fact kinds: {', '.join(fact_types) if fact_types else 'none'}",
        ]
    )

    conversion_warnings = common_metadata.get("conversion_warnings", [])
    if conversion_warnings:
        lines.append(f"Conversion warnings: {', '.join(conversion_warnings)}")

    generated_warnings = [warning for warning in warnings if warning not in conversion_warnings]
    if generated_warnings:
        lines.append(f"Warnings: {', '.join(generated_warnings)}")

    if blank_page_count:
        lines.append(f"Blank pages: {blank_page_count}")

    if drawing_layers:
        lines.append(f"Layers: {', '.join(drawing_layers)}")
    if drawing_views:
        lines.append(f"Views: {', '.join(drawing_views)}")
    if drawing_entities:
        lines.append(f"Entities: {', '.join(drawing_entities)}")

    diagnostic_page_count = provenance.diagnostics.get("page_count")
    if diagnostic_page_count and diagnostic_page_count != page_count:
        lines.append(f"Conversion page count: {diagnostic_page_count}")

    return "\n".join(lines)


def _common_metadata(
    *,
    source: str,
    source_path: str | None,
    artifact_path: Path,
    artifact_extension: str,
    provenance: _ConversionContext,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "subject": CONVERTED_DRAWING_SUBJECT,
        "source_cad_file": Path(source).name,
        "derived_artifact_path": str(artifact_path),
        "conversion_status": provenance.status,
        "conversion_source_extension": provenance.source_extension,
        "conversion_warnings": list(provenance.warnings),
        "drawing_artifact_extension": artifact_extension,
    }
    if source_path is not None:
        metadata["source_cad_path"] = str(Path(source_path))
    if provenance.diagnostics:
        metadata["conversion_diagnostics"] = provenance.diagnostics
    if provenance.diagnostics.get("layers"):
        metadata["drawing_layers"] = _list_from_diagnostic_value(provenance.diagnostics["layers"])
    if provenance.diagnostics.get("views"):
        metadata["drawing_views"] = _list_from_diagnostic_value(provenance.diagnostics["views"])
    if provenance.diagnostics.get("entities"):
        metadata["drawing_entities"] = _list_from_diagnostic_value(
            provenance.diagnostics["entities"]
        )
    return metadata


def _conversion_context(
    conversion: ConversionResult | None,
    *,
    source: str,
    source_path: str | None,
) -> _ConversionContext:
    source_reference = source_path or source
    source_extension = _normalize_extension(
        conversion.source_extension
        if conversion is not None
        else _derive_source_extension(source_reference)
    )
    warnings = tuple(_unique_values(conversion.warnings if conversion is not None else ()))
    diagnostics = _sanitize_diagnostics(conversion.diagnostics) if conversion is not None else {}
    status = conversion.status if conversion is not None else "unknown"
    return _ConversionContext(
        status=status,
        source_extension=source_extension,
        warnings=warnings,
        diagnostics=diagnostics,
    )


def _sanitize_diagnostics(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in diagnostics.items():
        if _is_sensitive_key(str(key)):
            continue
        normalized = _sanitize_value(value)
        if normalized is not None:
            sanitized[str(key)] = normalized
    return sanitized


def _sanitize_value(value: Any, *, depth: int = 0) -> Any | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        if depth >= 2:
            return None
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 10:
                break
            if _is_sensitive_key(str(key)):
                continue
            normalized = _sanitize_value(item, depth=depth + 1)
            if normalized is not None:
                sanitized[str(key)] = normalized
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if depth >= 2:
            return None
        sanitized_list: list[Any] = []
        for item in list(value)[:10]:
            normalized = _sanitize_value(item, depth=depth + 1)
            if normalized is not None:
                sanitized_list.append(normalized)
        return sanitized_list
    return None


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_DIAGNOSTIC_KEY_PARTS)


def _artifact_warnings(
    conversion_warnings: Sequence[str],
    *,
    fact_count: int,
    blank_page_count: int,
) -> tuple[str, ...]:
    warnings: list[str] = list(conversion_warnings)
    if fact_count == 0:
        warnings.append(CONVERTED_DRAWING_NO_TEXT_LAYER_WARNING)
    elif blank_page_count > 0:
        warnings.append(CONVERTED_DRAWING_PARTIAL_TEXT_LAYER_WARNING)
    return tuple(_unique_values(warnings))


def _collect_context_lists(
    facts: Sequence[_DrawingFact],
    *,
    provenance: _ConversionContext,
) -> tuple[list[str], list[str], list[str]]:
    layers = _list_from_diagnostic_value(provenance.diagnostics.get("layers"))
    views = _list_from_diagnostic_value(provenance.diagnostics.get("views"))
    entities = _list_from_diagnostic_value(provenance.diagnostics.get("entities"))

    for fact in facts:
        if fact.fact_type == "layer":
            layers = _append_unique(layers, fact.fact_value)
        elif fact.fact_type == "entity_view" and fact.fact_subtype == "view":
            views = _append_unique(views, fact.fact_value)
        elif fact.fact_type == "entity_view" and fact.fact_subtype == "entity":
            entities = _append_unique(entities, fact.fact_value)

    return layers, views, entities


def _append_unique(values: Sequence[str], value: str) -> list[str]:
    normalized = _normalize_text(value)
    items = list(values)
    if normalized and normalized not in items:
        items.append(normalized)
    return items


def _list_from_diagnostic_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return [normalized] if normalized else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _unique_values(_normalize_text(item) for item in value)
    normalized = _normalize_text(value)
    return [normalized] if normalized else []


def _unique_values(values: Sequence[Any] | Sequence[str] | Any) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _normalize_extension(value: str | None) -> str:
    if value is None:
        return ""
    normalized = _normalize_text(value).lower()
    if not normalized:
        return ""
    return normalized if normalized.startswith(".") else f".{normalized.lstrip('.')}"


def _derive_source_extension(source: str) -> str:
    return Path(source).suffix.lower()


def _normalize_text(value: object | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


__all__ = [
    "CONVERTED_DRAWING_FACT_ELEMENT_TYPE",
    "CONVERTED_DRAWING_NO_TEXT_LAYER_WARNING",
    "CONVERTED_DRAWING_PARTIAL_TEXT_LAYER_WARNING",
    "CONVERTED_DRAWING_SUBJECT",
    "CONVERTED_DRAWING_SUMMARY_ELEMENT_TYPE",
    "CONVERTED_DRAWING_TEXT_FACT_MODE",
    "CONVERTED_DRAWING_TEXT_SUMMARY_MODE",
    "CONVERTED_DRAWING_VISUAL_SUMMARY_MODE",
    "extract_converted_drawing",
]
