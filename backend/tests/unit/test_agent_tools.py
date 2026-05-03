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


ENGINEERING_DOCX_DOCUMENT_ID = "eng-docx-001"
ENGINEERING_DOCX_SOURCE = "loads.docx"
ENGINEERING_DOCX_PATH = "/synthetic/incoming/loads.docx"
ENGINEERING_DOCX_SUMMARY_CONTENT = "Title: Loads Spec\nAuthor: Test Engineer\nParagraphs: 2"
ENGINEERING_DOCX_SUMMARY_METADATA = {
    "subject": "engineering_narrative",
    "paragraph_count": 2,
    "docx_title": "Loads Spec",
    "docx_author": "Test Engineer",
}
ENGINEERING_DOCX_PARAGRAPH_CONTENT = "Sectioned engineering note keeps provenance visible."
ENGINEERING_DOCX_PARAGRAPH_METADATA = {
    "subject": "engineering_narrative",
    "block_index": 1,
    "style_name": "Normal",
    "section_heading": "Structural Notes",
}

ENGINEERING_XLSX_DOCUMENT_ID = "eng-xlsx-001"
ENGINEERING_XLSX_SOURCE = "loads.xlsx"
ENGINEERING_XLSX_PATH = "/synthetic/incoming/loads.xlsx"
ENGINEERING_XLSX_SUMMARY_CONTENT = (
    "Workbook overview: Loads workbook with two sheets.\n"
    "Visible sheets: Loads\n"
    "Hidden sheets: Hidden Notes"
)
ENGINEERING_XLSX_SUMMARY_METADATA = {
    "subject": "engineering_workbook",
    "sheet_count": 2,
    "xlsx_sheets": ["Loads", "Hidden Notes"],
    "xlsx_visible_sheet_count": 1,
    "xlsx_hidden_sheet_count": 1,
    "xlsx_non_empty_cell_count": 6,
    "xlsx_formula_cell_count": 1,
    "xlsx_comment_count": 1,
}
ENGINEERING_XLSX_SHEET_SUMMARY_CONTENT = "Sheet summary: north load values stay searchable."
ENGINEERING_XLSX_SHEET_SUMMARY_METADATA = {
    "subject": "engineering_workbook",
    "xlsx_sheet": "Loads",
    "xlsx_range": "A1:C3",
    "xlsx_sheet_state": "visible",
    "xlsx_non_empty_cell_count": 3,
    "xlsx_formula_cell_count": 1,
    "xlsx_comment_count": 1,
}
ENGINEERING_XLSX_CELL_CONTENT = "North load cell fact: 12 kN exact."
ENGINEERING_XLSX_CELL_METADATA = {
    "subject": "engineering_workbook",
    "xlsx_sheet": "Loads",
    "xlsx_cell": "B2",
    "xlsx_sheet_state": "visible",
    "xlsx_row_label": "North [kN]",
    "xlsx_column_label": "Load [kN]",
    "xlsx_label": "North [kN]",
    "xlsx_unit": "kN",
    "xlsx_value": 12,
    "xlsx_value_kind": "literal",
    "extraction_certainty": "exact",
}
ENGINEERING_XLSX_FORMULA_CONTENT = "Formula fact: cached result missing for north load."
ENGINEERING_XLSX_FORMULA_METADATA = {
    "subject": "engineering_workbook",
    "xlsx_sheet": "Loads",
    "xlsx_cell": "C2",
    "xlsx_sheet_state": "visible",
    "xlsx_row_label": "12",
    "xlsx_label": "12",
    "xlsx_formula": "=SUM(B2:B2)",
    "xlsx_value_kind": "missing_cached_value",
    "extraction_certainty": "exact_formula_cached_value_unknown",
}
ENGINEERING_XLSX_RANGE_CONTENT = "Range fact: north load block remains searchable."
ENGINEERING_XLSX_RANGE_METADATA = {
    "subject": "engineering_workbook",
    "xlsx_sheet": "Loads",
    "xlsx_range": "A1:C3",
    "xlsx_range_name": "LoadBlock",
    "xlsx_sheet_state": "visible",
    "table_rows": 3,
    "table_columns": 3,
}

