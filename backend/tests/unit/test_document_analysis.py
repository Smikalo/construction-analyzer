"""Tests for optional visual document-analysis enrichment."""

from __future__ import annotations

import pytest
from langchain_ollama import ChatOllama
from pydantic import ValidationError

from app.agent.llm import get_llm
from app.config import Settings
from app.services.document_analysis import (
    DOCUMENT_ANALYSIS_MODE_VISUAL_ONLY,
    OPENAI_ENRICHMENT_BLANK_WARNING,
    OPENAI_ENRICHMENT_FAILED_WARNING,
    OPENAI_ENRICHMENT_INVALID_WARNING,
    OPENAI_ENRICHMENT_REFUSED_WARNING,
    DocumentAnalysisInvalidResponseError,
    DocumentAnalysisRefusalError,
    NoopDocumentAnalyzer,
    VisualEnrichmentOutput,
    build_document_analyzer,
    enrich_document_elements,
)
from app.services.document_elements import DocumentElement
from app.services.visual_elements import APPROXIMATE_VALUE_WARNING


class RecordingDocumentAnalysisClient:
    def __init__(
        self,
        *,
        response: VisualEnrichmentOutput | None = None,
        exception: Exception | None = None,
    ) -> None:
        self.response = response
        self.exception = exception
        self.calls: list[DocumentElement] = []

    def enrich(self, element: DocumentElement) -> VisualEnrichmentOutput:
        self.calls.append(element)
        if self.exception is not None:
            raise self.exception
        assert self.response is not None
        return self.response


def _visual_element(
    *,
    warnings: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
    content: str = "Original visual summary",
    confidence: float | None = 0.42,
) -> DocumentElement:
    return DocumentElement(
        document_id="doc-123",
        source="sheet.pdf",
        path="backend/data/documents/sheet.pdf",
        page=4,
        element_type="chart",
        extraction_mode="visual_summary",
        content=content,
        confidence=confidence,
        warnings=warnings,
        metadata=metadata or {},
    )


def _text_element() -> DocumentElement:
    return DocumentElement(
        document_id="doc-123",
        source="sheet.pdf",
        path="backend/data/documents/sheet.pdf",
        page=3,
        element_type="paragraph",
        extraction_mode="pdf_text",
        content="Cover sheet body",
        confidence=None,
        warnings=(),
        metadata={"section": "cover"},
    )


class TestDocumentAnalysisSettings:
    def test_document_analysis_settings_are_optional_and_independent_from_chat_llm(
        self,
    ) -> None:
        settings = Settings(
            llm_provider="ollama",
            ollama_model="qwen3:1.7b",
        )

        assert settings.document_analysis_enabled is False
        assert settings.document_analysis_mode == DOCUMENT_ANALYSIS_MODE_VISUAL_ONLY
        assert settings.document_analysis_api_key == ""

        llm = get_llm(settings)
        assert isinstance(llm, ChatOllama)
        assert llm.model == "qwen3:1.7b"

    def test_disabled_document_analysis_factory_is_noop_by_default(self) -> None:
        analyzer = build_document_analyzer(Settings())

        assert isinstance(analyzer, NoopDocumentAnalyzer)

        paragraph = _text_element()
        chart = _visual_element()

        result = analyzer.enrich([paragraph, chart])

        assert result[0] is paragraph
        assert result[1] is chart


class TestVisualEnrichmentOutput:
    def test_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            VisualEnrichmentOutput.model_validate(
                {
                    "summary": "North stair sketch",
                    "extra": "boom",
                }
            )

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"

    @pytest.mark.parametrize("confidence", [-0.01, 1.01])
    def test_rejects_out_of_range_confidence(self, confidence: float) -> None:
        with pytest.raises(ValidationError):
            VisualEnrichmentOutput.model_validate(
                {
                    "summary": "North stair sketch",
                    "confidence": confidence,
                }
            )


