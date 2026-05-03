"""Optional visual-only document analysis enrichment for parser-produced elements."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings, get_settings
from app.services.document_elements import DocumentElement
from app.services.visual_elements import VISUAL_ELEMENT_TYPES, visual_element_from_summary

DOCUMENT_ANALYSIS_MODE_VISUAL_ONLY = "visual_only"
DOCUMENT_ANALYSIS_PROVIDER_OPENAI = "openai"

OPENAI_ENRICHMENT_FAILED_WARNING = "openai_enrichment_failed"
OPENAI_ENRICHMENT_REFUSED_WARNING = "openai_enrichment_refused"
OPENAI_ENRICHMENT_INVALID_WARNING = "openai_enrichment_invalid"
OPENAI_ENRICHMENT_BLANK_WARNING = "openai_enrichment_blank"

_VISUAL_ELEMENT_TYPE_SET = frozenset(VISUAL_ELEMENT_TYPES)


class VisualEnrichmentOutput(BaseModel):
    """Strict structured output for visual evidence enrichment."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str
    labels: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    uncertainty: str | None = None
    approximate: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DocumentAnalysisError(RuntimeError):
    """Base exception for document-analysis failures."""


class DocumentAnalysisRefusalError(DocumentAnalysisError):
    """The model refused to produce an enrichment response."""


class DocumentAnalysisInvalidResponseError(DocumentAnalysisError):
    """The model response could not be parsed into the strict output schema."""


class DocumentAnalysisClient(Protocol):
    """Protocol for a single-element visual enrichment client."""

    def enrich(self, element: DocumentElement) -> VisualEnrichmentOutput:
        """Return a strict enrichment payload for one visual element."""


class DocumentAnalyzer(Protocol):
    """Protocol for a sequence-level document analysis adapter."""

    def enrich(self, elements: Sequence[DocumentElement]) -> list[DocumentElement]:
        """Enrich a sequence of parsed document elements."""


class NoopDocumentAnalyzer:
    """Analyzer used when visual-only enrichment is disabled."""

    def enrich(self, elements: Sequence[DocumentElement]) -> list[DocumentElement]:
        return list(elements)


class OpenAIDocumentAnalysisClient:
    """Lazy OpenAI-backed visual enrichment client.

    The underlying OpenAI SDK client is created only when the first visual
    element needs enrichment so tests can inject fake clients without touching
    the network or requiring a real API key.
    """

    def __init__(self, settings: Settings | None = None, *, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._settings.document_analysis_api_key)
        return self._client

    def enrich(self, element: DocumentElement) -> VisualEnrichmentOutput:
        try:
            completion = self.client.chat.completions.parse(
                model=self._settings.document_analysis_model,
                messages=_build_visual_enrichment_messages(element),
                response_format=VisualEnrichmentOutput,
            )
        except ValidationError as exc:
            raise DocumentAnalysisInvalidResponseError(
                "OpenAI visual enrichment response failed strict validation"
            ) from exc

        if not getattr(completion, "choices", None):
            raise DocumentAnalysisInvalidResponseError(
                "OpenAI visual enrichment response returned no choices"
            )

        message = completion.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise DocumentAnalysisRefusalError(str(refusal))

        parsed = getattr(message, "parsed", None)
        if parsed is None:
            raise DocumentAnalysisInvalidResponseError(
                "OpenAI visual enrichment response returned no parsed payload"
            )

        try:
            if isinstance(parsed, VisualEnrichmentOutput):
                return parsed
            return VisualEnrichmentOutput.model_validate(parsed)
        except ValidationError as exc:
            raise DocumentAnalysisInvalidResponseError(
                "OpenAI visual enrichment payload failed strict schema validation"
            ) from exc


