"""Tests for backend PDF report export."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.services import report_exporter
from app.services.report_exporter import ReportExportError, export_report_pdf
from app.services.report_projection import (
    ReportParagraphCitation,
    ReportParagraphEvidence,
    build_report_projection,
)


def test_export_report_pdf_renders_static_notices_sections_sources_and_citations(
    tmp_path: Path,
) -> None:
    projection = build_report_projection(_report_artifacts())
    findings = [
        {"severity": "warning", "code": "citation_coverage_gap"},
        {"severity": "blocker", "code": "mandatory_uncertainty_missing"},
    ]

    result = export_report_pdf(
        projection,
        output_dir=str(tmp_path),
        session_id="session-123",
        validation_findings=findings,
    )

    pdf_bytes = result.output_path.read_bytes()
    text = _extract_pdf_text(result.output_path)

    assert result.output_path.parent == tmp_path.resolve()
    assert result.output_path.name == "session-123-report.pdf"
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1_000
    assert "Deckblatt" in text
    assert "DRAFT - NOT CERTIFIED" in text
    assert "keine zertifizierte" in text
    assert "internen Prüfung" in text
    assert "Inhaltsverzeichnis" in text
    assert "Grundlagen und ausgewertete Unterlagen" in text
    assert "Unsicherheiten, Widersprüche und fehlende Nachweise" in text
    assert "Maßgebliche Größe beträgt 12 kN" in text
    assert "site-report.pdf" in text
    assert "calc-failed.xlsx" in text
    assert "photo.png" in text
    assert "Anhang: Anlagenverzeichnis" in text
    assert "Nummerierte Zitiernachweise" in text
    assert "[1]" in text
    assert "mem-indexed-report" in text
    assert "mem-failed" in text
    assert "[source=site-report.pdf; page=2; sheet=1; cell=A1]" in text
    assert result.diagnostics == {
        "format": "pdf",
        "output_filename": "session-123-report.pdf",
        "byte_size": len(pdf_bytes),
        "page_count": 4,
        "section_count": 4,
        "paragraph_count": 3,
        "source_count": 3,
        "citation_count": 3,
        "validation_finding_count": 2,
        "validation_warning_count": 1,
        "validation_blocker_count": 1,
    }


def test_export_report_pdf_handles_empty_projection_with_zero_citation_diagnostics(
    tmp_path: Path,
) -> None:
    projection = build_report_projection([])

    result = export_report_pdf(projection, output_dir=str(tmp_path), session_id="empty")

    text = _extract_pdf_text(result.output_path)

    assert result.output_path.read_bytes().startswith(b"%PDF")
    assert "DRAFT - NOT CERTIFIED" in text
    assert "Keine Berichtskapitel verfügbar" in text
    assert "Keine Quellen im Inventar verfügbar" in text
    assert "Keine Zitate im Bericht vorhanden" in text
    assert result.diagnostics["section_count"] == 0
    assert result.diagnostics["source_count"] == 0
    assert result.diagnostics["citation_count"] == 0


def test_export_report_pdf_sanitizes_session_id_and_handles_missing_provenance(
    tmp_path: Path,
) -> None:
    projection = _projection_with_empty_provenance_evidence()
    unsafe_session_id = "../../private/project report: session\\draft"

    result = export_report_pdf(
        projection,
        output_dir=str(tmp_path),
        session_id=unsafe_session_id,
    )

    text = _extract_pdf_text(result.output_path)

    assert result.output_path.resolve().is_relative_to(tmp_path.resolve())
    assert result.output_path.name == "private-project-report-session-draft-report.pdf"
    assert ".." not in result.output_path.name
    assert "/" not in result.output_path.name
    assert "\\" not in result.output_path.name
    assert unsafe_session_id not in str(result.diagnostics)
    assert "keine Provenance angegeben" in text
    assert "mem-without-provenance" in text
    assert result.diagnostics["source_count"] == 0
    assert result.diagnostics["citation_count"] == 1


def test_export_report_pdf_rejects_non_directory_export_destination(tmp_path: Path) -> None:
    projection = build_report_projection([])
    export_destination = tmp_path / "not-a-directory"
    export_destination.write_text("occupied", encoding="utf-8")

    with pytest.raises(ReportExportError, match="prepare report export directory"):
        export_report_pdf(
            projection,
            output_dir=str(export_destination),
            session_id="session-123",
        )


def test_export_report_pdf_wraps_reportlab_build_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projection = build_report_projection(_minimal_artifacts_without_inventory())

    def fail_build(self: object, flowables: object) -> None:
        raise RuntimeError("private paragraph body should not leak")

    monkeypatch.setattr(report_exporter.SimpleDocTemplate, "build", fail_build)

    with pytest.raises(ReportExportError, match="Report PDF rendering failed") as exc_info:
        export_report_pdf(projection, output_dir=str(tmp_path), session_id="session-123")

    assert "private paragraph body" not in str(exc_info.value)
    assert not list(tmp_path.glob("*.pdf"))


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _report_artifacts() -> list[dict[str, object]]:
    sources = [
        _source_entry(
            document_id="doc-indexed-report",
            original_filename="site-report.pdf",
            status="indexed",
            family="text_documents",
        ),
        _source_entry(
            document_id="doc-failed",
            original_filename="calc-failed.xlsx",
            status="failed",
            family="engineering_workbooks",
            error="workbook parser failed",
        ),
        _source_entry(
            document_id="doc-skipped",
            original_filename="photo.png",
            status="skipped",
            family="engineering_images",
            error="image_extractor_pending",
        ),
    ]
    return [
        _source_inventory_artifact(sources),
        _section_plan_artifact(),
        _retrieval_manifest_artifact(),
        _paragraph_artifact(
            section_id="grundlagen",
            paragraph_index=1,
            text="Maßgebliche Größe beträgt 12 kN für die geprüfte Grundlage.",
            evidence_manifest=[
                {
                    "memory_id": "mem-indexed-report",
                    "provenance": "[source=site-report.pdf; page=2; sheet=1; cell=A1]",
                },
                {
                    "memory_id": "mem-failed",
                    "provenance": "[source=calc-failed.xlsx; page=4; sheet=2; cell=B7]",
                },
            ],
        ),
        _paragraph_artifact(
            section_id="grundlagen",
            paragraph_index=2,
            text="Der wiederholte Nachweis verweist stabil auf dieselbe Quelle.",
            evidence_manifest=[
                {
                    "memory_id": "mem-indexed-report",
                    "provenance": "[source=site-report.pdf; page=2; sheet=1; cell=A1]",
                }
            ],
        ),
        _paragraph_artifact(
            section_id="unsicherheiten",
            paragraph_index=1,
            text="Übersprungene Bildquellen bleiben als Unsicherheit sichtbar.",
            evidence_manifest=[
                {
                    "memory_id": "mem-skipped",
                    "provenance": "[source=photo.png; page=8; sheet=1; cell=C3]",
                }
            ],
        ),
    ]


def _minimal_artifacts_without_inventory() -> list[dict[str, object]]:
    return [
        {
            "kind": "section_plan",
            "content": {
                "template_id": "general_project_dossier",
                "sections": [
                    _section_plan_entry(
                        section_id="grundlagen",
                        title="Grundlagen und ausgewertete Unterlagen",
                    )
                ],
            },
        },
        _paragraph_artifact(
            section_id="grundlagen",
            paragraph_index=1,
            text="Absatz mit Evidence-Link ohne Provenienz.",
            evidence_manifest=[],
        ),
    ]


def _projection_with_empty_provenance_evidence():
    projection = build_report_projection(_minimal_artifacts_without_inventory())
    section = projection.sections_by_id["grundlagen"]
    paragraph = ReportParagraphCitation(
        section_id="grundlagen",
        paragraph_index=1,
        text="Absatz mit Evidence-Link ohne Provenienz.",
        evidence_manifest=(
            ReportParagraphEvidence(memory_id="mem-without-provenance", provenance=""),
        ),
        no_evidence=False,
    )
    updated_section = replace(section, paragraph_citations=(paragraph,))
    return replace(
        projection,
        sections_by_id={**projection.sections_by_id, "grundlagen": updated_section},
    )


def _source_inventory_artifact(sources: list[dict[str, object]]) -> dict[str, object]:
    by_status: dict[str, list[dict[str, object]]] = {"indexed": [], "skipped": [], "failed": []}
    by_family: dict[str, list[dict[str, object]]] = {}
    for source in sources:
        status = str(source["status"])
        family = str(source["family"])
        by_status.setdefault(status, []).append(source)
        by_family.setdefault(family, []).append(source)
    return {
        "kind": "source_inventory_snapshot",
        "content": {
            "totals": {
                "indexed": len(by_status["indexed"]),
                "skipped": len(by_status["skipped"]),
                "failed": len(by_status["failed"]),
                "uploaded": 0,
                "processing": 0,
                "total": len(sources),
            },
            "by_status": by_status,
            "by_family": by_family,
        },
    }


def _section_plan_artifact() -> dict[str, object]:
    return {
        "kind": "section_plan",
        "content": {
            "template_id": "general_project_dossier",
            "sections": [
                _section_plan_entry(
                    section_id="grundlagen",
                    title="Grundlagen und ausgewertete Unterlagen",
                ),
                _section_plan_entry(
                    section_id="unsicherheiten",
                    title="Unsicherheiten, Widersprüche und fehlende Nachweise",
                    uncertainty_required=True,
                ),
                _section_plan_entry(section_id="anlagenverzeichnis", title="Anlagenverzeichnis"),
                _section_plan_entry(section_id="quellennachweise", title="Quellennachweise"),
            ],
        },
    }


def _retrieval_manifest_artifact() -> dict[str, object]:
    return {
        "kind": "other",
        "content": {
            "kind": "retrieval_manifest",
            "sections": [
                _retrieval_section(
                    section_id="grundlagen",
                    title="Grundlagen und ausgewertete Unterlagen",
                    memories=["mem-indexed-report", "mem-failed"],
                ),
                _retrieval_section(
                    section_id="unsicherheiten",
                    title="Unsicherheiten, Widersprüche und fehlende Nachweise",
                    memories=["mem-skipped"],
                ),
            ],
        },
    }


def _retrieval_section(
    *,
    section_id: str,
    title: str,
    memories: list[str],
) -> dict[str, object]:
    return {
        "id": section_id,
        "title": title,
        "queries": [
            {
                "family": "text_documents",
                "query": f"query for {section_id}",
                "hit_count": len(memories),
                "memory_ids": memories,
            }
        ],
        "recalled_memories": [_memory(memory_id) for memory_id in memories],
        "total_hit_count": len(memories),
    }


def _memory(memory_id: str) -> dict[str, object]:
    content_by_id = {
        "mem-indexed-report": "[source=site-report.pdf; page=2; sheet=1; cell=A1]\nText",
        "mem-failed": "[source=calc-failed.xlsx; page=4; sheet=2; cell=B7]\nText",
        "mem-skipped": "[source=photo.png; page=8; sheet=1; cell=C3]\nText",
    }
    return {
        "id": memory_id,
        "content": content_by_id[memory_id],
        "metadata": {},
        "score": 1.0,
        "families": ["text_documents"],
    }


def _paragraph_artifact(
    *,
    section_id: str,
    paragraph_index: int,
    text: str,
    evidence_manifest: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "kind": "paragraph_citations",
        "content": {
            "section_id": section_id,
            "paragraph_index": paragraph_index,
            "text": text,
            "evidence_manifest": evidence_manifest,
            "no_evidence": False,
        },
    }


def _section_plan_entry(
    *,
    section_id: str,
    title: str,
    uncertainty_required: bool = False,
) -> dict[str, object]:
    return {
        "id": section_id,
        "title": title,
        "mandatory": True,
        "evidence_families": ["text_documents", "engineering_workbooks", "engineering_images"],
        "uncertainty_required": uncertainty_required,
        "active": True,
        "reason": None,
    }


def _source_entry(
    *,
    document_id: str,
    original_filename: str,
    status: str,
    family: str,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "original_filename": original_filename,
        "status": status,
        "family": family,
        "error": error,
    }
