"""Report session API endpoints.

These routes launch and inspect durable report sessions, accept structured gate
answers, and expose the per-session SSE queue used by the chat-owned report
UI.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Request, Response
from sse_starlette.sse import EventSourceResponse

from app.schemas import (
    ChatChunk,
    ReportArtifact,
    ReportExport,
    ReportGate,
    ReportGateAnswerRequest,
    ReportLog,
    ReportSession,
    ReportSessionInspectionResponse,
    ReportSessionLaunchRequest,
    ReportSessionLaunchResponse,
    ReportStage,
    ReportValidationFinding,
)
from app.services.document_registry import DocumentRegistry
from app.services.report_pipeline import ReportPipeline, ReportPipelineRegistry
from app.services.report_sessions import ReportGateRecord, ReportSessionStore

router = APIRouter(prefix="/api/reports", tags=["reports"])

_TERMINAL_SESSION_STATUSES = {"complete", "failed"}
TModel = TypeVar("TModel")


@router.post("", response_model=ReportSessionLaunchResponse)
async def launch_report_session(
    req: ReportSessionLaunchRequest,
    request: Request,
) -> ReportSessionLaunchResponse:
    state = request.app.state.app_state
    session_id = req.session_id.strip() if req.session_id is not None else uuid.uuid4().hex
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id must not be empty")

    state.pipeline_registry.get_or_create(session_id)
    pipeline = _build_pipeline(state.pipeline_registry, state.report_sessions, state.registry)
    resumed = state.report_sessions.get_session(session_id) is not None

    metadata = dict(req.metadata)
    if req.thread_id is not None:
        metadata.setdefault("thread_id", req.thread_id)

    session = await pipeline.start(session_id, metadata=metadata or None)
    return ReportSessionLaunchResponse(
        session_id=session.session_id,
        status=session.status,
        current_stage=session.current_stage,
        resumed=resumed,
    )


@router.get("/{session_id}", response_model=ReportSessionInspectionResponse)
async def get_report_session(session_id: str, request: Request) -> ReportSessionInspectionResponse:
    state = request.app.state.app_state
    session = state.report_sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="report session not found")

    stages = [
        _to_model(ReportStage, stage)
        for stage in state.report_sessions.list_stages(session_id)
    ]
    gates = [_to_model(ReportGate, gate) for gate in state.report_sessions.list_gates(session_id)]
    artifacts = [
        _to_model(ReportArtifact, artifact)
        for artifact in state.report_sessions.list_artifacts(session_id)
    ]
    validation_findings = [
        _to_model(ReportValidationFinding, finding)
        for finding in state.report_sessions.list_validation_findings(session_id)
    ]
    exports = [
        _to_model(ReportExport, export) for export in state.report_sessions.list_exports(session_id)
    ]
    recent_logs = [
        _to_model(ReportLog, log) for log in state.report_sessions.list_logs(session_id)
    ]
    return ReportSessionInspectionResponse(
        session=_to_model(ReportSession, session),
        current_stage=session.current_stage,
        stages=stages,
        gates=gates,
        artifacts=artifacts,
        validation_findings=validation_findings,
        exports=exports,
        recent_logs=recent_logs,
    )


@router.post("/{session_id}/gates/{gate_id}/answer", status_code=204)
async def answer_report_gate(
    session_id: str,
    gate_id: str,
    req: ReportGateAnswerRequest,
    request: Request,
) -> Response:
    state = request.app.state.app_state
    session = state.report_sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="report session not found")

    gate = _find_gate(state.report_sessions, session_id, gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail="report gate not found")
    if gate.status != "open":
        raise HTTPException(status_code=409, detail="report gate is already closed")

    pipeline = _build_pipeline(state.pipeline_registry, state.report_sessions, state.registry)
    try:
        await pipeline.answer_gate(session_id, req.answer, gate_id=gate.gate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report gate not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(status_code=204)


@router.get("/{session_id}/stream")
async def stream_report_session(session_id: str, request: Request):
    state = request.app.state.app_state
    session = state.report_sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="report session not found")

    queue = state.pipeline_registry.events(session_id)

    async def event_gen():
        while True:
            while True:
                try:
                    chunk = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                yield {"event": "message", "data": chunk.model_dump_json()}

            latest = state.report_sessions.get_session(session_id)
            if latest is None:
                raise HTTPException(status_code=404, detail="report session not found")
            if latest.status in _TERMINAL_SESSION_STATUSES:
                yield {
                    "event": "message",
                    "data": ChatChunk(type="done", data="").model_dump_json(),
                }
                return

            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.25)
            except TimeoutError:
                continue
            yield {"event": "message", "data": chunk.model_dump_json()}

    return EventSourceResponse(event_gen())


def _build_pipeline(
    registry: ReportPipelineRegistry,
    store: ReportSessionStore,
    document_registry: DocumentRegistry,
) -> ReportPipeline:
    return ReportPipeline(store=store, registry=document_registry, registry_pipeline=registry)


def _find_gate(
    store,
    session_id: str,
    gate_id: str,
) -> ReportGateRecord | None:
    normalized_gate_id = gate_id.strip()
    if not normalized_gate_id:
        raise HTTPException(status_code=422, detail="gate_id must not be empty")
    for gate in store.list_gates(session_id):
        if gate.gate_id == normalized_gate_id:
            return gate
    return None


def _to_model(model: type[TModel], record: Any) -> TModel:
    return model(**asdict(record))