class OpenAIDocumentAnalyzer:
    """Visual-only adapter that enriches visual elements and preserves others."""

    def __init__(
        self,
        client: DocumentAnalysisClient,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    def enrich(self, elements: Sequence[DocumentElement]) -> list[DocumentElement]:
        enriched_elements: list[DocumentElement] = []
        for element in elements:
            if not _is_visual_element(element):
                enriched_elements.append(element)
                continue
            enriched_elements.append(self._enrich_visual_element(element))
        return enriched_elements

    def _enrich_visual_element(self, element: DocumentElement) -> DocumentElement:
        try:
            output = self._client.enrich(element)
        except DocumentAnalysisRefusalError:
            return _fallback_visual_element(
                element,
                settings=self._settings,
                status="refused",
                warning=OPENAI_ENRICHMENT_REFUSED_WARNING,
            )
        except DocumentAnalysisInvalidResponseError:
            return _fallback_visual_element(
                element,
                settings=self._settings,
                status="invalid",
                warning=OPENAI_ENRICHMENT_INVALID_WARNING,
            )
        except Exception:
            return _fallback_visual_element(
                element,
                settings=self._settings,
                status="failed",
                warning=OPENAI_ENRICHMENT_FAILED_WARNING,
            )

        enriched = visual_element_from_summary(
            output.summary,
            element_type=element.element_type,
            source=element.source,
            document_id=element.document_id,
            path=element.path,
            page=element.page,
            confidence=output.confidence if output.confidence is not None else element.confidence,
            labels=output.labels,
            relationships=output.relationships,
            uncertainty=output.uncertainty,
            approximate=output.approximate,
            warnings=element.warnings,
            metadata=_analysis_metadata(
                settings=self._settings,
                element=element,
                status="enriched",
            ),
        )
        if enriched is None:
            return _fallback_visual_element(
                element,
                settings=self._settings,
                status="blank",
                warning=OPENAI_ENRICHMENT_BLANK_WARNING,
            )

        return replace(
            enriched,
            metadata=_merge_metadata(element.metadata, enriched.metadata),
        )


def build_openai_document_analysis_client(
    settings: Settings | None = None,
    *,
    client: Any | None = None,
) -> OpenAIDocumentAnalysisClient:
    """Return a lazily-created OpenAI-backed enrichment client."""
    return OpenAIDocumentAnalysisClient(settings=settings, client=client)


def build_document_analyzer(
    settings: Settings | None = None,
    *,
    client: DocumentAnalysisClient | None = None,
) -> DocumentAnalyzer:
    """Return the configured analyzer or a no-op adapter when disabled."""
    active_settings = settings or get_settings()
    if not active_settings.document_analysis_enabled:
        return NoopDocumentAnalyzer()

    analysis_client = client or build_openai_document_analysis_client(active_settings)
    return OpenAIDocumentAnalyzer(analysis_client, settings=active_settings)


def enrich_document_elements(
    elements: Sequence[DocumentElement],
    *,
    analyzer: DocumentAnalyzer | None = None,
    settings: Settings | None = None,
    client: DocumentAnalysisClient | None = None,
) -> list[DocumentElement]:
    """Convenience wrapper for enriching a batch of parsed document elements."""
    active_analyzer = analyzer or build_document_analyzer(settings=settings, client=client)
    return active_analyzer.enrich(elements)


def _build_visual_enrichment_messages(element: DocumentElement) -> list[dict[str, str]]:
    context = {
        "source": element.source,
        "document_id": element.document_id,
        "path": element.path,
        "page": element.page,
        "element_type": element.element_type,
        "extraction_mode": element.extraction_mode,
        "confidence": element.confidence,
        "warnings": list(element.warnings),
        "content": element.content,
        "metadata": element.metadata,
    }
    system_content = (
        "You enrich parser-produced visual document evidence for a construction-analysis "
        "pipeline. Visual-only mode is enabled, so only refine chart, diagram, drawing, "
        "and image evidence."
    )
    if _is_drawing_enrichment_context(element):
        system_content += (
            " For drawings and converted CAD/drawing exports, inspect visible labels, "
            "annotations, dimensions, revision markers, layers, entities, views, and notes. "
            "Keep exact text-layer facts separate from any visual interpretation, and do not "
            "present visual readings as certified measurements or invent missing facts."
        )
    system_content += (
        " Return only fields that fit the strict schema and do not add extra keys. If the "
        "evidence is sparse, preserve the visual summary and do not invent missing facts."
    )
    return [
        {
            "role": "system",
            "content": system_content,
        },
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False, sort_keys=True, default=str),
        },
    ]


def _is_drawing_enrichment_context(element: DocumentElement) -> bool:
    if element.metadata.get("subject") == "converted_drawing":
        return True
    return element.element_type == "drawing" or element.extraction_mode.startswith(
        "converted_drawing_"
    )


def _fallback_visual_element(
    element: DocumentElement,
    *,
    settings: Settings,
    status: str,
    warning: str,
) -> DocumentElement:
    return replace(
        element,
        warnings=_merge_warnings(element.warnings, (warning,)),
        metadata=_merge_metadata(
            element.metadata,
            _analysis_metadata(settings=settings, element=element, status=status),
        ),
    )


def _analysis_metadata(
    *,
    settings: Settings,
    element: DocumentElement,
    status: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "analysis_provider": DOCUMENT_ANALYSIS_PROVIDER_OPENAI,
        "analysis_model": settings.document_analysis_model,
        "analysis_mode": settings.document_analysis_mode,
        "analysis_status": status,
        "analysis_source_element_type": element.element_type,
        "analysis_source_extraction_mode": element.extraction_mode,
    }
    if element.confidence is not None:
        metadata["analysis_source_confidence"] = element.confidence
    return metadata


def _merge_metadata(
    original: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(original)
    metadata.update(generated)
    return metadata


def _merge_warnings(
    *warning_groups: Sequence[str],
) -> tuple[str, ...]:
    merged: list[str] = []
    for warning_group in warning_groups:
        for warning in warning_group:
            if warning and warning not in merged:
                merged.append(warning)
    return tuple(merged)


def _is_visual_element(element: DocumentElement) -> bool:
    return element.element_type in _VISUAL_ELEMENT_TYPE_SET


__all__ = [
    "DOCUMENT_ANALYSIS_MODE_VISUAL_ONLY",
    "DOCUMENT_ANALYSIS_PROVIDER_OPENAI",
    "DocumentAnalysisClient",
    "DocumentAnalysisError",
    "DocumentAnalysisInvalidResponseError",
    "DocumentAnalysisRefusalError",
    "DocumentAnalyzer",
    "NoopDocumentAnalyzer",
    "OPENAI_ENRICHMENT_BLANK_WARNING",
    "OPENAI_ENRICHMENT_FAILED_WARNING",
    "OPENAI_ENRICHMENT_INVALID_WARNING",
    "OPENAI_ENRICHMENT_REFUSED_WARNING",
    "OpenAIDocumentAnalysisClient",
    "OpenAIDocumentAnalyzer",
    "VisualEnrichmentOutput",
    "build_document_analyzer",
    "build_openai_document_analysis_client",
    "enrich_document_elements",
]