ENGINEERING_DRAWING_DOCUMENT_ID = "eng-drawing-001"
ENGINEERING_DRAWING_SOURCE = "north.dwg"
ENGINEERING_DRAWING_SOURCE_PATH = "/synthetic/incoming/north.dwg"
ENGINEERING_DRAWING_ARTIFACT_PATH = "/synthetic/converted/north.pdf"
ENGINEERING_DRAWING_COMMON_METADATA = {
    "subject": "converted_drawing",
    "source_cad_file": "north.dwg",
    "source_cad_path": ENGINEERING_DRAWING_SOURCE_PATH,
    "derived_artifact_path": ENGINEERING_DRAWING_ARTIFACT_PATH,
    "conversion_status": "success",
    "conversion_source_extension": ".dwg",
    "conversion_warnings": ["converter_note"],
    "drawing_artifact_extension": ".pdf",
    "conversion_diagnostics": {
        "layers": ["A-WALL"],
        "views": ["Level 1"],
        "entities": ["Door 7"],
    },
    "drawing_layers": ["A-WALL"],
    "drawing_views": ["Level 1"],
    "drawing_entities": ["Door 7"],
}
ENGINEERING_DRAWING_SUMMARY_CONTENT = (
    "Converted drawing summary for north entry sheet.\n"
    "Text layer mode: exact\n"
    "Conversion warnings: converter_note\n"
    "Layers: A-WALL\n"
    "Views: Level 1\n"
    "Entities: Door 7"
)
ENGINEERING_DRAWING_SUMMARY_METADATA = {
    **ENGINEERING_DRAWING_COMMON_METADATA,
    "drawing_fact_type": "summary",
    "drawing_page_count": 2,
    "drawing_text_page_count": 2,
    "drawing_fact_count": 3,
    "drawing_fact_types": ["layer", "entity_view"],
}
ENGINEERING_DRAWING_LAYER_FACT_CONTENT = "Layer fact line: A-WALL"
ENGINEERING_DRAWING_LAYER_FACT_METADATA = {
    **ENGINEERING_DRAWING_COMMON_METADATA,
    "drawing_fact_type": "layer",
    "drawing_fact_value": "A-WALL",
    "drawing_line_number": 12,
}
ENGINEERING_DRAWING_VIEW_FACT_CONTENT = "View fact line: Level 1"
ENGINEERING_DRAWING_VIEW_FACT_METADATA = {
    **ENGINEERING_DRAWING_COMMON_METADATA,
    "drawing_fact_type": "entity_view",
    "drawing_fact_subtype": "view",
    "drawing_fact_value": "Level 1",
    "drawing_line_number": 13,
}
ENGINEERING_DRAWING_ENTITY_FACT_CONTENT = "Entity fact line: Door 7"
ENGINEERING_DRAWING_ENTITY_FACT_METADATA = {
    **ENGINEERING_DRAWING_COMMON_METADATA,
    "drawing_fact_type": "entity_view",
    "drawing_fact_subtype": "entity",
    "drawing_fact_value": "Door 7",
    "drawing_line_number": 14,
}


async def _seed_recall_cases(
    fake_kb: FakeKB,
    cases: list[RecallCase],
) -> list[SeededRecallCase]:
    seeded: list[SeededRecallCase] = []
    for case in cases:
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


def _build_engineering_docx_summary_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_DOCX_DOCUMENT_ID,
        source=ENGINEERING_DOCX_SOURCE,
        path=ENGINEERING_DOCX_PATH,
        page=None,
        element_type="file_summary",
        extraction_mode="docx_summary",
        content=ENGINEERING_DOCX_SUMMARY_CONTENT,
        confidence=None,
        warnings=(),
        metadata=ENGINEERING_DOCX_SUMMARY_METADATA,
    )


