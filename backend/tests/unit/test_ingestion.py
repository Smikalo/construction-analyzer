"""Tests for the document ingestion pipeline (text + markdown loaders, chunker)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from openpyxl import Workbook

import app.services.converted_drawing_elements as converted_drawing_elements
from app.kb.fake import FakeKB
from app.services import ingestion as ingestion_module
from app.services.document_analysis import OPENAI_ENRICHMENT_FAILED_WARNING
from app.services.document_elements import DocumentElement
from app.services.document_registry import lifespan_document_registry
from app.services.engineering_converters import ConversionResult
from app.services.ingestion import (
    DEFAULT_CHUNK_SIZE,
    RegisteredIngestFile,
    _chunk,
    ingest_directory,
    ingest_files,
    ingest_registered_files,
)
from app.services.ocr_elements import ocr_element_from_text
from app.services.table_elements import table_element_from_rows
from app.services.visual_elements import VISUAL_ELEMENT_TYPES, visual_element_from_summary


def _analysis_metadata(element: DocumentElement, *, status: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "analysis_provider": "fake-openai",
        "analysis_model": "fake-visual-model",
        "analysis_mode": "visual_only",
        "analysis_status": status,
        "analysis_source_element_type": element.element_type,
        "analysis_source_extraction_mode": element.extraction_mode,
    }
    if element.confidence is not None:
        metadata["analysis_source_confidence"] = element.confidence
    return metadata


def _merge_warnings(*warning_groups: Sequence[str]) -> tuple[str, ...]:
    merged: list[str] = []
    for warning_group in warning_groups:
        for warning in warning_group:
            if warning and warning not in merged:
                merged.append(warning)
    return tuple(merged)


def _enriched_chart_element(element: DocumentElement) -> DocumentElement:
    visual = visual_element_from_summary(
        "North span load chart with wind load annotations",
        element_type=element.element_type,
        source=element.source,
        document_id=element.document_id,
        path=element.path,
        page=element.page,
        confidence=0.87,
        labels=("North span", "South span"),
        relationships=("North span -> South span",),
        uncertainty="estimated from site photo",
        approximate=True,
        warnings=element.warnings,
        metadata={
            **element.metadata,
            **_analysis_metadata(element, status="enriched"),
        },
    )
    assert visual is not None
    return visual


def _failed_chart_element(element: DocumentElement) -> DocumentElement:
    return replace(
        element,
        warnings=_merge_warnings(element.warnings, (OPENAI_ENRICHMENT_FAILED_WARNING,)),
        metadata={
            **element.metadata,
            **_analysis_metadata(element, status="failed"),
        },
    )


class VisualOnlyAnalyzer:
    def __init__(self, transform) -> None:
        self.calls: list[list[DocumentElement]] = []
        self._transform = transform

    def enrich(self, elements: Sequence[DocumentElement]) -> list[DocumentElement]:
        batch = list(elements)
        assert batch
        assert all(element.element_type in VISUAL_ELEMENT_TYPES for element in batch)
        self.calls.append(batch)
        return [self._transform(element) for element in batch]


class FailingAnalyzer:
    def enrich(self, elements: Sequence[DocumentElement]) -> list[DocumentElement]:
        raise AssertionError(f"analyzer should not have been called for: {list(elements)!r}")


class RecordingEngineeringConverter:
    def __init__(self, convert) -> None:
        self.calls: list[str] = []
        self._convert = convert

    def convert(self, source_path: str) -> ConversionResult:
        self.calls.append(source_path)
        return self._convert(source_path)

    def get_diagnostics(self) -> dict[str, object]:
        return {"calls": len(self.calls)}


class TestChunker:
    def test_short_text_yields_one_chunk(self) -> None:
        out = list(_chunk("hello world", size=100, overlap=10))
        assert out == ["hello world"]

    def test_long_text_yields_overlapping_chunks(self) -> None:
        text = "ABCDEFGHIJ" * 5  # 50 chars
        out = list(_chunk(text, size=20, overlap=5))
        assert all(len(c) <= 20 for c in out)
        # Step is 15, so we expect ceil(50 / 15) = 4 chunks.
        assert len(out) == 4
        # Overlap is observable.
        assert out[0][-5:] == out[1][:5]

    def test_empty_text_yields_nothing(self) -> None:
        assert list(_chunk("", size=20, overlap=5)) == []

    def test_invalid_overlap_raises(self) -> None:
        with pytest.raises(ValueError):
            list(_chunk("abc", size=10, overlap=10))


class TestIngestFiles:
    async def test_ingest_text_file(self, tmp_path: Path) -> None:
        path = tmp_path / "note.txt"
        path.write_text("the cat sat on the mat")
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 1
        assert result.ingested_chunks == 1
        records = kb.dump()
        assert len(records) == 1
        assert records[0]["content"].startswith("[source=note.txt;")
        assert records[0]["content"].endswith("the cat sat on the mat")
        metadata = records[0]["metadata"]
        assert metadata["source"] == "note.txt"
        assert metadata["extraction_mode"] == "text"
        assert metadata["element_type"] == "paragraph"
        assert "page" in metadata
        assert metadata["page"] is None

    async def test_ingest_markdown_file(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.md"
        path.write_text("# Title\n\nSome content here")
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 1
        records = kb.dump()
        assert len(records) == result.ingested_chunks
        assert records[0]["content"].startswith("[source=doc.md;")
        metadata = records[0]["metadata"]
        assert metadata["source"] == "doc.md"
        assert metadata["extraction_mode"] == "markdown"
        assert metadata["element_type"] == "paragraph"
        assert "page" in metadata
        assert metadata["page"] is None

    async def test_ingest_empty_markdown_file_writes_no_memories(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.md"
        path.write_text("")
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 0
        assert result.ingested_chunks == 0
        assert result.memory_ids == []
        assert kb.dump() == []

    async def test_ingest_skips_missing_files(self, tmp_path: Path) -> None:
        kb = FakeKB()
        result = await ingest_files(kb, [str(tmp_path / "missing.txt")])
        assert result.ingested_files == 0
        assert result.ingested_chunks == 0

    async def test_ingest_chunks_long_file(self, tmp_path: Path) -> None:
        path = tmp_path / "big.txt"
        path.write_text("X" * (DEFAULT_CHUNK_SIZE * 3))
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 1
        assert result.ingested_chunks >= 3


class TestIngestRegisteredFiles:
    async def test_registered_ingest_persists_indexed_status_and_memory_ids(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "stored.txt"
        path.write_text("registered content")
        kb = FakeKB()

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-1",
                original_filename="original.txt",
                stored_path=str(path),
                content_type="text/plain",
                byte_size=path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "indexed"
            assert updated.error is None
            assert updated.memory_ids == result.memory_ids
            assert result.ingested_files == 1
            assert result.ingested_chunks == 1
            memories = kb.dump()
            assert memories[0]["metadata"]["source"] == "original.txt"
            assert memories[0]["metadata"]["document_id"] == record.document_id

    async def test_registered_table_element_is_remembered_with_provenance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "stored.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            element = table_element_from_rows(
                [["Room", "Area"], ["A101", "42 m2"]],
                document_id=document_id,
                source=source,
                path=parser_path,
                page=4,
                confidence=0.91,
                warnings=("merged_cells",),
            )
            assert element is not None
            return [element]

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-table",
                original_filename="schedule.pdf",
                stored_path=str(path),
                content_type="application/pdf",
                byte_size=path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "indexed"
            assert updated.error is None
            assert updated.memory_ids == result.memory_ids
            assert result.ingested_files == 1
            assert result.ingested_chunks == 1

            memories = kb.dump()
            assert len(memories) == 1
            content = memories[0]["content"]
            assert content.startswith(
                "[source=schedule.pdf; page=4; element=table; extraction=pdf_table; "
                "confidence=0.91; warnings=merged_cells]\n"
            )
            assert content.endswith("| Room | Area |\n| --- | --- |\n| A101 | 42 m2 |")
            metadata = memories[0]["metadata"]
            assert metadata["document_id"] == record.document_id
            assert metadata["source"] == "schedule.pdf"
            assert metadata["path"] == str(path)
            assert metadata["page"] == 4
            assert metadata["element_type"] == "table"
            assert metadata["extraction_mode"] == "pdf_table"
            assert metadata["confidence"] == 0.91
            assert metadata["warnings"] == ["merged_cells"]
            assert metadata["table_rows"] == 2
            assert metadata["table_columns"] == 2

    async def test_registered_visual_summary_is_remembered_with_provenance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "stored.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            visual_element = visual_element_from_summary(
                "North span load chart",
                element_type="chart",
                source=source,
                document_id=document_id,
                path=parser_path,
                page=4,
                confidence=0.83,
                labels=("North span", "South span"),
                relationships=("North span -> South span",),
                uncertainty="estimated from site photo",
                approximate=True,
                metadata={"captured_by": "fake-parser", "chart_index": 7},
            )
            assert visual_element is not None
            return [
                DocumentElement(
                    document_id=document_id,
                    source=source,
                    path=parser_path,
                    page=1,
                    element_type="paragraph",
                    extraction_mode="pdf_text",
                    content="cover page body",
                ),
                visual_element,
            ]

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-visual",
                original_filename="schedule.pdf",
                stored_path=str(path),
                content_type="application/pdf",
                byte_size=path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "indexed"
            assert updated.error is None
            assert updated.memory_ids == result.memory_ids
            assert result.ingested_files == 1
            assert result.ingested_chunks == 2

            memories = kb.dump()
            assert len(memories) == 2
            assert memories[0]["content"] == (
                "[source=schedule.pdf; page=1; element=paragraph; extraction=pdf_text]\n"
                "cover page body"
            )

            content = memories[1]["content"]
            assert content == (
                "[source=schedule.pdf; page=4; element=chart; extraction=visual_summary; "
                "confidence=0.83; warnings=approximate_values]\n"
                "North span load chart\n"
                "Labels: North span; South span\n"
                "Relationships: North span -> South span\n"
                "Uncertainty: estimated from site photo"
            )

            metadata = memories[1]["metadata"]
            assert metadata == {
                "document_id": record.document_id,
                "source": "schedule.pdf",
                "path": str(path),
                "page": 4,
                "element_type": "chart",
                "extraction_mode": "visual_summary",
                "confidence": 0.83,
                "warnings": ["approximate_values"],
                "visual_summary_chars": len("North span load chart"),
                "labels": ["North span", "South span"],
                "relationships": ["North span -> South span"],
                "uncertainty": "estimated from site photo",
                "approximate": True,
                "captured_by": "fake-parser",
                "chart_index": 7,
            }

    async def test_registered_mixed_visual_elements_enrich_only_visual_elements_and_preserve_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "stored.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-mixed-visual",
                original_filename="schedule.pdf",
                stored_path=str(path),
                content_type="application/pdf",
                byte_size=path.stat().st_size,
            )

            chart_element = visual_element_from_summary(
                "North span load chart",
                element_type="chart",
                source=record.original_filename,
                document_id=record.document_id,
                path=str(path),
                page=4,
                confidence=0.83,
                labels=("North span", "South span"),
                relationships=("North span -> South span",),
                uncertainty="estimated from site photo",
                approximate=True,
                warnings=("parser_visual_hint",),
                metadata={"captured_by": "fake-parser", "chart_index": 7},
            )
            assert chart_element is not None
            analyzer = VisualOnlyAnalyzer(_enriched_chart_element)

            def fake_parse_document(
                parser_path: str,
                *,
                source: str,
                document_id: str | None = None,
            ) -> list[DocumentElement]:
                paragraph = DocumentElement(
                    document_id=document_id,
                    source=source,
                    path=parser_path,
                    page=1,
                    element_type="paragraph",
                    extraction_mode="pdf_text",
                    content="cover page body",
                )
                table_element = table_element_from_rows(
                    [["Room", "Area"], ["A101", "42 m2"]],
                    source=source,
                    document_id=document_id,
                    path=parser_path,
                    page=2,
                    confidence=0.91,
                    warnings=("table_normalized",),
                    metadata={"table_index": 3},
                )
                assert table_element is not None
                ocr_element = ocr_element_from_text(
                    "  recovered\n sheet\tnote  ",
                    document_id=document_id,
                    source=source,
                    path=parser_path,
                    page=3,
                    confidence=0.41,
                    warnings=("low_text_page", "ocr_low_confidence"),
                    low_text_threshold=20,
                    metadata={"ocr_engine": "fake"},
                )
                assert ocr_element is not None
                return [paragraph, table_element, ocr_element, chart_element]

            monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
                document_analyzer=analyzer,
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "indexed"
            assert updated.error is None
            assert updated.memory_ids == result.memory_ids
            assert result.ingested_files == 1
            assert result.ingested_chunks == 4
            assert analyzer.calls == [[chart_element]]

            memories = kb.dump()
            assert len(memories) == 4
            assert memories[0]["content"].startswith(
                "[source=schedule.pdf; page=1; element=paragraph; extraction=pdf_text]"
            )
            assert memories[0]["content"].endswith("cover page body")
            assert memories[0]["metadata"] == {
                "document_id": record.document_id,
                "source": "schedule.pdf",
                "path": str(path),
                "page": 1,
                "element_type": "paragraph",
                "extraction_mode": "pdf_text",
                "warnings": [],
            }
            assert memories[1]["content"].startswith(
                "[source=schedule.pdf; page=2; element=table; extraction=pdf_table; "
                "confidence=0.91; warnings=table_normalized]"
            )
            assert memories[1]["content"].endswith("| A101 | 42 m2 |")
            assert memories[1]["metadata"]["table_rows"] == 2
            assert memories[1]["metadata"]["table_columns"] == 2
            assert "analysis_provider" not in memories[1]["metadata"]
            assert memories[2]["content"].startswith(
                "[source=schedule.pdf; page=3; element=ocr_text; extraction=ocr; "
                "confidence=0.41; warnings=low_text_page,ocr_low_confidence]"
            )
            assert memories[2]["content"].endswith("recovered sheet note")
            assert memories[2]["metadata"]["ocr_text_chars"] == len("recovered sheet note")
            assert memories[2]["metadata"]["low_text_threshold"] == 20
            assert "analysis_provider" not in memories[2]["metadata"]
            assert memories[3]["content"].startswith(
                "[source=schedule.pdf; page=4; element=chart; extraction=visual_summary; "
                "confidence=0.87; warnings=parser_visual_hint,approximate_values]"
            )
            assert memories[3]["content"].endswith(
                "North span load chart with wind load annotations\nLabels: North span; South span\n"
                "Relationships: North span -> South span\n"
                "Uncertainty: estimated from site photo"
            )
            assert memories[3]["metadata"] == {
                "document_id": record.document_id,
                "source": "schedule.pdf",
                "path": str(path),
                "page": 4,
                "element_type": "chart",
                "extraction_mode": "visual_summary",
                "confidence": 0.87,
                "warnings": ["parser_visual_hint", "approximate_values"],
                "visual_summary_chars": len("North span load chart"),
                "labels": ["North span", "South span"],
                "relationships": ["North span -> South span"],
                "uncertainty": "estimated from site photo",
                "approximate": True,
                "captured_by": "fake-parser",
                "chart_index": 7,
                "analysis_provider": "fake-openai",
                "analysis_model": "fake-visual-model",
                "analysis_mode": "visual_only",
                "analysis_status": "enriched",
                "analysis_source_element_type": "chart",
                "analysis_source_extraction_mode": "visual_summary",
                "analysis_source_confidence": 0.83,
            }

    async def test_registered_visual_analyzer_failure_keeps_indexing_with_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "stored.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-visual-fallback",
                original_filename="schedule.pdf",
                stored_path=str(path),
                content_type="application/pdf",
                byte_size=path.stat().st_size,
            )

            chart_element = visual_element_from_summary(
                "Original visual summary",
                element_type="chart",
                source=record.original_filename,
                document_id=record.document_id,
                path=str(path),
                page=4,
                confidence=0.83,
                warnings=("parser_visual_hint",),
                metadata={"captured_by": "fake-parser", "chart_index": 8},
            )
            assert chart_element is not None
            analyzer = VisualOnlyAnalyzer(_failed_chart_element)

            def fake_parse_document(
                parser_path: str,
                *,
                source: str,
                document_id: str | None = None,
            ) -> list[DocumentElement]:
                return [
                    replace(
                        chart_element,
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                    )
                ]

            monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
                document_analyzer=analyzer,
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "indexed"
            assert updated.error is None
            assert updated.memory_ids == result.memory_ids
            assert result.ingested_files == 1
            assert result.ingested_chunks == 1
            assert analyzer.calls == [[chart_element]]

            memories = kb.dump()
            assert len(memories) == 1
            assert memories[0]["content"].startswith(
                "[source=schedule.pdf; page=4; element=chart; extraction=visual_summary; "
                "confidence=0.83; warnings=parser_visual_hint,openai_enrichment_failed]"
            )
            assert memories[0]["content"].endswith("Original visual summary")
            assert memories[0]["metadata"] == {
                "document_id": record.document_id,
                "source": "schedule.pdf",
                "path": str(path),
                "page": 4,
                "element_type": "chart",
                "extraction_mode": "visual_summary",
                "confidence": 0.83,
                "warnings": ["parser_visual_hint", "openai_enrichment_failed"],
                "visual_summary_chars": len("Original visual summary"),
                "captured_by": "fake-parser",
                "chart_index": 8,
                "analysis_provider": "fake-openai",
                "analysis_model": "fake-visual-model",
                "analysis_mode": "visual_only",
                "analysis_status": "failed",
                "analysis_source_element_type": "chart",
                "analysis_source_extraction_mode": "visual_summary",
                "analysis_source_confidence": 0.83,
            }

    async def test_registered_ocr_element_is_remembered_with_provenance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "stored.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            ocr_element = ocr_element_from_text(
                "  recovered\n sheet\tnote  ",
                document_id=document_id,
                source=source,
                path=parser_path,
                page=2,
                confidence=0.41,
                warnings=("low_text_page", "ocr_low_confidence"),
                low_text_threshold=20,
                metadata={"ocr_engine": "fake"},
            )
            assert ocr_element is not None
            return [
                DocumentElement(
                    document_id=document_id,
                    source=source,
                    path=parser_path,
                    page=1,
                    element_type="paragraph",
                    extraction_mode="pdf_text",
                    content="parsed cover sheet",
                ),
                ocr_element,
            ]

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-ocr",
                original_filename="scan.pdf",
                stored_path=str(path),
                content_type="application/pdf",
                byte_size=path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "indexed"
            assert updated.error is None
            assert updated.memory_ids == result.memory_ids
            assert result.ingested_files == 1
            assert result.ingested_chunks == 2

            memories = kb.dump()
            assert len(memories) == 2
            assert memories[0]["content"].startswith(
                "[source=scan.pdf; page=1; element=paragraph; extraction=pdf_text]\n"
            )
            assert memories[0]["content"].endswith("parsed cover sheet")

            ocr_content = memories[1]["content"]
            assert ocr_content.startswith(
                "[source=scan.pdf; page=2; element=ocr_text; extraction=ocr; "
                "confidence=0.41; warnings=low_text_page,ocr_low_confidence]\n"
            )
            assert ocr_content.endswith("recovered sheet note")

            metadata = memories[1]["metadata"]
            assert metadata["document_id"] == record.document_id
            assert metadata["source"] == "scan.pdf"
            assert metadata["path"] == str(path)
            assert metadata["page"] == 2
            assert metadata["element_type"] == "ocr_text"
            assert metadata["extraction_mode"] == "ocr"
            assert metadata["confidence"] == 0.41
            assert metadata["warnings"] == ["low_text_page", "ocr_low_confidence"]
            assert metadata["ocr_text_chars"] == len("recovered sheet note")
            assert metadata["low_text_threshold"] == 20
            assert metadata["ocr_engine"] == "fake"

    async def test_registered_duplicate_reuses_memory_ids_without_remembering(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        kb = FakeKB()

        def should_not_parse(*_args: object, **_kwargs: object) -> list[DocumentElement]:
            raise AssertionError("parse_document should not run for duplicate entries")

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", should_not_parse)

        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-2",
                original_filename="original.txt",
                stored_path=str(tmp_path / "stored.txt"),
                content_type="text/plain",
                byte_size=5,
            )
            indexed = registry.update_status(
                record.document_id,
                "indexed",
                memory_ids=["existing-memory"],
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=indexed, is_duplicate=True)],
                document_analyzer=FailingAnalyzer(),
            )

            assert result.ingested_files == 0
            assert result.ingested_chunks == 0
            assert result.memory_ids == ["existing-memory"]
            assert kb.dump() == []

    async def test_registered_parser_error_marks_failed_and_continues(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "bad.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        def raise_boom(*_args: object, **_kwargs: object) -> list[object]:
            raise RuntimeError("boom")

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", raise_boom)

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-3",
                original_filename="bad.pdf",
                stored_path=str(path),
                content_type="application/pdf",
                byte_size=path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
                document_analyzer=FailingAnalyzer(),
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "failed"
            assert updated.error == "boom"
            assert result.ingested_files == 0
            assert result.ingested_chunks == 0
            assert result.memory_ids == []
            assert kb.dump() == []

    async def test_registered_kb_remember_error_marks_failed_and_continues(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "stored.txt"
        path.write_text("registered content")

        class FailingKB(FakeKB):
            async def remember(self, *_args: object, **_kwargs: object) -> str:
                raise RuntimeError("kb down")

        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-4",
                original_filename="stored.txt",
                stored_path=str(path),
                content_type="text/plain",
                byte_size=path.stat().st_size,
            )

            result = await ingest_registered_files(
                FailingKB(),
                registry,
                [RegisteredIngestFile(record=record, is_duplicate=is_duplicate)],
            )

            updated = registry.get_by_id(record.document_id)
            assert updated is not None
            assert updated.status == "failed"
            assert updated.error == "kb down"
            assert result.ingested_files == 0
            assert result.ingested_chunks == 0
            assert result.memory_ids == []

    async def test_registered_converter_failure_marks_failed_and_continues_batch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dwg_path = tmp_path / "north.dwg"
        dwg_path.write_bytes(b"dwg body")
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("batch text")
        converted_dir = tmp_path / "converted"
        converted_path = converted_dir / "north.pdf"
        kb = FakeKB()

        def convert(source_path: str) -> ConversionResult:
            assert source_path == str(dwg_path)
            return ConversionResult(
                success=False,
                status="timeout",
                output_path=str(converted_path),
                warnings=("converter_timeout",),
                error="converter timed out after 1s",
                diagnostics={"fake": True, "source_path": source_path},
                command_exit_code=None,
                timeout_seconds=1,
                source_extension=".dwg",
            )

        converter = RecordingEngineeringConverter(convert)

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            assert document_id is not None
            if parser_path == str(txt_path):
                assert source == "notes.txt"
                return [
                    DocumentElement(
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                        page=1,
                        element_type="paragraph",
                        extraction_mode="text",
                        content="parsed batch text",
                    )
                ]
            raise AssertionError(f"unexpected parse target: {parser_path}")

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        async with lifespan_document_registry(":memory:") as registry:
            dwg_record, _ = registry.register_or_get(
                "hash-converter-timeout",
                original_filename="north.dwg",
                stored_path=str(dwg_path),
                content_type="application/acad",
                byte_size=dwg_path.stat().st_size,
            )
            txt_record, _ = registry.register_or_get(
                "hash-batch-text",
                original_filename="notes.txt",
                stored_path=str(txt_path),
                content_type="text/plain",
                byte_size=txt_path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [
                    RegisteredIngestFile(record=dwg_record, is_duplicate=False),
                    RegisteredIngestFile(record=txt_record, is_duplicate=False),
                ],
                engineering_converter=converter,
                engineering_converter_output_dir=str(converted_dir),
            )

            updated_dwg = registry.get_by_id(dwg_record.document_id)
            assert updated_dwg is not None
            assert updated_dwg.status == "failed"
            assert updated_dwg.error == "converter timed out after 1s"
            assert updated_dwg.memory_ids == []

            updated_txt = registry.get_by_id(txt_record.document_id)
            assert updated_txt is not None
            assert updated_txt.status == "indexed"
            assert updated_txt.error is None
            assert len(updated_txt.memory_ids) == 1

            assert result.ingested_files == 1
            assert result.ingested_chunks == 1
            assert len(result.memory_ids) == 1
            assert converter.calls == [str(dwg_path)]
            assert len(kb.dump()) == 1

    async def test_registered_converter_extractor_failure_marks_failed_and_continues_batch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dwg_path = tmp_path / "north.dwg"
        dwg_path.write_bytes(b"dwg body")
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("batch text")
        converted_dir = tmp_path / "converted"
        converted_path = converted_dir / "north.pdf"
        kb = FakeKB()

        def convert(source_path: str) -> ConversionResult:
            assert source_path == str(dwg_path)
            converted_path.parent.mkdir(parents=True, exist_ok=True)
            converted_path.write_bytes(b"%PDF-1.7\n")
            return ConversionResult(
                success=True,
                status="success",
                output_path=str(converted_path),
                warnings=("converter_note",),
                error=None,
                diagnostics={"fake": True, "source_path": source_path},
                command_exit_code=0,
                timeout_seconds=30,
                source_extension=".dwg",
            )

        def fake_extract_converted_drawing(
            path: str,
            *,
            source: str,
            document_id: str | None = None,
            source_path: str | None = None,
            conversion: ConversionResult | None = None,
        ) -> list[DocumentElement]:
            assert path == str(converted_path)
            assert source == "north.dwg"
            assert document_id is not None
            assert source_path == str(dwg_path)
            assert conversion is not None
            assert conversion.success is True
            assert conversion.status == "success"
            assert conversion.output_path == str(converted_path)
            raise RuntimeError("drawing extraction failed")

        converter = RecordingEngineeringConverter(convert)
        monkeypatch.setattr(
            ingestion_module, "extract_converted_drawing", fake_extract_converted_drawing
        )

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            assert document_id is not None
            if parser_path == str(txt_path):
                assert source == "notes.txt"
                return [
                    DocumentElement(
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                        page=1,
                        element_type="paragraph",
                        extraction_mode="text",
                        content="parsed batch text",
                    )
                ]
            raise AssertionError(f"unexpected parse target: {parser_path}")

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        async with lifespan_document_registry(":memory:") as registry:
            dwg_record, _ = registry.register_or_get(
                "hash-converted-extractor-failure",
                original_filename="north.dwg",
                stored_path=str(dwg_path),
                content_type="application/acad",
                byte_size=dwg_path.stat().st_size,
            )
            txt_record, _ = registry.register_or_get(
                "hash-batch-text",
                original_filename="notes.txt",
                stored_path=str(txt_path),
                content_type="text/plain",
                byte_size=txt_path.stat().st_size,
            )

            result = await ingest_registered_files(
                kb,
                registry,
                [
                    RegisteredIngestFile(record=dwg_record, is_duplicate=False),
                    RegisteredIngestFile(record=txt_record, is_duplicate=False),
                ],
                engineering_converter=converter,
                engineering_converter_output_dir=str(converted_dir),
            )

            updated_dwg = registry.get_by_id(dwg_record.document_id)
            assert updated_dwg is not None
            assert updated_dwg.status == "failed"
            assert updated_dwg.error == "drawing extraction failed"
            assert updated_dwg.memory_ids == []

            updated_txt = registry.get_by_id(txt_record.document_id)
            assert updated_txt is not None
            assert updated_txt.status == "indexed"
            assert updated_txt.error is None
            assert len(updated_txt.memory_ids) == 1

            assert result.ingested_files == 1
            assert result.ingested_chunks == 1
            assert len(result.memory_ids) == 1
            assert converter.calls == [str(dwg_path)]
            assert len(kb.dump()) == 1


class TestIngestDirectory:
    async def test_ingests_text_extensions_through_classifier(
        self,
        tmp_path: Path,
    ) -> None:
        txt_body = b"hello"
        md_body = b"world"
        bin_body = b"\x00\x01\x02"
        (tmp_path / "a.txt").write_bytes(txt_body)
        (tmp_path / "b.md").write_bytes(md_body)
        (tmp_path / "c.bin").write_bytes(bin_body)
        kb = FakeKB()

        async with lifespan_document_registry(":memory:") as registry:
            result = await ingest_directory(kb, registry, str(tmp_path))

            assert result.ingested_files == 2
            assert result.ingested_chunks == 2
            assert len(kb.dump()) == 2

            text_record = registry.get_by_hash(hashlib.sha256(txt_body).hexdigest())
            assert text_record is not None
            assert text_record.original_filename == "a.txt"
            assert text_record.status == "indexed"
            assert text_record.error is None
            assert len(text_record.memory_ids) == 1

            md_record = registry.get_by_hash(hashlib.sha256(md_body).hexdigest())
            assert md_record is not None
            assert md_record.original_filename == "b.md"
            assert md_record.status == "indexed"
            assert md_record.error is None
            assert len(md_record.memory_ids) == 1

            bin_record = registry.get_by_hash(hashlib.sha256(bin_body).hexdigest())
            assert bin_record is not None
            assert bin_record.original_filename == "c.bin"
            assert bin_record.status == "skipped"
            assert bin_record.error == "unsupported_extension"
            assert bin_record.memory_ids == []

    async def test_recursive_folder_ingestion_classifies_engineering_and_text_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        top_body = b"top level text"
        pdf_body = b"%PDF-1.7\nplan"
        dwg_body = b"dwg body"
        archive_body = b"old archived text"
        bin_body = b"\x00\x01\x02\x03"
        hidden_body = b"hidden content"

        nested_dir = tmp_path / "nested"
        nested_dir.mkdir()
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()

        xlsx_path = nested_dir / "sheet.xlsx"
        workbook = Workbook()
        workbook.active.title = "Loads"
        workbook.active["A1"] = "Folder workbook"
        workbook.save(xlsx_path)
        xlsx_body = xlsx_path.read_bytes()

        (tmp_path / "top.txt").write_bytes(top_body)
        (nested_dir / "plan.pdf").write_bytes(pdf_body)
        (nested_dir / "north.dwg").write_bytes(dwg_body)
        (archive_dir / "old.txt").write_bytes(archive_body)
        (tmp_path / "mystery.bin").write_bytes(bin_body)
        (hidden_dir / "ignored.txt").write_bytes(hidden_body)

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            assert document_id is not None
            if parser_path == str(xlsx_path):
                assert source == "sheet.xlsx"
                return ingestion_module.parsers.parse_xlsx(
                    parser_path,
                    source=source,
                    document_id=document_id,
                )
            if parser_path == str(nested_dir / "plan.pdf"):
                assert source == "plan.pdf"
                return [
                    DocumentElement(
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                        page=1,
                        element_type="paragraph",
                        extraction_mode="pdf_text",
                        content="parsed plan",
                    )
                ]
            if parser_path == str(tmp_path / "top.txt"):
                assert source == "top.txt"
                return [
                    DocumentElement(
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                        element_type="paragraph",
                        extraction_mode="text",
                        content="parsed top",
                    )
                ]
            raise AssertionError(f"unexpected parse target: {parser_path}")

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        kb = FakeKB()
        async with lifespan_document_registry(":memory:") as registry:
            result = await ingest_directory(kb, registry, str(tmp_path))

            assert result.ingested_files == 3
            assert result.ingested_chunks == 5
            assert len(kb.dump()) == 5

            top_record = registry.get_by_hash(hashlib.sha256(top_body).hexdigest())
            assert top_record is not None
            assert top_record.status == "indexed"
            assert top_record.error is None
            assert top_record.original_filename == "top.txt"
            assert Path(top_record.stored_path).parent == tmp_path

            pdf_record = registry.get_by_hash(hashlib.sha256(pdf_body).hexdigest())
            assert pdf_record is not None
            assert pdf_record.status == "indexed"
            assert pdf_record.error is None
            assert pdf_record.original_filename == "plan.pdf"
            assert Path(pdf_record.stored_path).parent == nested_dir

            xlsx_record = registry.get_by_hash(hashlib.sha256(xlsx_body).hexdigest())
            assert xlsx_record is not None
            assert xlsx_record.status == "indexed"
            assert xlsx_record.error is None
            assert xlsx_record.original_filename == "sheet.xlsx"
            assert Path(xlsx_record.stored_path).parent == nested_dir
            assert len(xlsx_record.memory_ids) == 3

            dwg_record = registry.get_by_hash(hashlib.sha256(dwg_body).hexdigest())
            assert dwg_record is not None
            assert dwg_record.status == "skipped"
            assert dwg_record.error == "missing_configuration"
            assert dwg_record.original_filename == "north.dwg"
            assert Path(dwg_record.stored_path).parent == nested_dir

            archive_record = registry.get_by_hash(hashlib.sha256(archive_body).hexdigest())
            assert archive_record is not None
            assert archive_record.status == "skipped"
            assert archive_record.error == "backup_or_temp"
            assert archive_record.original_filename == "old.txt"
            assert Path(archive_record.stored_path).parent == archive_dir

            bin_record = registry.get_by_hash(hashlib.sha256(bin_body).hexdigest())
            assert bin_record is not None
            assert bin_record.status == "skipped"
            assert bin_record.error == "unsupported_extension"
            assert bin_record.original_filename == "mystery.bin"
            assert Path(bin_record.stored_path).parent == tmp_path

            hidden_record = registry.get_by_hash(hashlib.sha256(hidden_body).hexdigest())
            assert hidden_record is None

    async def test_repeated_text_content_in_tree_deduplicates_to_one_registry_row_and_memory(
        self,
        tmp_path: Path,
    ) -> None:
        body = b"duplicate tree content"
        first_path = tmp_path / "first.txt"
        nested_dir = tmp_path / "nested"
        nested_dir.mkdir()
        second_path = nested_dir / "second.txt"
        first_path.write_bytes(body)
        second_path.write_bytes(body)
        kb = FakeKB()

        async with lifespan_document_registry(":memory:") as registry:
            result = await ingest_directory(kb, registry, str(tmp_path))

            assert result.ingested_files == 1
            assert result.ingested_chunks == 1
            assert len(result.memory_ids) == 2
            assert result.memory_ids[0] == result.memory_ids[1]
            assert len(kb.dump()) == 1

            record = registry.get_by_hash(hashlib.sha256(body).hexdigest())
            assert record is not None
            assert record.status == "indexed"
            assert record.error is None
            assert record.original_filename == "first.txt"
            assert record.stored_path == str(first_path)
            assert record.memory_ids == [result.memory_ids[0]]

    async def test_ingest_directory_threads_document_analyzer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "chart.pdf"
        path.write_bytes(b"%PDF-1.7\n")
        kb = FakeKB()

        chart_element = visual_element_from_summary(
            "North span load chart",
            element_type="chart",
            source=path.name,
            document_id=None,
            path=str(path),
            page=2,
            confidence=0.72,
            warnings=("parser_visual_hint",),
            metadata={"captured_by": "fake-parser", "chart_index": 11},
        )
        assert chart_element is not None
        analyzer = VisualOnlyAnalyzer(_enriched_chart_element)

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            return [
                replace(
                    chart_element,
                    document_id=document_id,
                    source=source,
                    path=parser_path,
                )
            ]

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        async with lifespan_document_registry(":memory:") as registry:
            result = await ingest_directory(
                kb,
                registry,
                str(tmp_path),
                document_analyzer=analyzer,
            )

            assert result.ingested_files == 1
            assert result.ingested_chunks == 1

            record = registry.get_by_hash(hashlib.sha256(b"%PDF-1.7\n").hexdigest())
            assert record is not None
            assert record.status == "indexed"
            assert record.error is None
            assert analyzer.calls == [[replace(chart_element, document_id=record.document_id)]]

            memories = kb.dump()
            assert len(memories) == 1
            assert memories[0]["metadata"]["analysis_status"] == "enriched"
            assert memories[0]["metadata"]["analysis_provider"] == "fake-openai"

    async def test_ingest_directory_uses_engineering_converter_for_cad_exports(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        top_body = b"top level text"
        pdf_body = b"%PDF-1.7\nplan"
        dwg_body = b"dwg body"
        archive_body = b"old archived text"
        bin_body = b"\x00\x01\x02\x03"
        hidden_body = b"hidden content"

        nested_dir = tmp_path / "nested"
        nested_dir.mkdir()
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()

        xlsx_path = nested_dir / "sheet.xlsx"
        workbook = Workbook()
        workbook.active.title = "Loads"
        workbook.active["A1"] = "Folder workbook"
        workbook.save(xlsx_path)
        xlsx_body = xlsx_path.read_bytes()

        converted_dir = tmp_path / "converted"
        converted_path = converted_dir / "north.pdf"

        (tmp_path / "top.txt").write_bytes(top_body)
        (nested_dir / "plan.pdf").write_bytes(pdf_body)
        (nested_dir / "north.dwg").write_bytes(dwg_body)
        (archive_dir / "old.txt").write_bytes(archive_body)
        (tmp_path / "mystery.bin").write_bytes(bin_body)
        (hidden_dir / "ignored.txt").write_bytes(hidden_body)

        def convert(source_path: str) -> ConversionResult:
            assert source_path == str(nested_dir / "north.dwg")
            converted_path.parent.mkdir(parents=True, exist_ok=True)
            converted_path.write_bytes(b"%PDF-1.7\n")
            return ConversionResult(
                success=True,
                status="success",
                output_path=str(converted_path),
                warnings=("converter_note",),
                error=None,
                diagnostics={
                    "fake": True,
                    "source_path": source_path,
                    "layers": ["A-WALL"],
                    "views": ["Level 1"],
                    "entities": ["Door 7"],
                    "stdout": "converter stdout should stay hidden",
                },
                command_exit_code=0,
                timeout_seconds=30,
                source_extension=".dwg",
            )

        converter = RecordingEngineeringConverter(convert)

        class FakePage:
            def __init__(self, text: str | None) -> None:
                self._text = text

            def extract_text(self) -> str | None:
                return self._text

        class FakePdfReader:
            def __init__(self, reader_path: str) -> None:
                assert reader_path == str(converted_path)
                self.pages = [
                    FakePage("Label: North entry\nDimension: 12'-0\""),
                    FakePage(
                        "Layer: A-WALL\n"
                        "View: Level 1\n"
                        "Entity: Door 7\n"
                        "Revision: R3\n"
                        "Note: verify field"
                    ),
                ]

        monkeypatch.setattr(converted_drawing_elements, "PdfReader", FakePdfReader)

        def fake_parse_document(
            parser_path: str,
            *,
            source: str,
            document_id: str | None = None,
        ) -> list[DocumentElement]:
            assert document_id is not None
            if parser_path == str(xlsx_path):
                assert source == "sheet.xlsx"
                return ingestion_module.parsers.parse_xlsx(
                    parser_path,
                    source=source,
                    document_id=document_id,
                )
            if parser_path == str(nested_dir / "plan.pdf"):
                assert source == "plan.pdf"
                return [
                    DocumentElement(
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                        page=1,
                        element_type="paragraph",
                        extraction_mode="pdf_text",
                        content="parsed plan",
                    )
                ]
            if parser_path == str(tmp_path / "top.txt"):
                assert source == "top.txt"
                return [
                    DocumentElement(
                        document_id=document_id,
                        source=source,
                        path=parser_path,
                        element_type="paragraph",
                        extraction_mode="text",
                        content="parsed top",
                    )
                ]
            if parser_path == str(converted_path):
                raise AssertionError("parse_document should not run for converted drawings")
            raise AssertionError(f"unexpected parse target: {parser_path}")

        monkeypatch.setattr(ingestion_module.parsers, "parse_document", fake_parse_document)

        analyzer = VisualOnlyAnalyzer(lambda element: element)
        kb = FakeKB()
        async with lifespan_document_registry(":memory:") as registry:
            result = await ingest_directory(
                kb,
                registry,
                str(tmp_path),
                document_analyzer=analyzer,
                engineering_converter=converter,
                engineering_converter_output_dir=str(converted_dir),
            )

            assert result.ingested_files == 4
            assert result.ingested_chunks == len(result.memory_ids)
            assert len(kb.dump()) == len(result.memory_ids)
            assert converter.calls == [str(nested_dir / "north.dwg")]
            assert len(analyzer.calls) == 1
            assert len(analyzer.calls[0]) == 1
            assert analyzer.calls[0][0].element_type == "drawing"
            assert analyzer.calls[0][0].extraction_mode == "converted_drawing_text_summary"

            top_record = registry.get_by_hash(hashlib.sha256(top_body).hexdigest())
            assert top_record is not None
            assert top_record.status == "indexed"
            assert top_record.error is None
            assert top_record.original_filename == "top.txt"
            assert Path(top_record.stored_path).parent == tmp_path

            pdf_record = registry.get_by_hash(hashlib.sha256(pdf_body).hexdigest())
            assert pdf_record is not None
            assert pdf_record.status == "indexed"
            assert pdf_record.error is None
            assert pdf_record.original_filename == "plan.pdf"
            assert Path(pdf_record.stored_path).parent == nested_dir

            xlsx_record = registry.get_by_hash(hashlib.sha256(xlsx_body).hexdigest())
            assert xlsx_record is not None
            assert xlsx_record.status == "indexed"
            assert xlsx_record.error is None
            assert xlsx_record.original_filename == "sheet.xlsx"
            assert Path(xlsx_record.stored_path).parent == nested_dir
            assert len(xlsx_record.memory_ids) == 3

            dwg_record = registry.get_by_hash(hashlib.sha256(dwg_body).hexdigest())
            assert dwg_record is not None
            assert dwg_record.status == "indexed"
            assert dwg_record.error is None
            assert dwg_record.original_filename == "north.dwg"
            assert Path(dwg_record.stored_path).parent == nested_dir
            assert len(dwg_record.memory_ids) == 8

            archive_record = registry.get_by_hash(hashlib.sha256(archive_body).hexdigest())
            assert archive_record is not None
            assert archive_record.status == "skipped"
            assert archive_record.error == "backup_or_temp"
            assert archive_record.original_filename == "old.txt"
            assert Path(archive_record.stored_path).parent == archive_dir

            bin_record = registry.get_by_hash(hashlib.sha256(bin_body).hexdigest())
            assert bin_record is not None
            assert bin_record.status == "skipped"
            assert bin_record.error == "unsupported_extension"
            assert bin_record.original_filename == "mystery.bin"
            assert Path(bin_record.stored_path).parent == tmp_path

            hidden_record = registry.get_by_hash(hashlib.sha256(hidden_body).hexdigest())
            assert hidden_record is None

            memories = kb.dump()
            dwg_memories = [
                record for record in memories if record["metadata"]["source"] == "north.dwg"
            ]
            assert len(dwg_memories) == 8

            dwg_summary = next(
                record
                for record in dwg_memories
                if record["metadata"]["extraction_mode"] == "converted_drawing_text_summary"
            )
            assert dwg_summary["content"].startswith(
                "[source=north.dwg; element=drawing; extraction=converted_drawing_text_summary; "
                "confidence=1.0; warnings=converter_note]"
            )
            assert "Source CAD path: " + str(nested_dir / "north.dwg") in dwg_summary["content"]
            assert f"Derived artifact path: {converted_path}" in dwg_summary["content"]
            assert "Conversion status: success" in dwg_summary["content"]
            assert "Conversion source extension: .dwg" in dwg_summary["content"]
            assert "Artifact extension: .pdf" in dwg_summary["content"]
            assert "Text layer mode: exact" in dwg_summary["content"]
            assert "Exact facts: 7" in dwg_summary["content"]
            assert (
                "Fact kinds: label, dimension, layer, entity_view, revision_marker, visible_note"
                in dwg_summary["content"]
            )
            assert "Conversion warnings: converter_note" in dwg_summary["content"]
            assert "Layers: A-WALL" in dwg_summary["content"]
            assert "Views: Level 1" in dwg_summary["content"]
            assert "Entities: Door 7" in dwg_summary["content"]
            assert dwg_summary["metadata"]["source_cad_file"] == "north.dwg"
            assert dwg_summary["metadata"]["source_cad_path"] == str(nested_dir / "north.dwg")
            assert dwg_summary["metadata"]["derived_artifact_path"] == str(converted_path)
            assert dwg_summary["metadata"]["conversion_status"] == "success"
            assert dwg_summary["metadata"]["conversion_warnings"] == ["converter_note"]
            assert dwg_summary["metadata"]["drawing_fact_count"] == 7
            assert dwg_summary["metadata"]["drawing_fact_types"] == [
                "label",
                "dimension",
                "layer",
                "entity_view",
                "revision_marker",
                "visible_note",
            ]
            assert dwg_summary["metadata"]["drawing_layers"] == ["A-WALL"]
            assert dwg_summary["metadata"]["drawing_views"] == ["Level 1"]
            assert dwg_summary["metadata"]["drawing_entities"] == ["Door 7"]
            assert "stdout" not in dwg_summary["metadata"]["conversion_diagnostics"]

            dwg_fact_records = [
                record
                for record in dwg_memories
                if record["metadata"]["extraction_mode"] == "converted_drawing_text_fact"
            ]
            assert len(dwg_fact_records) == 7
            assert [record["metadata"]["drawing_fact_type"] for record in dwg_fact_records] == [
                "label",
                "dimension",
                "layer",
                "entity_view",
                "entity_view",
                "revision_marker",
                "visible_note",
            ]
            assert [
                record["metadata"]["drawing_fact_subtype"] for record in dwg_fact_records[3:5]
            ] == [
                "view",
                "entity",
            ]
            assert all(
                record["metadata"]["source_cad_path"] == str(nested_dir / "north.dwg")
                for record in dwg_fact_records
            )
            assert all(
                record["metadata"]["derived_artifact_path"] == str(converted_path)
                for record in dwg_fact_records
            )

    async def test_missing_directory_is_a_noop(self, tmp_path: Path) -> None:
        kb = FakeKB()
        async with lifespan_document_registry(":memory:") as registry:
            result = await ingest_directory(kb, registry, str(tmp_path / "nope"))
            assert result.ingested_files == 0
            assert result.ingested_chunks == 0
