"""Tests for the document ingestion pipeline (text + markdown loaders, chunker)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from app.kb.fake import FakeKB
from app.services import ingestion as ingestion_module
from app.services.document_analysis import OPENAI_ENRICHMENT_FAILED_WARNING
from app.services.document_elements import DocumentElement
from app.services.document_registry import lifespan_document_registry
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


class TestIngestDirectory:
    async def test_ingests_supported_extensions_only(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        (tmp_path / "c.bin").write_bytes(b"\x00\x01\x02")
        kb = FakeKB()
        result = await ingest_directory(kb, str(tmp_path))
        assert result.ingested_files == 2

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

        result = await ingest_directory(
            kb,
            str(tmp_path),
            document_analyzer=analyzer,
        )

        assert result.ingested_files == 1
        assert result.ingested_chunks == 1
        assert analyzer.calls == [[chart_element]]

        memories = kb.dump()
        assert len(memories) == 1
        assert memories[0]["metadata"]["analysis_status"] == "enriched"
        assert memories[0]["metadata"]["analysis_provider"] == "fake-openai"

    async def test_missing_directory_is_a_noop(self, tmp_path: Path) -> None:
        kb = FakeKB()
        result = await ingest_directory(kb, str(tmp_path / "nope"))
        assert result.ingested_files == 0