def _build_engineering_docx_paragraph_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_DOCX_DOCUMENT_ID,
        source=ENGINEERING_DOCX_SOURCE,
        path=ENGINEERING_DOCX_PATH,
        page=None,
        element_type="paragraph",
        extraction_mode="docx_paragraph",
        content=ENGINEERING_DOCX_PARAGRAPH_CONTENT,
        confidence=None,
        warnings=(),
        metadata=ENGINEERING_DOCX_PARAGRAPH_METADATA,
    )


def _build_engineering_xlsx_summary_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_XLSX_DOCUMENT_ID,
        source=ENGINEERING_XLSX_SOURCE,
        path=ENGINEERING_XLSX_PATH,
        page=None,
        element_type="file_summary",
        extraction_mode="xlsx_summary",
        content=ENGINEERING_XLSX_SUMMARY_CONTENT,
        confidence=1.0,
        warnings=(),
        metadata=ENGINEERING_XLSX_SUMMARY_METADATA,
    )


def _build_engineering_xlsx_sheet_summary_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_XLSX_DOCUMENT_ID,
        source=ENGINEERING_XLSX_SOURCE,
        path=ENGINEERING_XLSX_PATH,
        page=None,
        element_type="sheet_summary",
        extraction_mode="xlsx_sheet_summary",
        content=ENGINEERING_XLSX_SHEET_SUMMARY_CONTENT,
        confidence=1.0,
        warnings=(),
        metadata=ENGINEERING_XLSX_SHEET_SUMMARY_METADATA,
    )


def _build_engineering_xlsx_cell_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_XLSX_DOCUMENT_ID,
        source=ENGINEERING_XLSX_SOURCE,
        path=ENGINEERING_XLSX_PATH,
        page=None,
        element_type="cell",
        extraction_mode="xlsx_cell",
        content=ENGINEERING_XLSX_CELL_CONTENT,
        confidence=1.0,
        warnings=(),
        metadata=ENGINEERING_XLSX_CELL_METADATA,
    )


def _build_engineering_xlsx_formula_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_XLSX_DOCUMENT_ID,
        source=ENGINEERING_XLSX_SOURCE,
        path=ENGINEERING_XLSX_PATH,
        page=None,
        element_type="formula",
        extraction_mode="xlsx_formula",
        content=ENGINEERING_XLSX_FORMULA_CONTENT,
        confidence=1.0,
        warnings=("missing_cached_value",),
        metadata=ENGINEERING_XLSX_FORMULA_METADATA,
    )


def _build_engineering_xlsx_range_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_XLSX_DOCUMENT_ID,
        source=ENGINEERING_XLSX_SOURCE,
        path=ENGINEERING_XLSX_PATH,
        page=None,
        element_type="range",
        extraction_mode="xlsx_range",
        content=ENGINEERING_XLSX_RANGE_CONTENT,
        confidence=1.0,
        warnings=(),
        metadata=ENGINEERING_XLSX_RANGE_METADATA,
    )


def _build_engineering_drawing_summary_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_DRAWING_DOCUMENT_ID,
        source=ENGINEERING_DRAWING_SOURCE,
        path=ENGINEERING_DRAWING_ARTIFACT_PATH,
        page=None,
        element_type="drawing",
        extraction_mode="converted_drawing_text_summary",
        content=ENGINEERING_DRAWING_SUMMARY_CONTENT,
        confidence=1.0,
        warnings=("converter_note",),
        metadata=ENGINEERING_DRAWING_SUMMARY_METADATA,
    )


def _build_engineering_drawing_layer_fact_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_DRAWING_DOCUMENT_ID,
        source=ENGINEERING_DRAWING_SOURCE,
        path=ENGINEERING_DRAWING_ARTIFACT_PATH,
        page=1,
        element_type="drawing_fact",
        extraction_mode="converted_drawing_text_fact",
        content=ENGINEERING_DRAWING_LAYER_FACT_CONTENT,
        confidence=1.0,
        warnings=("converter_note",),
        metadata=ENGINEERING_DRAWING_LAYER_FACT_METADATA,
    )


