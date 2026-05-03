"""Integration tests for the report session API."""

from __future__ import annotations

import json
from pathlib import Path

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


def _set_report_draft_llm(client: TestClient, payloads: list[str]) -> None:
    client.app.state.app_state.llm = make_fake_chat_model(payloads)


def _set_empty_report_draft_llm(client: TestClient) -> None:
    _set_report_draft_llm(
        client,
        [json.dumps({"paragraphs": []}, ensure_ascii=False)],
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
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
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


def _seed_indexed_text_document(registry) -> str:
    indexed_record, _ = registry.register_or_get(
        "hash-indexed-report",
        document_id="doc-indexed-report",
        original_filename="site-report.txt",
        stored_path="/app/data/documents/doc-indexed-report.txt",
        content_type="text/plain",
        byte_size=123,
        uploaded_at="2026-05-01T10:00:00+00:00",
    )
    registry.update_status(indexed_record.document_id, "indexed")
    return indexed_record.document_id


async def _seed_recalled_memory(kb) -> str:
    provenance_header = "[source=report.pdf; page=2; element=paragraph; extraction=text]"
    memory_content = (
        f"{provenance_header}\n"
        "Texte Unterlagen Aufgabenstellung und Berichtszweck "
        "— Aufgabenstellung Bauwerk"
    )
    return await kb.remember(
        memory_content,
        metadata={
            "document_id": "doc-hit",
            "source": "report.pdf",
        },
    )


async def _seed_uncertainty_memory(kb) -> str:
    provenance_header = "[source=uncertainty.pdf; page=7; element=paragraph; extraction=text]"
    memory_content = (
        f"{provenance_header}\n"
        "Texte Unterlagen Unsicherheiten, Widersprueche und fehlende Nachweise "
        "— fehlende Nachweise bleiben als Unsicherheit sichtbar."
    )
    return await kb.remember(
        memory_content,
        metadata={
            "document_id": "doc-uncertainty",
            "source": "uncertainty.pdf",
        },
    )


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
        assert [item["finding_id"] for item in body["validation_findings"]] == [finding.finding_id]
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
        assert session.status == "blocked"
        assert session.current_stage == "validate_report"

        stages = store.list_stages(session_id)
        assert [stage.name for stage in stages] == [
            "bootstrap",
            "inventory_sources",
            "plan_report_sections",
            "retrieve_section_evidence",
            "draft_report_sections",
            "validate_report",
        ]
        assert stages[-1].status == "complete"
        gates = store.list_gates(session_id)
        assert gates[0].status == "closed"
        assert gates[0].answer == {"choice": "general_project_dossier"}
        assert gates[1].gate_id == "report_validation_export_confirmation"
        assert gates[1].status == "open"
        assert [finding.code for finding in store.list_validation_findings(session_id)] == [
            "appendix_source_inventory_consistent",
            "mandatory_uncertainty_missing",
        ]
        assert store.list_exports(session_id) == []

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
        assert body["current_stage"] == "validate_report"
        assert body["session"]["status"] == "blocked"
        assert [stage["name"] for stage in body["stages"]] == [
            "bootstrap",
            "inventory_sources",
            "plan_report_sections",
            "retrieve_section_evidence",
            "draft_report_sections",
            "validate_report",
        ]
        assert len(body["stages"]) == 6
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
        assert body["validation_findings"]
        assert any(
            finding["severity"] == "blocker"
            and finding["code"] == "failed_skipped_source_not_visible"
            for finding in body["validation_findings"]
        )
        assert body["exports"] == []
        assert body["gates"][-1]["gate_id"] == "report_validation_export_confirmation"
        assert body["gates"][-1]["status"] == "open"

    async def test_general_project_dossier_run_produces_paragraph_citations(
        self,
        client: TestClient,
    ) -> None:
        registry = client.app.state.app_state.registry
        _seed_indexed_text_document(registry)
        memory_id = await _seed_recalled_memory(client.app.state.app_state.kb)

        payload = json.dumps(
            {
                "paragraphs": [
                    {
                        "text": f"Beispielabsatz [evidence_id={memory_id}]",
                        "evidence_ids": [memory_id],
                    }
                ]
            },
            ensure_ascii=False,
        )
        llm = make_fake_chat_model([payload] * 4)
        client.app.state.app_state.llm = llm

        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

        response = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert response.status_code == 204

        inspection = client.get(f"/api/reports/{session_id}")
        assert inspection.status_code == 200

        body = inspection.json()
        stage_statuses = {stage["name"]: stage["status"] for stage in body["stages"]}
        retrieval_manifest = next(
            artifact for artifact in body["artifacts"] if artifact["kind"] == "other"
        )
        paragraph_artifacts = [
            artifact for artifact in body["artifacts"] if artifact["kind"] == "paragraph_citations"
        ]
        evidence_artifact = next(
            artifact for artifact in paragraph_artifacts if artifact["content"]["evidence_manifest"]
        )
        retrieval_section = next(
            section
            for section in retrieval_manifest["content"]["sections"]
            if section["id"] == "aufgabenstellung"
        )
        hit_section_ids = [
            section["id"]
            for section in retrieval_manifest["content"]["sections"]
            if section["total_hit_count"] > 0
        ]

        assert body["session"]["status"] == "blocked"
        assert body["current_stage"] == "validate_report"
        assert stage_statuses["retrieve_section_evidence"] == "complete"
        assert stage_statuses["draft_report_sections"] == "complete"
        assert stage_statuses["validate_report"] == "complete"
        assert retrieval_manifest["content"]["kind"] == "retrieval_manifest"
        assert hit_section_ids == ["aufgabenstellung"]
        assert retrieval_section["total_hit_count"] == 1
        assert retrieval_section["recalled_memories"][0]["id"] == memory_id
        assert evidence_artifact["content"]["section_id"] == "aufgabenstellung"
        assert evidence_artifact["content"]["text"] == (f"Beispielabsatz [evidence_id={memory_id}]")
        assert evidence_artifact["content"]["evidence_manifest"] == [
            {
                "memory_id": memory_id,
                "provenance": "[source=report.pdf; page=2; element=paragraph; extraction=text]",
            }
        ]
        assert any(
            finding["code"] == "mandatory_uncertainty_missing"
            for finding in body["validation_findings"]
        )
        assert body["exports"] == []
        assert llm.call_count == 1

    async def test_general_project_dossier_run_marks_zero_evidence_sections(
        self,
        client: TestClient,
    ) -> None:
        llm = make_fake_chat_model([])
        client.app.state.app_state.llm = llm

        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

        response = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert response.status_code == 204

        inspection = client.get(f"/api/reports/{session_id}")
        assert inspection.status_code == 200

        body = inspection.json()
        section_plan = next(
            artifact for artifact in body["artifacts"] if artifact["kind"] == "section_plan"
        )
        active_section_ids = [
            section["id"] for section in section_plan["content"]["sections"] if section["active"]
        ]
        paragraph_artifacts = [
            artifact for artifact in body["artifacts"] if artifact["kind"] == "paragraph_citations"
        ]
        warning_logs = [log for log in body["recent_logs"] if log["level"] == "warning"]
        stage_statuses = {stage["name"]: stage["status"] for stage in body["stages"]}

        assert body["session"]["status"] == "blocked"
        assert body["current_stage"] == "validate_report"
        assert stage_statuses["retrieve_section_evidence"] == "complete"
        assert stage_statuses["draft_report_sections"] == "complete"
        assert stage_statuses["validate_report"] == "complete"
        assert len(paragraph_artifacts) == len(active_section_ids)
        assert sorted(
            artifact["content"]["section_id"] for artifact in paragraph_artifacts
        ) == sorted(active_section_ids)
        assert all(artifact["content"]["no_evidence"] is True for artifact in paragraph_artifacts)
        assert warning_logs
        assert any(
            log["message"].startswith("Section ") and "drafted with no evidence" in log["message"]
            for log in warning_logs
        )
        assert any(
            finding["code"] == "mandatory_uncertainty_missing"
            for finding in body["validation_findings"]
        )
        assert body["exports"] == []
        assert llm.call_count == 0

    async def test_clean_general_project_dossier_exports_pdf_in_inspection(
        self,
        client: TestClient,
    ) -> None:
        memory_id = await _seed_uncertainty_memory(client.app.state.app_state.kb)
        payload = json.dumps(
            {
                "paragraphs": [
                    {
                        "text": (
                            "Unsicherheiten werden als interner Prüfpunkt benannt. "
                            f"[evidence_id={memory_id}]"
                        ),
                        "evidence_ids": [memory_id],
                    }
                ]
            },
            ensure_ascii=False,
        )
        llm = make_fake_chat_model([payload])
        client.app.state.app_state.llm = llm

        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

        answer = client.post(
            f"/api/reports/{session_id}/gates/{gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert answer.status_code == 204

        inspection = client.get(f"/api/reports/{session_id}")
        assert inspection.status_code == 200

        body = inspection.json()
        export = body["exports"][0]
        pdf_artifact = next(
            artifact for artifact in body["artifacts"] if artifact["kind"] == "pdf_export"
        )
        stage_statuses = {stage["name"]: stage["status"] for stage in body["stages"]}
        log_messages = [log["message"] for log in body["recent_logs"]]

        assert body["session"]["status"] == "complete"
        assert body["current_stage"] == "export_report"
        assert stage_statuses["validate_report"] == "complete"
        assert stage_statuses["export_report"] == "complete"
        assert [finding["severity"] for finding in body["validation_findings"]] == ["info"]
        assert export["status"] == "ready"
        assert export["format"] == "pdf"
        assert export["output_path"] is not None
        assert Path(export["output_path"]).read_bytes().startswith(b"%PDF")
        assert export["diagnostics"]["validation_blocker_count"] == 0
        assert export["diagnostics"]["blockers_overridden"] is False
        assert pdf_artifact["content"]["status"] == "ready"
        assert pdf_artifact["content"]["diagnostics"]["format"] == "pdf"
        assert "Report validation stage completed" in log_messages
        assert "Report PDF export ready" in log_messages
        assert llm.call_count == 1

    async def test_validation_gate_rejects_invalid_choice_then_exports_with_override(
        self,
        client: TestClient,
    ) -> None:
        launch = client.post("/api/reports", json={})
        session_id = launch.json()["session_id"]
        bootstrap_gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[
            0
        ].gate_id
        _set_empty_report_draft_llm(client)

        first = client.post(
            f"/api/reports/{session_id}/gates/{bootstrap_gate_id}/answer",
            json={"answer": {"choice": "general_project_dossier"}},
        )
        assert first.status_code == 204

        validation_gate = client.app.state.app_state.report_sessions.list_gates(session_id)[-1]
        invalid = client.post(
            f"/api/reports/{session_id}/gates/{validation_gate.gate_id}/answer",
            json={"answer": {"choice": "unsupported"}},
        )
        assert invalid.status_code == 422
        gates = client.app.state.app_state.report_sessions.list_gates(session_id)
        assert gates[-1].status == "open"
        assert client.app.state.app_state.report_sessions.list_exports(session_id) == []

        proceed = client.post(
            f"/api/reports/{session_id}/gates/{validation_gate.gate_id}/answer",
            json={"answer": {"choice": "proceed_with_blockers"}},
        )
        assert proceed.status_code == 204

        inspection = client.get(f"/api/reports/{session_id}")
        body = inspection.json()
        export = body["exports"][0]

        assert body["session"]["status"] == "complete"
        assert body["current_stage"] == "export_report"
        assert body["gates"][-1]["status"] == "closed"
        assert body["gates"][-1]["answer"] == {"choice": "proceed_with_blockers"}
        assert export["status"] == "ready"
        assert export["diagnostics"]["blockers_overridden"] is True
        assert export["diagnostics"]["validation_blocker_count"] >= 1
        assert export["diagnostics"]["validation_gate_id"] == (
            "report_validation_export_confirmation"
        )
        assert Path(export["output_path"]).exists()

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


class TestReportExportDownload:
    def test_download_ready_export_returns_pdf_bytes_and_basename_header(
        self,
        client: TestClient,
    ) -> None:
        store = client.app.state.app_state.report_sessions
        export_root = Path(client.app.state.app_state.report_exports_dir)
        export_root.mkdir(parents=True, exist_ok=True)
        pdf_path = export_root / "ready-report.pdf"
        pdf_path.write_bytes(b"%PDF-1.7\nready export\n")

        session = store.create_session()
        export = store.create_export(
            session.session_id,
            format="pdf",
            status="ready",
            output_path=str(pdf_path),
            diagnostics={"output_filename": pdf_path.name},
        )

        response = client.get(
            f"/api/reports/{session.session_id}/exports/{export.export_id}/download"
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        content_disposition = response.headers["content-disposition"]
        assert pdf_path.name in content_disposition
        assert str(pdf_path.parent) not in content_disposition

    def test_download_rejects_unknown_and_mismatched_exports(
        self,
        client: TestClient,
    ) -> None:
        store = client.app.state.app_state.report_sessions
        export_root = Path(client.app.state.app_state.report_exports_dir)
        export_root.mkdir(parents=True, exist_ok=True)
        pdf_path = export_root / "other-session.pdf"
        pdf_path.write_bytes(b"%PDF-1.7\nother session\n")

        first_session = store.create_session()
        second_session = store.create_session()
        second_export = store.create_export(
            second_session.session_id,
            format="pdf",
            status="ready",
            output_path=str(pdf_path),
        )

        unknown_session = client.get(
            "/api/reports/missing-session/exports/missing-export/download"
        )
        unknown_export = client.get(
            f"/api/reports/{first_session.session_id}/exports/missing-export/download"
        )
        mismatched_export = client.get(
            f"/api/reports/{first_session.session_id}/exports/"
            f"{second_export.export_id}/download"
        )

        assert unknown_session.status_code == 404
        assert unknown_export.status_code == 404
        assert mismatched_export.status_code == 404

    def test_download_rejects_non_ready_missing_and_escaping_paths(
        self,
        client: TestClient,
        tmp_path: Path,
    ) -> None:
        store = client.app.state.app_state.report_sessions
        export_root = Path(client.app.state.app_state.report_exports_dir)
        export_root.mkdir(parents=True, exist_ok=True)
        pdf_path = export_root / "pending-report.pdf"
        pdf_path.write_bytes(b"%PDF-1.7\npending export\n")
        outside_path = tmp_path / "outside-report.pdf"
        outside_path.write_bytes(b"%PDF-1.7\noutside export\n")

        session = store.create_session()
        pending_export = store.create_export(
            session.session_id,
            format="pdf",
            status="pending",
            output_path=str(pdf_path),
        )
        no_path_export = store.create_export(
            session.session_id,
            format="pdf",
            status="ready",
            output_path=None,
        )
        missing_file_export = store.create_export(
            session.session_id,
            format="pdf",
            status="ready",
            output_path=str(export_root / "missing-report.pdf"),
        )
        escaping_export = store.create_export(
            session.session_id,
            format="pdf",
            status="ready",
            output_path=str(outside_path),
        )

        pending = client.get(
            f"/api/reports/{session.session_id}/exports/{pending_export.export_id}/download"
        )
        no_path = client.get(
            f"/api/reports/{session.session_id}/exports/{no_path_export.export_id}/download"
        )
        missing_file = client.get(
            f"/api/reports/{session.session_id}/exports/"
            f"{missing_file_export.export_id}/download"
        )
        escaping = client.get(
            f"/api/reports/{session.session_id}/exports/{escaping_export.export_id}/download"
        )

        assert pending.status_code == 409
        assert no_path.status_code == 404
        assert missing_file.status_code == 404
        assert escaping.status_code == 404
        assert str(outside_path) not in escaping.text


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
            payload["type"] == "report_card" and payload["payload"]["kind"] == "stage_started"
            for payload in payloads
        )
        assert any(
            payload["type"] == "report_gate" and payload["payload"]["status"] == "open"
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