class TestDocumentAnalysisAdapter:
    def test_visual_only_enrichment_preserves_provenance_and_merges_metadata(self) -> None:
        response = VisualEnrichmentOutput(
            summary="North stair sketch with access path",
            labels=["North stair", "Access path"],
            relationships=["North stair -> Access path"],
            uncertainty="estimated from site photo",
            approximate=True,
            confidence=0.86,
        )
        client = RecordingDocumentAnalysisClient(response=response)
        paragraph = _text_element()
        chart = _visual_element(
            warnings=("existing_warning", APPROXIMATE_VALUE_WARNING),
            metadata={"figure_index": 7},
            content="Original visual summary",
            confidence=0.42,
        )

        result = enrich_document_elements(
            [paragraph, chart],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )

        assert client.calls == [chart]
        assert result[0] is paragraph

        enriched = result[1]
        assert enriched.document_id == "doc-123"
        assert enriched.source == "sheet.pdf"
        assert enriched.path == "backend/data/documents/sheet.pdf"
        assert enriched.page == 4
        assert enriched.element_type == "chart"
        assert enriched.extraction_mode == "visual_summary"
        assert enriched.content == (
            "North stair sketch with access path\n"
            "Labels: North stair; Access path\n"
            "Relationships: North stair -> Access path\n"
            "Uncertainty: estimated from site photo"
        )
        assert enriched.confidence == 0.86
        assert enriched.warnings == ("existing_warning", APPROXIMATE_VALUE_WARNING)
        assert enriched.metadata == {
            "figure_index": 7,
            "visual_summary_chars": len("North stair sketch with access path"),
            "labels": ["North stair", "Access path"],
            "relationships": ["North stair -> Access path"],
            "uncertainty": "estimated from site photo",
            "approximate": True,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "enriched",
            "analysis_source_element_type": "chart",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.42,
        }

    def test_refusal_returns_original_visual_element_with_warning(self) -> None:
        client = RecordingDocumentAnalysisClient(
            exception=DocumentAnalysisRefusalError("policy refusal"),
        )
        visual = _visual_element(
            warnings=("existing_warning", OPENAI_ENRICHMENT_REFUSED_WARNING),
            metadata={"figure_index": 2},
            content="Original visual summary",
            confidence=0.55,
        )

        result = enrich_document_elements(
            [visual],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert result.content == visual.content
        assert result.document_id == visual.document_id
        assert result.source == visual.source
        assert result.page == visual.page
        assert result.warnings == ("existing_warning", OPENAI_ENRICHMENT_REFUSED_WARNING)
        assert result.metadata == {
            "figure_index": 2,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "refused",
            "analysis_source_element_type": "chart",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.55,
        }

    def test_invalid_response_returns_original_visual_element_with_warning(self) -> None:
        client = RecordingDocumentAnalysisClient(
            exception=DocumentAnalysisInvalidResponseError("malformed response"),
        )
        visual = _visual_element(
            warnings=("existing_warning", OPENAI_ENRICHMENT_INVALID_WARNING),
            metadata={"figure_index": 3},
            content="Original visual summary",
            confidence=0.61,
        )

        result = enrich_document_elements(
            [visual],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert result.content == visual.content
        assert result.document_id == visual.document_id
        assert result.source == visual.source
        assert result.page == visual.page
        assert result.warnings == ("existing_warning", OPENAI_ENRICHMENT_INVALID_WARNING)
        assert result.metadata == {
            "figure_index": 3,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "invalid",
            "analysis_source_element_type": "chart",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.61,
        }

    def test_client_exception_returns_original_visual_element_with_warning(self) -> None:
        client = RecordingDocumentAnalysisClient(exception=RuntimeError("boom"))
        visual = _visual_element(
            warnings=("existing_warning", OPENAI_ENRICHMENT_FAILED_WARNING),
            metadata={"figure_index": 4},
            content="Original visual summary",
            confidence=0.61,
        )

        result = enrich_document_elements(
            [visual],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert result.content == visual.content
        assert result.document_id == visual.document_id
        assert result.source == visual.source
        assert result.page == visual.page
        assert result.warnings == ("existing_warning", OPENAI_ENRICHMENT_FAILED_WARNING)
        assert result.metadata == {
            "figure_index": 4,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "failed",
            "analysis_source_element_type": "chart",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.61,
        }

    def test_blank_enrichment_returns_original_visual_element(self) -> None:
        client = RecordingDocumentAnalysisClient(
            response=VisualEnrichmentOutput(
                summary="   ",
                labels=[],
                relationships=[],
                uncertainty="  ",
                approximate=False,
                confidence=0.11,
            )
        )
        visual = _visual_element(
            metadata={"figure_index": 4},
            content="Original visual summary",
            confidence=0.33,
        )

        result = enrich_document_elements(
            [visual],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert result.content == visual.content
        assert result.document_id == visual.document_id
        assert result.source == visual.source
        assert result.page == visual.page
        assert result.warnings == (OPENAI_ENRICHMENT_BLANK_WARNING,)
        assert result.metadata == {
            "figure_index": 4,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "blank",
            "analysis_source_element_type": "chart",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.33,
        }

    def test_build_document_analyzer_uses_injected_client_when_enabled(self) -> None:
        response = VisualEnrichmentOutput(
            summary="North stair sketch",
            confidence=0.73,
        )
        client = RecordingDocumentAnalysisClient(response=response)
        analyzer = build_document_analyzer(
            Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )

        visual = _visual_element()

        result = analyzer.enrich([visual])

        assert client.calls == [visual]
        assert result[0].content == "North stair sketch"
        assert result[0].metadata["analysis_status"] == "enriched"
        assert result[0].metadata["analysis_provider"] == "openai"