def _build_engineering_drawing_view_fact_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_DRAWING_DOCUMENT_ID,
        source=ENGINEERING_DRAWING_SOURCE,
        path=ENGINEERING_DRAWING_ARTIFACT_PATH,
        page=2,
        element_type="drawing_fact",
        extraction_mode="converted_drawing_text_fact",
        content=ENGINEERING_DRAWING_VIEW_FACT_CONTENT,
        confidence=1.0,
        warnings=("converter_note",),
        metadata=ENGINEERING_DRAWING_VIEW_FACT_METADATA,
    )


def _build_engineering_drawing_entity_fact_element() -> DocumentElement:
    return DocumentElement(
        document_id=ENGINEERING_DRAWING_DOCUMENT_ID,
        source=ENGINEERING_DRAWING_SOURCE,
        path=ENGINEERING_DRAWING_ARTIFACT_PATH,
        page=3,
        element_type="drawing_fact",
        extraction_mode="converted_drawing_text_fact",
        content=ENGINEERING_DRAWING_ENTITY_FACT_CONTENT,
        confidence=1.0,
        warnings=("converter_note",),
        metadata=ENGINEERING_DRAWING_ENTITY_FACT_METADATA,
    )


ENGINEERING_DOCX_CASES: list[RecallCase] = [
    RecallCase(
        name="docx-summary",
        build=_build_engineering_docx_summary_element,
        query="Loads Spec",
        expected_content=(
            "[source=loads.docx; element=file_summary; extraction=docx_summary]\n"
            f"{ENGINEERING_DOCX_SUMMARY_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_DOCX_DOCUMENT_ID,
            "source": ENGINEERING_DOCX_SOURCE,
            "path": ENGINEERING_DOCX_PATH,
            "page": None,
            "element_type": "file_summary",
            "extraction_mode": "docx_summary",
            "warnings": [],
            **ENGINEERING_DOCX_SUMMARY_METADATA,
        },
    ),
    RecallCase(
        name="docx-paragraph",
        build=_build_engineering_docx_paragraph_element,
        query="Sectioned engineering note",
        expected_content=(
            "[source=loads.docx; section=Structural Notes; element=paragraph; "
            "extraction=docx_paragraph]\n"
            f"{ENGINEERING_DOCX_PARAGRAPH_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_DOCX_DOCUMENT_ID,
            "source": ENGINEERING_DOCX_SOURCE,
            "path": ENGINEERING_DOCX_PATH,
            "page": None,
            "element_type": "paragraph",
            "extraction_mode": "docx_paragraph",
            "warnings": [],
            **ENGINEERING_DOCX_PARAGRAPH_METADATA,
        },
    ),
]

