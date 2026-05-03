"""AppState wiring contracts for injected FastAPI apps."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import build_app_state
from app.services.document_analysis import NoopDocumentAnalyzer
from app.services.document_registry import DocumentRegistry
from app.services.report_pipeline import ReportPipelineRegistry
from app.services.report_sessions import ReportSessionStore


def test_injected_app_state_exposes_document_registry(client: TestClient) -> None:
    registry = client.app.state.app_state.registry

    assert isinstance(registry, DocumentRegistry)
    record, is_duplicate = registry.register_or_get(
        "fixture-hash",
        document_id="fixture-doc",
        original_filename="fixture.txt",
        stored_path="/app/data/documents/fixture-doc.txt",
        content_type="text/plain",
        byte_size=12,
        uploaded_at="2026-05-01T10:00:00+00:00",
    )

    assert is_duplicate is False
    assert registry.get_by_id("fixture-doc") == record


def test_build_app_state_can_include_document_analyzer(client: TestClient) -> None:
    analyzer = NoopDocumentAnalyzer()
    state = build_app_state(
        llm=client.app.state.app_state.llm,
        kb=client.app.state.app_state.kb,
        checkpointer=client.app.state.app_state.checkpointer,
        registry=client.app.state.app_state.registry,
        report_sessions=client.app.state.app_state.report_sessions,
        graph=client.app.state.app_state.graph,
        settings=client.app.state.app_state.settings,
        pipeline_registry=client.app.state.app_state.pipeline_registry,
        document_analyzer=analyzer,
    )

    assert state.document_analyzer is analyzer
    assert state.settings is client.app.state.app_state.settings


def test_build_app_state_exposes_report_sessions_store(client: TestClient) -> None:
    state = client.app.state.app_state

    assert isinstance(state.report_sessions, ReportSessionStore)
    record = state.report_sessions.create_session(session_id="session-1")
    assert state.report_sessions.get_session("session-1") == record


def test_build_app_state_exposes_report_pipeline_registry(client: TestClient) -> None:
    state = client.app.state.app_state

    assert isinstance(state.pipeline_registry, ReportPipelineRegistry)
