"""Schemas are the public contract between the frontend and backend.

These tests pin down the wire format so any breaking change is caught early.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    ChatChunk,
    ChatRequest,
    HealthStatus,
    IngestResponse,
    Message,
    ReadinessStatus,
    ReportArtifact,
    ReportExport,
    ReportGate,
    ReportLog,
    ReportSession,
    ReportStage,
    ReportValidationFinding,
    ThreadHistory,
    ThreadInfo,
)


class TestChatRequest:
    def test_minimal_request_is_valid(self) -> None:
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.thread_id is None

    def test_request_with_thread_id_is_valid(self) -> None:
        req = ChatRequest(message="hi", thread_id="abc-123")
        assert req.thread_id == "abc-123"

    def test_empty_message_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_blank_message_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="   ")


class TestChatChunk:
    def test_token_chunk_round_trip(self) -> None:
        chunk = ChatChunk(type="token", data="hello")
        as_dict = chunk.model_dump()
        assert as_dict == {"type": "token", "data": "hello"}

    def test_done_chunk(self) -> None:
        chunk = ChatChunk(type="done", data="")
        assert chunk.type == "done"

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatChunk(type="garbage", data="")  # type: ignore[arg-type]


class TestMessage:
    def test_user_message(self) -> None:
        m = Message(role="user", content="hi")
        assert m.role == "user"

    def test_assistant_message(self) -> None:
        m = Message(role="assistant", content="hey")
        assert m.role == "assistant"

    def test_invalid_role(self) -> None:
        with pytest.raises(ValidationError):
            Message(role="alien", content="hi")  # type: ignore[arg-type]


class TestThreadInfo:
    def test_minimal(self) -> None:
        info = ThreadInfo(thread_id="t1")
        assert info.thread_id == "t1"
        assert info.last_message_at is None
        assert info.message_count == 0

    def test_with_metadata(self) -> None:
        info = ThreadInfo(thread_id="t1", message_count=4, last_message_at=12345.0)
        assert info.message_count == 4


class TestThreadHistory:
    def test_history_round_trip(self) -> None:
        history = ThreadHistory(
            thread_id="t1",
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
        )
        assert len(history.messages) == 2


class TestStatusModels:
    def test_health(self) -> None:
        h = HealthStatus(status="ok")
        assert h.status == "ok"

    def test_readiness_all_good(self) -> None:
        r = ReadinessStatus(
            status="ready",
            ollama=True,
            postgres=True,
            checkpointer=True,
            kb=True,
        )
        assert r.status == "ready"

    def test_readiness_degraded(self) -> None:
        r = ReadinessStatus(
            status="degraded",
            ollama=False,
            postgres=True,
            checkpointer=True,
            kb=False,
            detail="ollama unreachable",
        )
        assert r.status == "degraded"
        assert r.detail == "ollama unreachable"


class TestIngestResponse:
    def test_response(self) -> None:
        r = IngestResponse(
            ingested_files=2,
            ingested_chunks=5,
            memory_ids=["m1", "m2", "m3", "m4", "m5"],
        )
        assert r.ingested_files == 2
        assert len(r.memory_ids) == 5


class TestReportSchemas:
    @pytest.mark.parametrize(
        ("model_cls", "kwargs"),
        [
            (
                ReportSession,
                {
                    "session_id": "session-1",
                    "status": "active",
                    "current_stage": "drafting",
                    "created_at": "2026-05-03T00:00:00Z",
                    "updated_at": "2026-05-03T00:01:00Z",
                    "last_error": None,
                    "metadata": {"report": "alpha"},
                },
            ),
            (
                ReportStage,
                {
                    "stage_id": "stage-1",
                    "session_id": "session-1",
                    "name": "drafting",
                    "status": "active",
                    "started_at": "2026-05-03T00:00:01Z",
                    "completed_at": None,
                    "summary": "Drafting started",
                    "error": None,
                },
            ),
            (
                ReportGate,
                {
                    "gate_id": "gate-1",
                    "session_id": "session-1",
                    "stage_id": "stage-1",
                    "status": "open",
                    "question": {"prompt": "Proceed?"},
                    "answer": {},
                    "created_at": "2026-05-03T00:00:02Z",
                    "closed_at": None,
                },
            ),
            (
                ReportArtifact,
                {
                    "artifact_id": "artifact-1",
                    "session_id": "session-1",
                    "stage_id": "stage-1",
                    "kind": "section_plan",
                    "content": {"sections": ["intro"]},
                    "created_at": "2026-05-03T00:00:03Z",
                },
            ),
            (
                ReportLog,
                {
                    "log_id": "log-1",
                    "session_id": "session-1",
                    "stage_id": "stage-1",
                    "level": "info",
                    "message": "stage started",
                    "payload": {"provenance": ["stage-1"]},
                    "created_at": "2026-05-03T00:00:04Z",
                },
            ),
            (
                ReportValidationFinding,
                {
                    "finding_id": "finding-1",
                    "session_id": "session-1",
                    "severity": "warning",
                    "code": "UNCERTAIN_SOURCE",
                    "message": "missing appendix provenance",
                    "payload": {"source_ids": ["doc-1"]},
                    "created_at": "2026-05-03T00:00:05Z",
                },
            ),
            (
                ReportExport,
                {
                    "export_id": "export-1",
                    "session_id": "session-1",
                    "status": "ready",
                    "format": "pdf",
                    "output_path": "reports/report.pdf",
                    "diagnostics": {"pages": 12},
                    "created_at": "2026-05-03T00:00:06Z",
                    "completed_at": "2026-05-03T00:02:00Z",
                },
            ),
        ],
    )
    def test_report_model_round_trip(self, model_cls, kwargs) -> None:
        model = model_cls(**kwargs)
        assert model_cls.model_validate(model.model_dump()) == model

    @pytest.mark.parametrize(
        ("model_cls", "kwargs"),
        [
            (
                ReportSession,
                {
                    "session_id": "session-1",
                    "status": "bogus",
                    "created_at": "2026-05-03T00:00:00Z",
                },
            ),
            (
                ReportStage,
                {
                    "stage_id": "stage-1",
                    "session_id": "session-1",
                    "name": "drafting",
                    "status": "bogus",
                },
            ),
            (
                ReportGate,
                {
                    "gate_id": "gate-1",
                    "session_id": "session-1",
                    "status": "bogus",
                    "question": {},
                    "created_at": "2026-05-03T00:00:02Z",
                },
            ),
            (
                ReportArtifact,
                {
                    "artifact_id": "artifact-1",
                    "session_id": "session-1",
                    "kind": "bogus",
                    "content": {},
                    "created_at": "2026-05-03T00:00:03Z",
                },
            ),
            (
                ReportLog,
                {
                    "log_id": "log-1",
                    "session_id": "session-1",
                    "level": "bogus",
                    "message": "stage started",
                    "created_at": "2026-05-03T00:00:04Z",
                },
            ),
            (
                ReportValidationFinding,
                {
                    "finding_id": "finding-1",
                    "session_id": "session-1",
                    "severity": "bogus",
                    "message": "missing appendix provenance",
                    "created_at": "2026-05-03T00:00:05Z",
                },
            ),
            (
                ReportExport,
                {
                    "export_id": "export-1",
                    "session_id": "session-1",
                    "status": "bogus",
                    "format": "pdf",
                    "created_at": "2026-05-03T00:00:06Z",
                },
            ),
        ],
    )
    def test_unknown_status_strings_are_rejected(self, model_cls, kwargs) -> None:
        with pytest.raises(ValidationError):
            model_cls(**kwargs)

    def test_json_payload_fields_default_to_empty_dicts(self) -> None:
        session = ReportSession(session_id="session-1", created_at="2026-05-03T00:00:00Z")
        gate = ReportGate(
            gate_id="gate-1", session_id="session-1", created_at="2026-05-03T00:00:01Z"
        )
        log = ReportLog(
            log_id="log-1",
            session_id="session-1",
            level="info",
            message="ok",
            created_at="2026-05-03T00:00:02Z",
        )
        finding = ReportValidationFinding(
            finding_id="finding-1",
            session_id="session-1",
            severity="info",
            message="note",
            created_at="2026-05-03T00:00:03Z",
        )
        export = ReportExport(
            export_id="export-1",
            session_id="session-1",
            format="pdf",
            created_at="2026-05-03T00:00:04Z",
        )

        assert session.metadata == {}
        assert gate.question == {}
        assert gate.answer == {}
        assert log.payload == {}
        assert finding.payload == {}
        assert export.diagnostics == {}