ENGINEERING_XLSX_CASES: list[RecallCase] = [
    RecallCase(
        name="xlsx-summary",
        build=_build_engineering_xlsx_summary_element,
        query="Workbook overview",
        expected_content=(
            "[source=loads.xlsx; element=file_summary; extraction=xlsx_summary; "
            "confidence=1.0]\n"
            f"{ENGINEERING_XLSX_SUMMARY_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_XLSX_DOCUMENT_ID,
            "source": ENGINEERING_XLSX_SOURCE,
            "path": ENGINEERING_XLSX_PATH,
            "page": None,
            "element_type": "file_summary",
            "extraction_mode": "xlsx_summary",
            "confidence": 1.0,
            "warnings": [],
            **ENGINEERING_XLSX_SUMMARY_METADATA,
        },
    ),
    RecallCase(
        name="xlsx-sheet-summary",
        build=_build_engineering_xlsx_sheet_summary_element,
        query="north load values",
        expected_content=(
            "[source=loads.xlsx; sheet=Loads; range=A1:C3; element=sheet_summary; "
            "extraction=xlsx_sheet_summary; confidence=1.0]\n"
            f"{ENGINEERING_XLSX_SHEET_SUMMARY_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_XLSX_DOCUMENT_ID,
            "source": ENGINEERING_XLSX_SOURCE,
            "path": ENGINEERING_XLSX_PATH,
            "page": None,
            "element_type": "sheet_summary",
            "extraction_mode": "xlsx_sheet_summary",
            "confidence": 1.0,
            "warnings": [],
            **ENGINEERING_XLSX_SHEET_SUMMARY_METADATA,
        },
    ),
    RecallCase(
        name="xlsx-cell",
        build=_build_engineering_xlsx_cell_element,
        query="North load cell fact",
        expected_content=(
            "[source=loads.xlsx; sheet=Loads; cell=B2; label=North [kN]; unit=kN; "
            "element=cell; extraction=xlsx_cell; certainty=exact; confidence=1.0]\n"
            f"{ENGINEERING_XLSX_CELL_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_XLSX_DOCUMENT_ID,
            "source": ENGINEERING_XLSX_SOURCE,
            "path": ENGINEERING_XLSX_PATH,
            "page": None,
            "element_type": "cell",
            "extraction_mode": "xlsx_cell",
            "confidence": 1.0,
            "warnings": [],
            **ENGINEERING_XLSX_CELL_METADATA,
        },
    ),
    RecallCase(
        name="xlsx-formula",
        build=_build_engineering_xlsx_formula_element,
        query="cached result missing",
        expected_content=(
            "[source=loads.xlsx; sheet=Loads; cell=C2; label=12; element=formula; "
            "extraction=xlsx_formula; certainty=exact_formula_cached_value_unknown; "
            "confidence=1.0; warnings=missing_cached_value]\n"
            f"{ENGINEERING_XLSX_FORMULA_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_XLSX_DOCUMENT_ID,
            "source": ENGINEERING_XLSX_SOURCE,
            "path": ENGINEERING_XLSX_PATH,
            "page": None,
            "element_type": "formula",
            "extraction_mode": "xlsx_formula",
            "confidence": 1.0,
            "warnings": ["missing_cached_value"],
            **ENGINEERING_XLSX_FORMULA_METADATA,
        },
    ),
    RecallCase(
        name="xlsx-range",
        build=_build_engineering_xlsx_range_element,
        query="north load block",
        expected_content=(
            "[source=loads.xlsx; sheet=Loads; range=A1:C3; range_name=LoadBlock; "
            "element=range; extraction=xlsx_range; confidence=1.0]\n"
            f"{ENGINEERING_XLSX_RANGE_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_XLSX_DOCUMENT_ID,
            "source": ENGINEERING_XLSX_SOURCE,
            "path": ENGINEERING_XLSX_PATH,
            "page": None,
            "element_type": "range",
            "extraction_mode": "xlsx_range",
            "confidence": 1.0,
            "warnings": [],
            **ENGINEERING_XLSX_RANGE_METADATA,
        },
    ),
]

