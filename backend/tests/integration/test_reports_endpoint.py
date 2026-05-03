"""Integration tests for the report session API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests._fakes import make_fake_chat_model


def _parse_sse_events(blob: str) -> list[tuple[str, str]]:
    blob = blob.replace("\r\n", "\n")
    events: list[tuple[str, str]] = []
    for frame in blob.split("\n\n"):
        if not frame.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        events.append((event_name, "\n".join(data_lines)))
    return events


def _set_empty_report_draft_llm(client: TestClient) -> None:
    client.app.state.app_state.llm = make_fake_chat_model(
        [json.dumps({"paragraphs": []}, ensure_ascii=False)]
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


class TestReportLaunch:
    async def test_launch_creates_session_and_bootstrap_stage(self, client: TestClient) -> None:
        response = client.post("/api/reports", json={})
        assert response.status_code == 200

        body = response.json()
        assert body["resumed"] is False
        assert isinstance(body["session_id"], str) and body["session_id"]
        assert body["status"] == "blocked"
        assert body["current_stage"] == "bootstrap"

        store = client.app.state.app_state.report_sessions
        session = store.get_session(body["session_id"])
        assert session is not None
        assert session.status == "blocked"
        assert session.current_stage == "bootstrap"
        assert [stage.name for stage in store.list_stages(body["session_id"])] == ["bootstrap"]
        gates = store.list_gates(body["session_id"])
        assert len(gates) == 1
        assert gates[0].status == "open"
        assert gates[0].gate_id == "report_template_confirmation"

    async def test_launch_with_same_session_id_resumes_without_duplicate_bootstrap(
        self,
        client: TestClient,
    ) -> None:
        first = client.post("/api/reports", json={})
        session_id = first.json()["session_id"]

        second = client.post("/api/reports", json={"session_id": session_id})
        assert second.status_code == 200
        assert second.json()["resumed"] is True

        stages = client.app.state.app_state.report_sessions.list_stages(session_id)
        bootstrap_stages = [stage for stage in stages if stage.name == "bootstrap"]
        assert len(bootstrap_stages) == 1


class TestReportInspection:
    async def test_get_returns_artifacts_validation_findings_and_exports(
        self,
        client: TestClient,
    ) -> None:
        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        store = client.app.state.app_state.report_sessions

        artifact = store.record_artifact(
            session_id,
            kind="section_plan",
            content={"section": "timeline"},
            created_at="2024-01-01T00:00:00Z",
        )
        finding = store.record_validation_finding(
            session_id,
            severity="warning",
            code="W001",
            message="Needs review",
            payload={"section": "timeline"},
            created_at="2024-01-01T00:00:01Z",
        )
        export = store.create_export(
            session_id,
            format="pdf",
            status="ready",
            output_path="report.pdf",
            diagnostics={"pages": 4},
            created_at="2024-01-01T00:00:02Z",
        )

        response = client.get(f"/api/reports/{session_id}")
        assert response.status_code == 200

        body = response.json()
        assert [item["artifact_id"] for item in body["artifacts"]] == [artifact.artifact_id]
        assert [item["kind"] for item in body["artifacts"]] == ["section_plan"]
        assert [item["finding_id"] for item in body["validation_findings"]] == [
            finding.finding_id
        ]
        assert [item["severity"] for item in body["validation_findings"]] == ["warning"]
        assert [item["export_id"] for item in body["exports"]] == [export.export_id]
        assert [item["status"] for item in body["exports"]] == ["ready"]

        fresh_session = store.create_session()
        fresh_response = client.get(f"/api/reports/{fresh_session.session_id}")
        assert fresh_response.status_code == 200

        fresh_body = fresh_response.json()
        assert fresh_body["artifacts"] == []
        assert fresh_body["validation_findings"] == []
        assert fresh_body["exports"] == []

    async def test_unknown_session_returns_404_for_inspection_and_gate_answer(
        self,
        client: TestClient,
    ) -> None:
        missing_session_id = "missing-session"

        inspection = client.get(f"/api/reports/{missing_session_id}")
        assert inspection.status_code == 404

        answer = client.post(
            f"/api/reports/{missing_session_id}/gates/report_template_confirmation/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert answer.status_code == 404


class TestReportGateAnswer:
    async def test_gate_answer_general_project_dossier_advances_session_to_active(
        self,
        client: TestClient,
    ) -> None:
        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id
        _set_empty_report_draft_llm(client)

        response = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert response.status_code == 204

        store = client.app.state.app_state.report_sessions
        session = store.get_session(session_id)
        assert session is not None
        assert session.status == "active"
        assert session.current_stage == "draft_report_sections"

        stages = store.list_stages(session_id)
        assert [stage.name for stage in stages] == [
            "bootstrap",
            "inventory_sources",
            "plan_report_sections",
            "retrieve_section_evidence",
            "draft_report_sections",
        ]
        gates = store.list_gates(session_id)
        assert gates[0].status == "closed"
        assert gates[0].answer == {"choice": "general_project_dossier"}

    async def test_general_project_dossier_persists_inventory_and_section_plan_in_inspection(
        self,
        client: TestClient,
    ) -> None:
        registry = client.app.state.app_state.registry
        _seed_report_documents(registry)

        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id
        _set_empty_report_draft_llm(client)

        response = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert response.status_code == 204

        inspection = client.get(f"/api/reports/{session_id}")
        assert inspection.status_code == 200

        body = inspection.json()
        assert body["current_stage"] == "draft_report_sections"
        assert body["session"]["status"] == "active"
        assert [stage["name"] for stage in body["stages"]] == [
            "bootstrap",
            "inventory_sources",
            "plan_report_sections",
            "retrieve_section_evidence",
            "draft_report_sections",
        ]
        assert len(body["stages"]) == 5
        assert body["artifacts"][0]["content"]["totals"] == {
            "indexed": 1,
            "skipped": 1,
            "failed": 1,
            "uploaded": 0,
            "processing": 0,
            "total": 3,
        }
        assert body["artifacts"][1]["content"]["template_id"] == "general_project_dossier"
        assert len(body["artifacts"][1]["content"]["sections"]) == 14
        retrieval_artifact = next(
            artifact for artifact in body["artifacts"] if artifact["kind"] == "other"
        )
        paragraph_artifacts = [
            artifact for artifact in body["artifacts"] if artifact["kind"] == "paragraph_citations"
        ]
        active_section_count = sum(
            1 for section in body["artifacts"][1]["content"]["sections"] if section["active"]
        )
        assert retrieval_artifact["content"]["kind"] == "retrieval_manifest"
        assert len(paragraph_artifacts) == active_section_count
        assert all(artifact["content"]["no_evidence"] is True for artifact in paragraph_artifacts)

    async def test_double_answering_closed_gate_returns_409(self, client: TestClient) -> None:
        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

        first = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert first.status_code == 204

        second = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "cancel"}},
        )
        assert second.status_code == 409


class TestReportStream:
    async def test_stream_emits_report_card_and_report_gate_events(
        self,
        client: TestClient,
    ) -> None:
        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

        # TestClient buffers EventSourceResponse bodies until the stream ends, so
        # complete the session first while leaving the queued bootstrap events
        # available for the stream to drain and assert.
        answer = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "cancel"}},
        )
        assert answer.status_code == 204

        body = ""
        with client.stream("GET", f"/api/reports/{session_id}/stream") as response:
            assert response.status_code == 200
            for chunk in response.iter_text():
                body += chunk

        events = _parse_sse_events(body)
        payloads = [json.loads(data) for event, data in events if event == "message" and data]
        assert any(
            payload["type"] == "report_card"
            and payload["payload"]["kind"] == "stage_started"
            for payload in payloads
        )
        assert any(
            payload["type"] == "report_gate"
            and payload["payload"]["status"] == "open"
            for payload in payloads
        )

    async def test_stream_emits_done_chunk_when_session_completes_via_cancel(
        self,
        client: TestClient,
    ) -> None:
        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

        response = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "cancel"}},
        )
        assert response.status_code == 204
        session = client.app.state.app_state.report_sessions.get_session(session_id)
        assert session is not None
        assert session.status == "complete"

        body = ""
        with client.stream("GET", f"/api/reports/{session_id}/stream") as stream_response:
            assert stream_response.status_code == 200
            for chunk in stream_response.iter_text():
                body += chunk
                if '"type":"done"' in body:
                    break

        assert '"type":"done"' in body
