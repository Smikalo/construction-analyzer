"""AppState wiring contracts for injected FastAPI apps."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import build_app_state
from app.services.document_analysis import NoopDocumentAnalyzer
from app.services.document_registry import DocumentRegistry


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
        graph=client.app.state.app_state.graph,
        settings=client.app.state.app_state.settings,
        document_analyzer=analyzer,
    )

    assert state.document_analyzer is analyzer
    assert state.settings is client.app.state.app_state.settings
