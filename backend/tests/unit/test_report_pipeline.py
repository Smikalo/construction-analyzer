"""Tests for the report pipeline state machine and per-session event queue."""

from __future__ import annotations

import asyncio

import pytest

from app.services.report_pipeline import (
    AWAITING_INVENTORY_STAGE_NAME,
    BOOTSTRAP_STAGE_NAME,
    REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
    ReportPipeline,
    ReportPipelineRegistry,
)
from app.services.report_sessions import lifespan_report_sessions


class TestReportPipeline:
    async def test_bootstrap_emits_stage_started_then_gate_opened(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            pipeline = ReportPipeline(store, ReportPipelineRegistry())

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
            assert store.list_logs("session-1")[0].message == ("Report bootstrap stage started")
            assert [stage.name for stage in store.list_stages("session-1")] == [
                BOOTSTRAP_STAGE_NAME,
            ]
            assert store.list_stages("session-1")[0].status == "complete"

    async def test_general_project_dossier_advances_to_awaiting_inventory(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            pipeline = ReportPipeline(store, ReportPipelineRegistry())

            await pipeline.start("session-1")
            _drain_queue(pipeline.events("session-1"))

            session = await pipeline.answer_gate(
                "session-1",
                {"choice": "general_project_dossier"},
            )
            chunks = _drain_queue(pipeline.events("session-1"))

            assert session.status == "active"
            assert session.current_stage == AWAITING_INVENTORY_STAGE_NAME
            assert [chunk.type for chunk in chunks] == ["report_card", "report_card"]
            assert [chunk.payload["kind"] for chunk in chunks] == [
                "gate_closed",
                "stage_started",
            ]
            assert chunks[0].payload["payload"] == {
                "gate_id": REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
                "choice": "general_project_dossier",
            }
            assert chunks[1].payload["stage_name"] == AWAITING_INVENTORY_STAGE_NAME
            assert [stage.name for stage in store.list_stages("session-1")] == [
                BOOTSTRAP_STAGE_NAME,
                AWAITING_INVENTORY_STAGE_NAME,
            ]
            assert [stage.status for stage in store.list_stages("session-1")] == [
                "complete",
                "active",
            ]

    async def test_cancel_completes_the_session(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            pipeline = ReportPipeline(store, ReportPipelineRegistry())

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
        async with lifespan_report_sessions(":memory:") as store:
            pipeline = ReportPipeline(store, ReportPipelineRegistry())

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
        async with lifespan_report_sessions(":memory:") as store:
            registry = ReportPipelineRegistry()
            pipeline = ReportPipeline(store, registry)

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
        async with lifespan_report_sessions(":memory:") as store:
            pipeline = ReportPipeline(store, ReportPipelineRegistry())

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
