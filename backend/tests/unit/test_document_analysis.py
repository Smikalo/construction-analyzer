"""Tests for optional visual document-analysis enrichment."""

from __future__ import annotations

from types import SimpleNamespace

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
    OpenAIDocumentAnalysisClient,
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


def _converted_drawing_element(
    *,
    warnings: tuple[str, ...] = ("converter_note",),
    metadata: dict[str, object] | None = None,
    content: str = (
        "Subject: converted_drawing\n"
        "Source CAD file: north.dwg\n"
        "Source CAD path: backend/data/documents/input/north.dwg\n"
        "Derived artifact path: backend/data/documents/converted/north.pdf\n"
        "Conversion status: success\n"
        "Conversion source extension: .dwg\n"
        "Artifact extension: .pdf\n"
        "Text layer mode: exact\n"
        "Pages: 2\n"
        "Text pages: 2\n"
        "Exact facts: 4\n"
        "Fact kinds: label, dimension, layer, revision_marker\n"
        "Conversion warnings: converter_note\n"
        "Layers: A-WALL\n"
        "Views: Level 1\n"
        "Entities: Door 7"
    ),
    confidence: float | None = 1.0,
    extraction_mode: str = "converted_drawing_text_summary",
) -> DocumentElement:
    return DocumentElement(
        document_id="doc-123",
        source="north.dwg",
        path="backend/data/documents/converted/north.pdf",
        page=None,
        element_type="drawing",
        extraction_mode=extraction_mode,
        content=content,
        confidence=confidence,
        warnings=warnings,
        metadata={
            "subject": "converted_drawing",
            "source_cad_file": "north.dwg",
            "source_cad_path": "backend/data/documents/input/north.dwg",
            "derived_artifact_path": "backend/data/documents/converted/north.pdf",
            "conversion_status": "success",
            "conversion_source_extension": ".dwg",
            "conversion_warnings": ["converter_note"],
            "drawing_artifact_extension": ".pdf",
            "drawing_fact_type": "summary",
            "drawing_page_count": 2,
            "drawing_text_page_count": 2,
            "drawing_fact_count": 4,
            "drawing_fact_types": ["label", "dimension", "layer", "revision_marker"],
            "drawing_layers": ["A-WALL"],
            "drawing_views": ["Level 1"],
            "drawing_entities": ["Door 7"],
            **(metadata or {}),
        },
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


class TestConvertedDrawingDocumentAnalysis:
    def test_prompt_calls_out_drawing_facts_and_uncertainty_contract(self) -> None:
        element = _converted_drawing_element()
        recorded_calls: list[dict[str, object]] = []

        class RecordingCompletions:
            def parse(self, **kwargs: object) -> object:
                recorded_calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                parsed=VisualEnrichmentOutput(summary="North stair sketch refined"),
                                refusal=None,
                            )
                        )
                    ]
                )

        class RecordingOpenAIClient:
            def __init__(self) -> None:
                self.chat = SimpleNamespace(completions=RecordingCompletions())

        analysis_client = OpenAIDocumentAnalysisClient(
            Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=RecordingOpenAIClient(),
        )

        result = analysis_client.enrich(element)

        assert result.summary == "North stair sketch refined"
        assert recorded_calls
        system_prompt = recorded_calls[0]["messages"][0]["content"]
        assert "converted CAD/drawing exports" in system_prompt
        assert (
            "visible labels, annotations, dimensions, revision markers, "
            "layers, entities, views, and notes" in system_prompt
        )
        assert "do not present visual readings as certified measurements" in system_prompt
        assert "do not invent missing facts" in system_prompt

    def test_approximate_enrichment_preserves_converted_drawing_provenance_and_warnings(
        self,
    ) -> None:
        element = _converted_drawing_element(
            warnings=("converter_note",),
            metadata={"drawing_quality": "rough"},
            confidence=0.83,
        )
        client = RecordingDocumentAnalysisClient(
            response=VisualEnrichmentOutput(
                summary="North stair sketch with approximate dimensions",
                labels=["North stair", "Approx. 12 ft span"],
                relationships=["North stair -> Access path"],
                uncertainty="dimensions inferred from screenshot",
                approximate=True,
                confidence=0.76,
            )
        )

        result = enrich_document_elements(
            [element],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert client.calls == [element]
        assert result.document_id == element.document_id
        assert result.source == element.source
        assert result.path == element.path
        assert result.page == element.page
        assert result.element_type == element.element_type
        assert result.extraction_mode == "visual_summary"
        assert result.content == (
            "North stair sketch with approximate dimensions\n"
            "Labels: North stair; Approx. 12 ft span\n"
            "Relationships: North stair -> Access path\n"
            "Uncertainty: dimensions inferred from screenshot"
        )
        assert result.confidence == 0.76
        assert result.warnings == ("converter_note", APPROXIMATE_VALUE_WARNING)
        assert result.metadata == {
            **element.metadata,
            "drawing_quality": "rough",
            "visual_summary_chars": len("North stair sketch with approximate dimensions"),
            "labels": ["North stair", "Approx. 12 ft span"],
            "relationships": ["North stair -> Access path"],
            "uncertainty": "dimensions inferred from screenshot",
            "approximate": True,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "enriched",
            "analysis_source_element_type": "drawing",
            "analysis_source_extraction_mode": "converted_drawing_text_summary",
            "analysis_source_confidence": 0.83,
        }

    def test_blank_enrichment_preserves_converted_drawing_provenance_and_warning(
        self,
    ) -> None:
        element = _converted_drawing_element()
        client = RecordingDocumentAnalysisClient(
            response=VisualEnrichmentOutput(
                summary="   ",
                labels=[],
                relationships=[],
                uncertainty="  ",
                approximate=False,
                confidence=0.24,
            )
        )

        result = enrich_document_elements(
            [element],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert client.calls == [element]
        assert result.content == element.content
        assert result.confidence == element.confidence
        assert result.warnings == ("converter_note", OPENAI_ENRICHMENT_BLANK_WARNING)
        assert result.metadata == {
            **element.metadata,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": "blank",
            "analysis_source_element_type": "drawing",
            "analysis_source_extraction_mode": "converted_drawing_text_summary",
            "analysis_source_confidence": 1.0,
        }

    @pytest.mark.parametrize(
        ("error", "warning", "status"),
        [
            pytest.param(
                DocumentAnalysisRefusalError("policy refusal"),
                OPENAI_ENRICHMENT_REFUSED_WARNING,
                "refused",
                id="refusal",
            ),
            pytest.param(
                DocumentAnalysisInvalidResponseError("malformed response"),
                OPENAI_ENRICHMENT_INVALID_WARNING,
                "invalid",
                id="invalid",
            ),
            pytest.param(
                RuntimeError("boom"),
                OPENAI_ENRICHMENT_FAILED_WARNING,
                "failed",
                id="failed",
            ),
        ],
    )
    def test_failure_paths_preserve_converted_drawing_provenance(
        self,
        error: Exception,
        warning: str,
        status: str,
    ) -> None:
        element = _converted_drawing_element()
        client = RecordingDocumentAnalysisClient(exception=error)

        result = enrich_document_elements(
            [element],
            settings=Settings(
                llm_provider="ollama",
                document_analysis_enabled=True,
                document_analysis_api_key="",
                document_analysis_model="gpt-4o-mini",
            ),
            client=client,
        )[0]

        assert client.calls == [element]
        assert result.document_id == element.document_id
        assert result.source == element.source
        assert result.path == element.path
        assert result.page == element.page
        assert result.element_type == element.element_type
        assert result.extraction_mode == element.extraction_mode
        assert result.content == element.content
        assert result.confidence == element.confidence
        assert result.warnings == ("converter_note", warning)
        assert result.metadata == {
            **element.metadata,
            "analysis_provider": "openai",
            "analysis_model": "gpt-4o-mini",
            "analysis_mode": "visual_only",
            "analysis_status": status,
            "analysis_source_element_type": "drawing",
            "analysis_source_extraction_mode": "converted_drawing_text_summary",
            "analysis_source_confidence": 1.0,
        }


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
