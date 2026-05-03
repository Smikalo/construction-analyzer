"""Tests for the report pipeline state machine and per-session event queue."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import asynccontextmanager

import pytest
from langchain_core.language_models import BaseChatModel

from app.kb.fake import FakeKB
from app.services.document_registry import lifespan_document_registry
from app.services.report_pipeline import (
    BOOTSTRAP_STAGE_NAME,
    DRAFT_REPORT_SECTIONS_STAGE_NAME,
    INVENTORY_SOURCES_STAGE_NAME,
    PLAN_REPORT_SECTIONS_STAGE_NAME,
    REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
    RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
    ReportPipeline,
    ReportPipelineRegistry,
)
from app.services.report_planner import (
    build_general_project_dossier_section_plan,
    build_source_inventory,
)
from app.services.report_sessions import lifespan_report_sessions
from tests._fakes import make_fake_chat_model

EMPTY_DRAFT_PAYLOAD = json.dumps({"paragraphs": []}, ensure_ascii=False)


@asynccontextmanager
async def _pipeline_context(
    *,
    kb: FakeKB | None = None,
    llm_factory: Callable[[], BaseChatModel] | None = None,
):
    active_kb = kb or FakeKB()
    active_llm_factory = llm_factory or (lambda: make_fake_chat_model([EMPTY_DRAFT_PAYLOAD]))
    async with lifespan_report_sessions(":memory:") as store:
        async with lifespan_document_registry(":memory:") as document_registry:
            yield (
                store,
                document_registry,
                ReportPipeline(
                    store,
                    document_registry,
                    kb=active_kb,
                    llm_factory=active_llm_factory,
                    registry_pipeline=ReportPipelineRegistry(),
                ),
            )


def _seed_report_documents(registry) -> None:
    indexed_record, _ = registry.register_or_get(
        "hash-indexed",
        document_id="doc-indexed",
        original_filename="site-report.pdf",
        stored_path="/app/data/documents/doc-indexed.pdf",
        content_type="application/pdf",
        byte_size=123,
        uploaded_at="2026-05-01T10:00:00+00:00",
    )
    registry.update_status(indexed_record.document_id, "indexed")

    failed_record, _ = registry.register_or_get(
        "hash-failed",
        document_id="doc-failed",
        original_filename="calc.xlsx",
        stored_path="/app/data/documents/doc-failed.xlsx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        byte_size=456,
        uploaded_at="2026-05-01T11:00:00+00:00",
    )
    registry.update_status(failed_record.document_id, "failed", error="workbook parser failed")

    skipped_record, _ = registry.register_or_get(
        "hash-skipped",
        document_id="doc-skipped",
        original_filename="photo.png",
        stored_path="/app/data/documents/doc-skipped.png",
        content_type="image/png",
        byte_size=789,
        uploaded_at="2026-05-01T12:00:00+00:00",
    )
    registry.mark_skipped(skipped_record.document_id, reason="image_extractor_pending")


class TestReportPipeline:
    async def test_bootstrap_emits_stage_started_then_gate_opened(self) -> None:
        async with _pipeline_context() as (store, _document_registry, pipeline):
            session = await pipeline.start("session-1")
            chunks = _drain_queue(pipeline.events("session-1"))

            assert session.status == "blocked"
            assert session.current_stage == BOOTSTRAP_STAGE_NAME
            assert [chunk.type for chunk in chunks] == [
                "report_card",
                "report_gate",
                "report_card",
            ]
            assert [chunk.payload["kind"] for chunk in (chunks[0], chunks[2])] == [
                "stage_started",
                "stage_completed",
            ]
            assert chunks[1].payload["gate_id"] == REPORT_TEMPLATE_CONFIRMATION_GATE_ID
            assert chunks[1].payload["status"] == "open"
            assert store.list_logs("session-1")[0].message == "Report bootstrap stage started"
            assert [stage.name for stage in store.list_stages("session-1")] == [
                BOOTSTRAP_STAGE_NAME,
            ]
            assert store.list_stages("session-1")[0].status == "complete"

    async def test_general_project_dossier_advances_to_section_planning(self) -> None:
        async with _pipeline_context() as (store, _document_registry, pipeline):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate(
                "session-1",
                {"choice": "general_project_dossier"},
            )
            chunks = _drain_queue(pipeline.events("session-1"))

            assert session.status == "active"
            assert session.current_stage == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert [chunk.type for chunk in chunks] == [
                "report_card",
                "report_card",
                "report_card",
                "report_card",
                "report_card",
                "report_card",
                "report_card",
                "report_card",
                "report_card",
            ]
            assert [chunk.payload["kind"] for chunk in chunks] == [
                "gate_closed",
                "stage_started",
                "stage_completed",
                "stage_started",
                "stage_completed",
                "stage_started",
                "stage_completed",
                "stage_started",
                "stage_completed",
            ]
            assert chunks[0].payload["payload"] == {
                "gate_id": REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
                "choice": "general_project_dossier",
            }
            assert chunks[1].payload["stage_name"] == INVENTORY_SOURCES_STAGE_NAME
            assert chunks[3].payload["stage_name"] == PLAN_REPORT_SECTIONS_STAGE_NAME
            assert chunks[5].payload["stage_name"] == RETRIEVE_SECTION_EVIDENCE_STAGE_NAME
            assert chunks[7].payload["stage_name"] == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert [stage.name for stage in store.list_stages("session-1")] == [
                BOOTSTRAP_STAGE_NAME,
                INVENTORY_SOURCES_STAGE_NAME,
                PLAN_REPORT_SECTIONS_STAGE_NAME,
                RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
                DRAFT_REPORT_SECTIONS_STAGE_NAME,
            ]
            assert [stage.status for stage in store.list_stages("session-1")] == [
                "complete",
                "complete",
                "complete",
                "complete",
                "complete",
            ]

            logs = store.list_logs("session-1")
            lifecycle_messages = [
                log.message
                for log in logs
                if log.message
                in {
                    "Inventory sources stage started",
                    "Inventory sources stage completed",
                    "Section planning stage started",
                    "Section planning stage completed",
                    "Section evidence retrieval started",
                    "Section evidence retrieval completed",
                    "Report section drafting started",
                    "Report section drafting completed",
                }
            ]
            assert lifecycle_messages == [
                "Inventory sources stage started",
                "Inventory sources stage completed",
                "Section planning stage started",
                "Section planning stage completed",
                "Section evidence retrieval started",
                "Section evidence retrieval completed",
                "Report section drafting started",
                "Report section drafting completed",
            ]
            assert next(
                log for log in logs if log.message == "Source inventory snapshot recorded"
            ).payload == {
                "stage_name": INVENTORY_SOURCES_STAGE_NAME,
                "indexed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
            }
            assert next(log for log in logs if log.message == "Section plan recorded").payload == {
                "stage_name": PLAN_REPORT_SECTIONS_STAGE_NAME,
                "section_count": 14,
                "active_section_count": 11,
            }
            assert next(
                log for log in logs if log.message == "Section evidence retrieval completed"
            ).payload == {
                "stage_name": RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
                "sections": [
                    {"id": "deckblatt", "total_hit_count": 0},
                    {"id": "aufgabenstellung", "total_hit_count": 0},
                    {"id": "grundlagen", "total_hit_count": 0},
                    {"id": "projekt_beschreibung", "total_hit_count": 0},
                    {"id": "normen", "total_hit_count": 0},
                    {"id": "plaene", "total_hit_count": 0},
                    {"id": "berechnungen", "total_hit_count": 0},
                    {"id": "ergebnisse", "total_hit_count": 0},
                    {"id": "unsicherheiten", "total_hit_count": 0},
                    {"id": "anlagenverzeichnis", "total_hit_count": 0},
                    {"id": "quellennachweise", "total_hit_count": 0},
                ],
            }
            assert next(
                log for log in logs if log.message == "Report section drafting completed"
            ).payload == {
                "stage_name": DRAFT_REPORT_SECTIONS_STAGE_NAME,
                "sections": [
                    {"id": "deckblatt", "paragraph_count": 0, "no_evidence": True},
                    {"id": "aufgabenstellung", "paragraph_count": 0, "no_evidence": True},
                    {"id": "grundlagen", "paragraph_count": 0, "no_evidence": True},
                    {"id": "projekt_beschreibung", "paragraph_count": 0, "no_evidence": True},
                    {"id": "normen", "paragraph_count": 0, "no_evidence": True},
                    {"id": "plaene", "paragraph_count": 0, "no_evidence": True},
                    {"id": "berechnungen", "paragraph_count": 0, "no_evidence": True},
                    {"id": "ergebnisse", "paragraph_count": 0, "no_evidence": True},
                    {"id": "unsicherheiten", "paragraph_count": 0, "no_evidence": True},
                    {"id": "anlagenverzeichnis", "paragraph_count": 0, "no_evidence": True},
                    {"id": "quellennachweise", "paragraph_count": 0, "no_evidence": True},
                ],
            }

    async def test_inventory_and_section_plan_artifacts_persisted(self) -> None:
        async with _pipeline_context() as (store, document_registry, pipeline):
            _seed_report_documents(document_registry)

            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate(
                "session-1",
                {"choice": "general_project_dossier"},
            )
            _drain_queue(pipeline.events("session-1"))

            artifacts = store.list_artifacts("session-1")
            section_plan_artifact = next(
                artifact for artifact in artifacts if artifact.kind == "section_plan"
            )
            retrieval_artifact = next(
                artifact for artifact in artifacts if artifact.kind == "other"
            )
            active_section_count = sum(
                1 for section in section_plan_artifact.content["sections"] if section["active"]
            )

            assert session.status == "active"
            assert session.current_stage == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert [
                artifact.kind for artifact in artifacts if artifact.kind != "paragraph_citations"
            ] == [
                "source_inventory_snapshot",
                "section_plan",
                "other",
            ]
            assert artifacts[0].content["totals"] == {
                "indexed": 1,
                "skipped": 1,
                "failed": 1,
                "uploaded": 0,
                "processing": 0,
                "total": 3,
            }
            assert artifacts[1].content["template_id"] == "general_project_dossier"
            assert len(section_plan_artifact.content["sections"]) == 14
            assert retrieval_artifact.content["kind"] == "retrieval_manifest"
            paragraph_artifacts = [
                artifact for artifact in artifacts if artifact.kind == "paragraph_citations"
            ]
            assert len(paragraph_artifacts) == active_section_count
            assert all(artifact.content["no_evidence"] is True for artifact in paragraph_artifacts)

    async def test_retrieve_section_evidence_persists_manifest_artifact(self) -> None:
        kb = FakeKB()
        llm = make_fake_chat_model([EMPTY_DRAFT_PAYLOAD])
        memory_id, section_entry = await _seed_recalled_memory(kb)

        async with _pipeline_context(kb=kb, llm_factory=lambda: llm) as (
            store,
            _document_registry,
            pipeline,
        ):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate(
                "session-1",
                {"choice": "general_project_dossier"},
            )
            _drain_queue(pipeline.events("session-1"))

            artifacts = store.list_artifacts("session-1")
            retrieval_artifacts = [artifact for artifact in artifacts if artifact.kind == "other"]
            retrieval_artifact = retrieval_artifacts[0]
            retrieval_section = next(
                section
                for section in retrieval_artifact.content["sections"]
                if section["id"] == section_entry["id"]
            )
            manifest_section_ids = [
                section["id"] for section in retrieval_artifact.content["sections"]
            ]

            assert session.status == "active"
            assert session.current_stage == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert llm.call_count == 1
            assert len(retrieval_artifacts) == 1
            assert retrieval_artifact.content["kind"] == "retrieval_manifest"
            assert section_entry["id"] in manifest_section_ids
            assert retrieval_section["total_hit_count"] == 1
            assert retrieval_section["recalled_memories"][0]["id"] == memory_id

    async def test_draft_report_sections_persists_paragraph_citations(self) -> None:
        kb = FakeKB()
        memory_id, section_entry = await _seed_recalled_memory(kb)
        payload = json.dumps(
            {
                "paragraphs": [
                    {
                        "text": f"Die statische Aussage ist belegt. [evidence_id={memory_id}]",
                        "evidence_ids": [memory_id],
                    }
                ]
            },
            ensure_ascii=False,
        )
        llm = make_fake_chat_model([payload])

        async with _pipeline_context(kb=kb, llm_factory=lambda: llm) as (
            store,
            _document_registry,
            pipeline,
        ):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate(
                "session-1",
                {"choice": "general_project_dossier"},
            )
            _drain_queue(pipeline.events("session-1"))

            paragraph_artifacts = [
                artifact
                for artifact in store.list_artifacts("session-1")
                if artifact.kind == "paragraph_citations" and not artifact.content["no_evidence"]
            ]

            assert session.status == "active"
            assert session.current_stage == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert llm.call_count == 1
            assert len(paragraph_artifacts) == 1
            expected_provenance = "[source=report.pdf; page=2; element=paragraph; extraction=text]"
            assert paragraph_artifacts[0].content == {
                "section_id": section_entry["id"],
                "paragraph_index": 1,
                "text": f"Die statische Aussage ist belegt. [evidence_id={memory_id}]",
                "evidence_manifest": [
                    {
                        "memory_id": memory_id,
                        "provenance": expected_provenance,
                    }
                ],
                "no_evidence": False,
            }

    async def test_draft_report_sections_emits_no_evidence_paragraph_for_empty_section(
        self,
    ) -> None:
        kb = FakeKB()
        llm = make_fake_chat_model([EMPTY_DRAFT_PAYLOAD])

        async with _pipeline_context(kb=kb, llm_factory=lambda: llm) as (
            store,
            _document_registry,
            pipeline,
        ):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate(
                "session-1",
                {"choice": "general_project_dossier"},
            )
            _drain_queue(pipeline.events("session-1"))

            artifacts = store.list_artifacts("session-1")
            section_plan_artifact = next(
                artifact for artifact in artifacts if artifact.kind == "section_plan"
            )
            active_section_count = sum(
                1 for section in section_plan_artifact.content["sections"] if section["active"]
            )
            paragraph_artifacts = [
                artifact for artifact in artifacts if artifact.kind == "paragraph_citations"
            ]
            warning_logs = [
                log
                for log in store.list_logs("session-1")
                if log.level == "warning" and log.message.endswith("drafted with no evidence")
            ]

            assert session.status == "active"
            assert session.current_stage == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert llm.call_count == 0
            assert len(paragraph_artifacts) == active_section_count
            assert all(artifact.content["no_evidence"] is True for artifact in paragraph_artifacts)
            assert all(artifact.content["paragraph_index"] == 0 for artifact in paragraph_artifacts)
            assert len(warning_logs) == active_section_count
            assert all(log.payload["no_evidence"] is True for log in warning_logs)

    async def test_inventory_stage_failure_marks_session_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async with _pipeline_context() as (store, document_registry, pipeline):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            def boom() -> list:
                raise RuntimeError("inventory boom")

            monkeypatch.setattr(document_registry, "list_all", boom)

            with pytest.raises(RuntimeError, match="inventory boom"):
                await pipeline.answer_gate(
                    "session-1",
                    {"choice": "general_project_dossier"},
                )

            chunks = _drain_queue(pipeline.events("session-1"))
            session = store.get_session("session-1")
            stages = store.list_stages("session-1")

            assert session is not None
            assert session.status == "failed"
            assert session.current_stage == INVENTORY_SOURCES_STAGE_NAME
            assert session.last_error == "inventory boom"
            assert [chunk.payload["kind"] for chunk in chunks] == [
                "gate_closed",
                "stage_started",
                "failure",
            ]
            assert chunks[-1].payload["stage_name"] == INVENTORY_SOURCES_STAGE_NAME
            assert [stage.name for stage in stages] == [
                BOOTSTRAP_STAGE_NAME,
                INVENTORY_SOURCES_STAGE_NAME,
            ]
            assert stages[1].status == "failed"
            assert stages[1].error == "inventory boom"
            assert store.list_logs("session-1")[-1].level == "error"
            assert store.list_logs("session-1")[-1].message == "Report pipeline failed"

    async def test_draft_stage_failure_marks_session_failed_with_last_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        kb = FakeKB()
        llm = make_fake_chat_model([EMPTY_DRAFT_PAYLOAD])
        await _seed_recalled_memory(kb)

        async def boom(*args, **kwargs):
            raise RuntimeError("draft boom")

        monkeypatch.setattr(type(llm), "ainvoke", boom)
        async with _pipeline_context(kb=kb, llm_factory=lambda: llm) as (
            store,
            _document_registry,
            pipeline,
        ):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            with pytest.raises(RuntimeError, match="draft boom"):
                await pipeline.answer_gate(
                    "session-1",
                    {"choice": "general_project_dossier"},
                )

            chunks = _drain_queue(pipeline.events("session-1"))
            session = store.get_session("session-1")
            stages = store.list_stages("session-1")

            assert session is not None
            assert session.status == "failed"
            assert session.current_stage == DRAFT_REPORT_SECTIONS_STAGE_NAME
            assert session.last_error == "draft boom"
            assert [stage.name for stage in stages] == [
                BOOTSTRAP_STAGE_NAME,
                INVENTORY_SOURCES_STAGE_NAME,
                PLAN_REPORT_SECTIONS_STAGE_NAME,
                RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
                DRAFT_REPORT_SECTIONS_STAGE_NAME,
            ]
            assert stages[-1].status == "failed"
            assert stages[-1].error == "draft boom"
            assert any(
                chunk.payload["kind"] == "failure"
                and chunk.payload["stage_name"] == DRAFT_REPORT_SECTIONS_STAGE_NAME
                for chunk in chunks
            )
            assert store.list_logs("session-1")[-1].level == "error"
            assert store.list_logs("session-1")[-1].message == "Report pipeline failed"

    async def test_cancel_completes_the_session(self) -> None:
        async with _pipeline_context() as (store, _document_registry, pipeline):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate("session-1", {"choice": "cancel"})
            chunks = _drain_queue(pipeline.events("session-1"))

            assert session.status == "complete"
            assert session.current_stage is None
            assert [chunk.payload["kind"] for chunk in chunks] == ["gate_closed"]
            assert store.list_gates("session-1")[0].status == "closed"
            assert [log.message for log in store.list_logs("session-1")][-2:] == [
                "Report template confirmation gate closed",
                "Report session completed",
            ]

    async def test_answering_a_closed_gate_raises_a_clear_error(self) -> None:
        async with _pipeline_context() as (store, _document_registry, pipeline):
            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))
            await pipeline.answer_gate("session-1", {"choice": "cancel"})
            _drain_queue(pipeline.events("session-1"))

            with pytest.raises(RuntimeError, match="already closed"):
                await pipeline.answer_gate(
                    "session-1",
                    {"choice": "general_project_dossier"},
                )

            assert _drain_queue(pipeline.events("session-1")) == []
            assert store.get_session("session-1").status == "complete"

    async def test_restarting_a_blocked_session_replays_the_open_gate(self) -> None:
        async with _pipeline_context() as (store, _document_registry, pipeline):
            await pipeline.start("session-1")
            first_chunks = _drain_queue(pipeline.events("session-1"))
            assert [
                chunk.payload["kind"] for chunk in first_chunks if chunk.type == "report_card"
            ] == [
                "stage_started",
                "stage_completed",
            ]

            session = await pipeline.start("session-1")
            replay_chunks = _drain_queue(pipeline.events("session-1"))

            assert session.status == "blocked"
            assert session.current_stage == BOOTSTRAP_STAGE_NAME
            assert [chunk.type for chunk in replay_chunks] == ["report_gate"]
            assert replay_chunks[0].payload["gate_id"] == REPORT_TEMPLATE_CONFIRMATION_GATE_ID
            assert [stage.name for stage in store.list_stages("session-1")] == [
                BOOTSTRAP_STAGE_NAME,
            ]
            assert len(store.list_logs("session-1")) == 3

    async def test_start_failure_records_last_error_and_emits_failure_card(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async with _pipeline_context() as (store, _document_registry, pipeline):
            def boom(*args, **kwargs):
                raise RuntimeError("boom")

            monkeypatch.setattr(store, "open_gate", boom)

            with pytest.raises(RuntimeError, match="boom"):
                await pipeline.start("session-1")

            chunks = _drain_queue(pipeline.events("session-1"))
            session = store.get_session("session-1")
            stages = store.list_stages("session-1")
            logs = store.list_logs("session-1")

            assert session is not None
            assert session.status == "failed"
            assert session.last_error == "boom"
            assert [chunk.payload["kind"] for chunk in chunks] == ["stage_started", "failure"]
            assert chunks[-1].payload["stage_name"] == BOOTSTRAP_STAGE_NAME
            assert stages[0].status == "failed"
            assert logs[-1].level == "error"
            assert logs[-1].message == "Report pipeline failed"


async def _seed_recalled_memory(
    kb: FakeKB,
    section_id: str = "berechnungen",
) -> tuple[str, dict[str, object]]:
    section = _section_from_plan(section_id)
    provenance_header = "[source=report.pdf; page=2; element=paragraph; extraction=text]"
    memory_id = await kb.remember(
        f"{provenance_header}\nTexte Unterlagen {section['title']} belegt den Nachweis.",
        metadata={
            "document_id": "doc-hit",
            "source": "report.pdf",
        },
    )
    return memory_id, section


def _section_from_plan(section_id: str) -> dict[str, object]:
    plan = build_general_project_dossier_section_plan(build_source_inventory([]))
    return next(section for section in plan["sections"] if section["id"] == section_id)


def _drain_queue(queue: asyncio.Queue) -> list:
    chunks = []
    while True:
        try:
            chunks.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return chunks
