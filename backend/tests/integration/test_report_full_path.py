"""Full-path report API proof from public ingest to PDF download."""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests._fakes import make_fake_chat_model

_SYNTHETIC_EVIDENCE = (
    "Synthetic Bauwerksbericht fixture.\n"
    "Texte Unterlagen Aufgabenstellung und Berichtszweck: "
    "Die Aufgabenstellung beschreibt eine hermetische Berichtserstellung.\n"
    "Texte Unterlagen Unsicherheiten, Widersprueche und fehlende Nachweise: "
    "Unsicherheiten und fehlende Nachweise werden fuer den Entwurf sichtbar benannt.\n"
)


def test_public_ingest_report_export_path_downloads_ready_pdf(
    client: TestClient,
    tmp_path: Path,
) -> None:
    documents_dir = tmp_path / "documents"
    client.app.state.app_state.settings.documents_dir = str(documents_dir)

    ingest_response = client.post(
        "/api/ingest",
        files=[
            (
                "files",
                (
                    "synthetic-report-evidence.txt",
                    io.BytesIO(_SYNTHETIC_EVIDENCE.encode("utf-8")),
                    "text/plain",
                ),
            )
        ],
    )
    assert ingest_response.status_code == 200, ingest_response.text
    ingest_body = ingest_response.json()
    assert ingest_body["ingested_files"] == 1
    assert ingest_body["ingested_chunks"] == 1
    assert len(ingest_body["memory_ids"]) == 1
    memory_id = ingest_body["memory_ids"][0]

    paragraph_payload = json.dumps(
        {
            "paragraphs": [
                {
                    "text": (
                        "Die Aufgabenstellung ist durch die synthetischen Unterlagen belegt. "
                        f"[evidence_id={memory_id}]"
                    ),
                    "evidence_ids": [memory_id],
                }
            ]
        },
        ensure_ascii=False,
    )
    uncertainty_payload = json.dumps(
        {
            "paragraphs": [
                {
                    "text": (
                        "Unsicherheiten und fehlende Nachweise sind im Entwurf sichtbar benannt. "
                        f"[evidence_id={memory_id}]"
                    ),
                    "evidence_ids": [memory_id],
                }
            ]
        },
        ensure_ascii=False,
    )
    llm = make_fake_chat_model([paragraph_payload, uncertainty_payload])
    client.app.state.app_state.llm = llm

    launch = client.post("/api/reports", json={})
    assert launch.status_code == 200, launch.text
    session_id = launch.json()["session_id"]
    gate_id = client.app.state.app_state.report_sessions.list_gates(session_id)[0].gate_id

    gate_answer = client.post(
        f"/api/reports/{session_id}/gates/{gate_id}/answer",
        json={"answer": {"choice": "general_project_dossier"}},
    )
    assert gate_answer.status_code == 204, gate_answer.text

    inspection = client.get(f"/api/reports/{session_id}")
    assert inspection.status_code == 200, inspection.text
    body = inspection.json()

    stage_statuses = {stage["name"]: stage["status"] for stage in body["stages"]}
    assert stage_statuses == {
        "bootstrap": "complete",
        "inventory_sources": "complete",
        "plan_report_sections": "complete",
        "retrieve_section_evidence": "complete",
        "draft_report_sections": "complete",
        "validate_report": "complete",
        "export_report": "complete",
    }
    assert body["session"]["status"] == "complete"
    assert body["session"]["last_error"] is None
    assert body["current_stage"] == "export_report"

    retrieval_manifest = next(
        artifact for artifact in body["artifacts"] if artifact["kind"] == "other"
    )
    sections_by_id = {
        section["id"]: section for section in retrieval_manifest["content"]["sections"]
    }
    aufgabenstellung = sections_by_id["aufgabenstellung"]
    unsicherheiten = sections_by_id["unsicherheiten"]
    assert aufgabenstellung["total_hit_count"] == 1
    assert unsicherheiten["total_hit_count"] == 1
    assert aufgabenstellung["recalled_memories"][0]["id"] == memory_id
    assert unsicherheiten["recalled_memories"][0]["id"] == memory_id
    assert any(
        query["query"] == "Texte Unterlagen Aufgabenstellung und Berichtszweck"
        and query["memory_ids"] == [memory_id]
        for query in aufgabenstellung["queries"]
    )
    assert any(
        query["query"]
        == "Texte Unterlagen Unsicherheiten, Widersprueche und fehlende Nachweise"
        and query["memory_ids"] == [memory_id]
        for query in unsicherheiten["queries"]
    )

    paragraph_artifacts = [
        artifact for artifact in body["artifacts"] if artifact["kind"] == "paragraph_citations"
    ]
    cited_paragraphs = [
        artifact
        for artifact in paragraph_artifacts
        if artifact["content"]["evidence_manifest"]
    ]
    assert {artifact["content"]["section_id"] for artifact in cited_paragraphs} == {
        "aufgabenstellung",
        "unsicherheiten",
    }
    assert all(
        artifact["content"]["evidence_manifest"][0]["memory_id"] == memory_id
        for artifact in cited_paragraphs
    )

    findings = body["validation_findings"]
    assert findings
    assert [finding["severity"] for finding in findings] == ["info"]
    assert findings[0]["code"] == "appendix_source_inventory_consistent"

    log_messages = [log["message"] for log in body["recent_logs"]]
    assert any(
        message == "Recalled 1 memories for section aufgabenstellung in family text_documents"
        for message in log_messages
    )
    assert any(
        message == "Recalled 1 memories for section unsicherheiten in family text_documents"
        for message in log_messages
    )
    validation_log = next(
        log for log in body["recent_logs"] if log["message"] == "Report validation stage completed"
    )
    assert validation_log["payload"]["finding_counts"] == {
        "total": 1,
        "info": 1,
        "warning": 0,
        "blocker": 0,
        "codes": {"appendix_source_inventory_consistent": 1},
    }

    assert len(body["exports"]) == 1
    export = body["exports"][0]
    assert export["status"] == "ready"
    assert export["format"] == "pdf"
    assert export["diagnostics"]["validation_finding_count"] == len(findings)
    assert export["diagnostics"]["validation_blocker_count"] == 0
    assert export["diagnostics"]["blockers_overridden"] is False
    assert export["diagnostics"]["output_filename"] == Path(export["output_path"]).name

    export_root = Path(client.app.state.app_state.report_exports_dir).resolve()
    export_path = Path(export["output_path"]).resolve()
    assert export_path.is_relative_to(export_root)
    assert export_path.read_bytes().startswith(b"%PDF")

    pdf_artifact = next(
        artifact for artifact in body["artifacts"] if artifact["kind"] == "pdf_export"
    )
    assert pdf_artifact["content"]["status"] == "ready"
    assert pdf_artifact["content"]["output_filename"] == export_path.name
    assert "output_path" not in pdf_artifact["content"]

    export_log = next(
        log for log in body["recent_logs"] if log["message"] == "Report PDF export ready"
    )
    assert export_log["payload"]["export_id"] == export["export_id"]
    assert export_log["payload"]["output_filename"] == export_path.name
    assert "output_path" not in export_log["payload"]

    download = client.get(
        f"/api/reports/{session_id}/exports/{export['export_id']}/download"
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")
    content_disposition = download.headers["content-disposition"]
    assert export_path.name in content_disposition
    assert str(export_path.parent) not in content_disposition

    assert llm.call_count == 2
