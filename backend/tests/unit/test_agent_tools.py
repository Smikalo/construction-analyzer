"""Tests for KB agent tools and recall provenance formatting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from app.agent.tools import build_kb_tools
from app.kb.fake import FakeKB
from app.services.document_elements import DocumentElement
from app.services.element_memory import chunk_and_format
from app.services.ocr_elements import ocr_element_from_text
from app.services.table_elements import table_element_from_rows
from app.services.visual_elements import (
    APPROXIMATE_VALUE_WARNING,
    visual_element_from_summary,
)

DOCUMENT_ID = "doc-mixed-001"
SOURCE = "mixed.pdf"
PATH = "/synthetic/mixed.pdf"


@dataclass(frozen=True)
class RecallCase:
    name: str
    build: Callable[[], DocumentElement]
    query: str
    expected_content: str
    expected_metadata: dict[str, object]


@dataclass(frozen=True)
class SeededRecallCase:
    name: str
    query: str
    memory_id: str
    expected_content: str
    expected_metadata: dict[str, object]


def _build_paragraph_element() -> DocumentElement:
    element = DocumentElement(
        document_id=DOCUMENT_ID,
        source=SOURCE,
        path=PATH,
        page=None,
        element_type="paragraph",
        extraction_mode="pdf_text",
        content="Page-less paragraph keeps the mixed upload searchable.",
        metadata={"section": "cover"},
    )
    assert element is not None
    return element


def _build_table_element() -> DocumentElement:
    element = table_element_from_rows(
        [["Room", "Width", "Notes"], ["North stair", "42", "egress path"]],
        document_id=DOCUMENT_ID,
        source=SOURCE,
        path=PATH,
        page=2,
        confidence=0.82,
        warnings=("merged_cells",),
        metadata={"table_index": 0},
    )
    assert element is not None
    return element


def _build_ocr_element() -> DocumentElement:
    element = ocr_element_from_text(
        "  Recovered\nsheet\tnote from scan  ",
        document_id=DOCUMENT_ID,
        source=SOURCE,
        path=PATH,
        page=3,
        confidence=0.41,
        warnings=("low_text_page", "ocr_low_confidence"),
        low_text_threshold=20,
        metadata={"ocr_engine": "fake"},
    )
    assert element is not None
    return element


def _build_visual_summary_element() -> DocumentElement:
    element = visual_element_from_summary(
        "North stair sketch",
        element_type="drawing",
        source=SOURCE,
        document_id=DOCUMENT_ID,
        path=PATH,
        page=4,
        confidence=0.94,
        labels=("North stair", "Access path"),
        relationships=("North stair -> Access path",),
        approximate=True,
        warnings=("diagram_note",),
        metadata={"figure_index": 7},
    )
    assert element is not None
    return element


def _build_enriched_visual_element() -> DocumentElement:
    element = visual_element_from_summary(
        "Site photo annotated",
        element_type="image",
        source=SOURCE,
        document_id=DOCUMENT_ID,
        path=PATH,
        page=5,
        confidence=0.79,
        labels=("Facade",),
        relationships=("Facade -> Entry",),
        uncertainty="approximate from field notes",
        approximate=True,
        warnings=("field_review",),
        metadata={
            "figure_index": 8,
            "analysis_provider": "openai",
            "analysis_model": "fake-visual-model",
            "analysis_mode": "visual_only",
            "analysis_status": "enriched",
            "analysis_source_element_type": "image",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.61,
        },
    )
    assert element is not None
    return element


MIXED_UPLOAD_CASES: list[RecallCase] = [
    RecallCase(
        name="paragraph",
        build=_build_paragraph_element,
        query="page-less paragraph",
        expected_content=(
            "[source=mixed.pdf; element=paragraph; extraction=pdf_text]\n"
            "Page-less paragraph keeps the mixed upload searchable."
        ),
        expected_metadata={
            "document_id": DOCUMENT_ID,
            "source": SOURCE,
            "path": PATH,
            "page": None,
            "element_type": "paragraph",
            "extraction_mode": "pdf_text",
            "warnings": [],
            "section": "cover",
        },
    ),
    RecallCase(
        name="table",
        build=_build_table_element,
        query="egress path",
        expected_content=(
            "[source=mixed.pdf; page=2; element=table; extraction=pdf_table; "
            "confidence=0.82; warnings=merged_cells]\n"
            "| Room | Width | Notes |\n"
            "| --- | --- | --- |\n"
            "| North stair | 42 | egress path |"
        ),
        expected_metadata={
            "document_id": DOCUMENT_ID,
            "source": SOURCE,
            "path": PATH,
            "page": 2,
            "element_type": "table",
            "extraction_mode": "pdf_table",
            "confidence": 0.82,
            "warnings": ["merged_cells"],
            "table_rows": 2,
            "table_columns": 3,
            "table_index": 0,
        },
    ),
    RecallCase(
        name="ocr",
        build=_build_ocr_element,
        query="recovered sheet note",
        expected_content=(
            "[source=mixed.pdf; page=3; element=ocr_text; extraction=ocr; "
            "confidence=0.41; warnings=low_text_page,ocr_low_confidence]\n"
            "Recovered sheet note from scan"
        ),
        expected_metadata={
            "document_id": DOCUMENT_ID,
            "source": SOURCE,
            "path": PATH,
            "page": 3,
            "element_type": "ocr_text",
            "extraction_mode": "ocr",
            "confidence": 0.41,
            "warnings": ["low_text_page", "ocr_low_confidence"],
            "ocr_text_chars": len("Recovered sheet note from scan"),
            "low_text_threshold": 20,
            "ocr_engine": "fake",
        },
    ),
    RecallCase(
        name="visual-summary",
        build=_build_visual_summary_element,
        query="Access path",
        expected_content=(
            f"[source=mixed.pdf; page=4; element=drawing; extraction=visual_summary; "
            f"confidence=0.94; warnings=diagram_note,{APPROXIMATE_VALUE_WARNING}]\n"
            "North stair sketch\n"
            "Labels: North stair; Access path\n"
            "Relationships: North stair -> Access path"
        ),
        expected_metadata={
            "document_id": DOCUMENT_ID,
            "source": SOURCE,
            "path": PATH,
            "page": 4,
            "element_type": "drawing",
            "extraction_mode": "visual_summary",
            "confidence": 0.94,
            "warnings": ["diagram_note", APPROXIMATE_VALUE_WARNING],
            "visual_summary_chars": len("North stair sketch"),
            "labels": ["North stair", "Access path"],
            "relationships": ["North stair -> Access path"],
            "approximate": True,
            "figure_index": 7,
        },
    ),
    RecallCase(
        name="enriched-visual",
        build=_build_enriched_visual_element,
        query="field notes",
        expected_content=(
            f"[source=mixed.pdf; page=5; element=image; extraction=visual_summary; "
            f"confidence=0.79; warnings=field_review,{APPROXIMATE_VALUE_WARNING}]\n"
            "Site photo annotated\n"
            "Labels: Facade\n"
            "Relationships: Facade -> Entry\n"
            "Uncertainty: approximate from field notes"
        ),
        expected_metadata={
            "document_id": DOCUMENT_ID,
            "source": SOURCE,
            "path": PATH,
            "page": 5,
            "element_type": "image",
            "extraction_mode": "visual_summary",
            "confidence": 0.79,
            "warnings": ["field_review", APPROXIMATE_VALUE_WARNING],
            "visual_summary_chars": len("Site photo annotated"),
            "labels": ["Facade"],
            "relationships": ["Facade -> Entry"],
            "uncertainty": "approximate from field notes",
            "approximate": True,
            "figure_index": 8,
            "analysis_provider": "openai",
            "analysis_model": "fake-visual-model",
            "analysis_mode": "visual_only",
            "analysis_status": "enriched",
            "analysis_source_element_type": "image",
            "analysis_source_extraction_mode": "visual_summary",
            "analysis_source_confidence": 0.61,
        },
    ),
]


async def _remember_formatted_memory(
    fake_kb: FakeKB,
    element: DocumentElement,
) -> tuple[str, str, dict[str, object]]:
    chunks = list(chunk_and_format(element, size=4096, overlap=0))
    assert len(chunks) == 1, "expected one formatted chunk per synthetic element"
    content, metadata = chunks[0]
    memory_id = await fake_kb.remember(content, metadata=metadata)
    return memory_id, content, metadata


async def _seed_mixed_upload(fake_kb: FakeKB) -> list[SeededRecallCase]:
    seeded: list[SeededRecallCase] = []
    for case in MIXED_UPLOAD_CASES:
        element = case.build()
        memory_id, content, metadata = await _remember_formatted_memory(fake_kb, element)
        assert content == case.expected_content
        assert metadata == case.expected_metadata
        seeded.append(
            SeededRecallCase(
                name=case.name,
                query=case.query,
                memory_id=memory_id,
                expected_content=case.expected_content,
                expected_metadata=case.expected_metadata,
            )
        )
    return seeded


def _kb_recall_tool(fake_kb: FakeKB):
    tools = build_kb_tools(fake_kb)
    tool = next((tool for tool in tools if tool.name == "kb_recall"), None)
    assert tool is not None
    return tool


class TestKbRecallProvenance:
    async def test_kb_recall_preserves_mixed_upload_provenance(self) -> None:
        fake_kb = FakeKB()
        seeded = await _seed_mixed_upload(fake_kb)

        assert fake_kb.dump() == [
            {
                "id": case.memory_id,
                "content": case.expected_content,
                "metadata": case.expected_metadata,
                "score": 1.0,
            }
            for case in seeded
        ]

        kb_recall = _kb_recall_tool(fake_kb)
        for case in seeded:
            result = await kb_recall.ainvoke({"query": case.query, "k": 5})
            assert result == f"- ({case.memory_id}) {case.expected_content}"

    @pytest.mark.parametrize("query", ["", "no matching provenance token"])
    async def test_kb_recall_returns_exact_no_hit_message(
        self,
        query: str,
    ) -> None:
        fake_kb = FakeKB()
        await _seed_mixed_upload(fake_kb)

        result = await _kb_recall_tool(fake_kb).ainvoke({"query": query, "k": 5})

        assert result == "No relevant memories found."
