"""Tests for the report pipeline state machine and per-session event queue."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.services.document_registry import lifespan_document_registry
from app.services.report_pipeline import (
    BOOTSTRAP_STAGE_NAME,
    INVENTORY_SOURCES_STAGE_NAME,
    PLAN_REPORT_SECTIONS_STAGE_NAME,
    REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
    ReportPipeline,
    ReportPipelineRegistry,
)
from app.services.report_sessions import lifespan_report_sessions


@asynccontextmanager
async def _pipeline_context():
    async with lifespan_report_sessions(":memory:") as store:
        async with lifespan_document_registry(":memory:") as document_registry:
            yield (
                store,
                document_registry,
                ReportPipeline(store, document_registry, ReportPipelineRegistry()),
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
            assert session.current_stage == PLAN_REPORT_SECTIONS_STAGE_NAME
            assert [chunk.type for chunk in chunks] == [
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
            ]
            assert chunks[0].payload["payload"] == {
                "gate_id": REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
                "choice": "general_project_dossier",
            }
            assert chunks[1].payload["stage_name"] == INVENTORY_SOURCES_STAGE_NAME
            assert chunks[3].payload["stage_name"] == PLAN_REPORT_SECTIONS_STAGE_NAME
            assert [stage.name for stage in store.list_stages("session-1")] == [
                BOOTSTRAP_STAGE_NAME,
                INVENTORY_SOURCES_STAGE_NAME,
                PLAN_REPORT_SECTIONS_STAGE_NAME,
            ]
            assert [stage.status for stage in store.list_stages("session-1")] == [
                "complete",
                "complete",
                "complete",
            ]

            logs = store.list_logs("session-1")
            assert [log.message for log in logs[-6:]] == [
                "Inventory sources stage started",
                "Source inventory snapshot recorded",
                "Inventory sources stage completed",
                "Section planning stage started",
                "Section plan recorded",
                "Section planning stage completed",
            ]
            assert logs[-5].payload == {
                "stage_name": INVENTORY_SOURCES_STAGE_NAME,
                "indexed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
            }
            assert logs[-2].payload == {
                "stage_name": PLAN_REPORT_SECTIONS_STAGE_NAME,
                "section_count": 14,
                "active_section_count": 11,
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

            assert session.status == "active"
            assert session.current_stage == PLAN_REPORT_SECTIONS_STAGE_NAME
            assert [artifact.kind for artifact in artifacts] == [
                "source_inventory_snapshot",
                "section_plan",
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
            assert len(artifacts[1].content["sections"]) == 14

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


def _drain_queue(queue: asyncio.Queue) -> list:
    chunks = []
    while True:
        try:
            chunks.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return chunks