ENGINEERING_DRAWING_CASES: list[RecallCase] = [
    RecallCase(
        name="drawing-summary",
        build=_build_engineering_drawing_summary_element,
        query="Conversion warnings",
        expected_content=(
            "[source=north.dwg; layers=A-WALL; views=Level 1; entities=Door 7; "
            "element=drawing; extraction=converted_drawing_text_summary; "
            "confidence=1.0; warnings=converter_note]\n"
            f"{ENGINEERING_DRAWING_SUMMARY_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_DRAWING_DOCUMENT_ID,
            "source": ENGINEERING_DRAWING_SOURCE,
            "path": ENGINEERING_DRAWING_ARTIFACT_PATH,
            "page": None,
            "element_type": "drawing",
            "extraction_mode": "converted_drawing_text_summary",
            "confidence": 1.0,
            "warnings": ["converter_note"],
            **ENGINEERING_DRAWING_SUMMARY_METADATA,
        },
    ),
    RecallCase(
        name="drawing-layer-fact",
        build=_build_engineering_drawing_layer_fact_element,
        query="Layer fact line",
        expected_content=(
            "[source=north.dwg; page=1; layers=A-WALL; views=Level 1; entities=Door 7; "
            "fact=layer; layer=A-WALL; line=12; element=drawing_fact; "
            "extraction=converted_drawing_text_fact; confidence=1.0; "
            "warnings=converter_note]\n"
            f"{ENGINEERING_DRAWING_LAYER_FACT_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_DRAWING_DOCUMENT_ID,
            "source": ENGINEERING_DRAWING_SOURCE,
            "path": ENGINEERING_DRAWING_ARTIFACT_PATH,
            "page": 1,
            "element_type": "drawing_fact",
            "extraction_mode": "converted_drawing_text_fact",
            "confidence": 1.0,
            "warnings": ["converter_note"],
            **ENGINEERING_DRAWING_LAYER_FACT_METADATA,
        },
    ),
    RecallCase(
        name="drawing-view-fact",
        build=_build_engineering_drawing_view_fact_element,
        query="View fact line",
        expected_content=(
            "[source=north.dwg; page=2; layers=A-WALL; views=Level 1; entities=Door 7; "
            "fact=entity_view; view=Level 1; line=13; element=drawing_fact; "
            "extraction=converted_drawing_text_fact; confidence=1.0; "
            "warnings=converter_note]\n"
            f"{ENGINEERING_DRAWING_VIEW_FACT_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_DRAWING_DOCUMENT_ID,
            "source": ENGINEERING_DRAWING_SOURCE,
            "path": ENGINEERING_DRAWING_ARTIFACT_PATH,
            "page": 2,
            "element_type": "drawing_fact",
            "extraction_mode": "converted_drawing_text_fact",
            "confidence": 1.0,
            "warnings": ["converter_note"],
            **ENGINEERING_DRAWING_VIEW_FACT_METADATA,
        },
    ),
    RecallCase(
        name="drawing-entity-fact",
        build=_build_engineering_drawing_entity_fact_element,
        query="Entity fact line",
        expected_content=(
            "[source=north.dwg; page=3; layers=A-WALL; views=Level 1; entities=Door 7; "
            "fact=entity_view; entity=Door 7; line=14; element=drawing_fact; "
            "extraction=converted_drawing_text_fact; confidence=1.0; "
            "warnings=converter_note]\n"
            f"{ENGINEERING_DRAWING_ENTITY_FACT_CONTENT}"
        ),
        expected_metadata={
            "document_id": ENGINEERING_DRAWING_DOCUMENT_ID,
            "source": ENGINEERING_DRAWING_SOURCE,
            "path": ENGINEERING_DRAWING_ARTIFACT_PATH,
            "page": 3,
            "element_type": "drawing_fact",
            "extraction_mode": "converted_drawing_text_fact",
            "confidence": 1.0,
            "warnings": ["converter_note"],
            **ENGINEERING_DRAWING_ENTITY_FACT_METADATA,
        },
    ),
]


class TestEngineeringKbRecallProvenance:
    async def test_kb_recall_preserves_docx_engineering_provenance(self) -> None:
        fake_kb = FakeKB()
        seeded = await _seed_recall_cases(fake_kb, ENGINEERING_DOCX_CASES)

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

    async def test_kb_recall_preserves_xlsx_engineering_provenance(self) -> None:
        fake_kb = FakeKB()
        seeded = await _seed_recall_cases(fake_kb, ENGINEERING_XLSX_CASES)

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

    async def test_kb_recall_preserves_converted_drawing_engineering_provenance(
        self,
    ) -> None:
        fake_kb = FakeKB()
        seeded = await _seed_recall_cases(fake_kb, ENGINEERING_DRAWING_CASES)

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
