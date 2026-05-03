"""Tests for the pure report planner helpers."""

from __future__ import annotations

from typing import cast

from app.services.document_registry import DocumentRecord, DocumentStatus
from app.services.report_planner import (
    GENERAL_PROJECT_DOSSIER_SECTIONS,
    ReportSectionTemplate,
    build_general_project_dossier_section_plan,
    build_source_inventory,
)


class TestBuildSourceInventory:
    def test_groups_records_by_family_and_status(self) -> None:
        records = [
            _record(
                document_id="doc-pdf",
                original_filename="site-report.pdf",
                status="indexed",
            ),
            _record(
                document_id="doc-docx",
                original_filename="design-note.docx",
                status="indexed",
            ),
            _record(
                document_id="doc-xlsx",
                original_filename="calculation.xlsx",
                status="failed",
                error="workbook parser failed",
            ),
            _record(
                document_id="doc-dwg",
                original_filename="drawing.dwg",
                status="indexed",
            ),
            _record(
                document_id="doc-png",
                original_filename="photo.png",
                status="skipped",
                error="image_extractor_pending",
            ),
        ]

        inventory = build_source_inventory(records)

        assert inventory["totals"] == {
            "indexed": 3,
            "skipped": 1,
            "failed": 1,
            "uploaded": 0,
            "processing": 0,
            "total": 5,
        }
        assert [entry["document_id"] for entry in inventory["by_family"]["text_documents"]] == [
            "doc-pdf",
        ]
        assert [
            entry["document_id"] for entry in inventory["by_family"]["engineering_documents"]
        ] == ["doc-docx"]
        assert [
            entry["document_id"] for entry in inventory["by_family"]["engineering_workbooks"]
        ] == ["doc-xlsx"]
        assert [entry["document_id"] for entry in inventory["by_family"]["cad_exports"]] == [
            "doc-dwg",
        ]
        assert [
            entry["document_id"] for entry in inventory["by_family"]["engineering_images"]
        ] == ["doc-png"]
        assert [entry["document_id"] for entry in inventory["by_status"]["indexed"]] == [
            "doc-pdf",
            "doc-docx",
            "doc-dwg",
        ]
        assert [entry["document_id"] for entry in inventory["by_status"]["skipped"]] == [
            "doc-png",
        ]
        assert [entry["document_id"] for entry in inventory["by_status"]["failed"]] == [
            "doc-xlsx",
        ]

    def test_includes_failed_and_skipped_with_error_text(self) -> None:
        records = [
            _record(
                document_id="doc-failed",
                original_filename="calc.xlsx",
                status="failed",
                error="workbook parser failed",
            ),
            _record(
                document_id="doc-skipped",
                original_filename="photo.png",
                status="skipped",
                error="image_extractor_pending",
            ),
        ]

        inventory = build_source_inventory(records)

        assert inventory["by_status"]["failed"][0]["error"] == "workbook parser failed"
        assert inventory["by_status"]["skipped"][0]["error"] == "image_extractor_pending"
        assert inventory["by_family"]["engineering_workbooks"][0]["error"] == (
            "workbook parser failed"
        )
        assert inventory["by_family"]["engineering_images"][0]["error"] == (
            "image_extractor_pending"
        )

    def test_does_not_leak_stored_path_or_memory_ids(self) -> None:
        inventory = build_source_inventory(
            [
                _record(
                    document_id="doc-leak",
                    original_filename="notes.pdf",
                    status="indexed",
                    stored_path="/secret/path/notes.pdf",
                    memory_ids=["memory-1", "memory-2"],
                )
            ]
        )

        entry = inventory["by_family"]["text_documents"][0]

        assert set(entry) == {"document_id", "original_filename", "status", "error", "family"}
        assert "stored_path" not in entry
        assert "content_hash" not in entry
        assert "byte_size" not in entry
        assert "memory_ids" not in entry

    def test_empty_records_returns_zero_totals(self) -> None:
        inventory = build_source_inventory([])

        assert inventory["totals"] == {
            "indexed": 0,
            "skipped": 0,
            "failed": 0,
            "uploaded": 0,
            "processing": 0,
            "total": 0,
        }
        assert all(not entries for entries in inventory["by_family"].values())
        assert all(not entries for entries in inventory["by_status"].values())


class TestBuildGeneralProjectDossierSectionPlan:
    def test_emits_all_fourteen_base_sections(self) -> None:
        plan = build_general_project_dossier_section_plan(build_source_inventory([]))

        assert plan["template_id"] == "general_project_dossier"
        assert len(plan["sections"]) == 14
        assert [section["id"] for section in plan["sections"]] == [
            template.id for template in GENERAL_PROJECT_DOSSIER_SECTIONS
        ]

        mandatory_sections = {
            template.id for template in GENERAL_PROJECT_DOSSIER_SECTIONS if template.mandatory
        }
        for section in plan["sections"]:
            if section["id"] in mandatory_sections:
                assert section["active"] is True
                assert section["reason"] is None

    def test_baugrund_active_only_when_geotechnical_evidence_exists(self) -> None:
        template = _section_template("baugrund")

        empty_plan = build_general_project_dossier_section_plan(build_source_inventory([]))
        empty_section = _section(empty_plan, "baugrund")

        assert empty_section["active"] is False
        assert empty_section["reason"] == _inactive_reason(template)

        inventory = build_source_inventory(_records_for_families(template.evidence_families))
        active_section = _section(
            build_general_project_dossier_section_plan(inventory),
            "baugrund",
        )

        assert active_section["active"] is True
        assert active_section["reason"] is None

    def test_tragwerk_active_only_when_statics_evidence_exists(self) -> None:
        template = _section_template("tragwerk")

        empty_section = _section(
            build_general_project_dossier_section_plan(build_source_inventory([])),
            "tragwerk",
        )
        assert empty_section["active"] is False
        assert empty_section["reason"] == _inactive_reason(template)

        inventory = build_source_inventory(_records_for_families(template.evidence_families))
        active_section = _section(
            build_general_project_dossier_section_plan(inventory),
            "tragwerk",
        )

        assert active_section["active"] is True
        assert active_section["reason"] is None

    def test_ausfuehrung_active_only_when_closeout_evidence_exists(self) -> None:
        template = _section_template("ausfuehrung")

        empty_section = _section(
            build_general_project_dossier_section_plan(build_source_inventory([])),
            "ausfuehrung",
        )
        assert empty_section["active"] is False
        assert empty_section["reason"] == _inactive_reason(template)

        inventory = build_source_inventory(_records_for_families(template.evidence_families))
        active_section = _section(
            build_general_project_dossier_section_plan(inventory),
            "ausfuehrung",
        )

        assert active_section["active"] is True
        assert active_section["reason"] is None

    def test_uncertainty_section_is_mandatory_and_uncertainty_required_true(self) -> None:
        section = _section(
            build_general_project_dossier_section_plan(build_source_inventory([])),
            "unsicherheiten",
        )

        assert section["mandatory"] is True
        assert section["uncertainty_required"] is True
        assert section["active"] is True


def _record(
    *,
    document_id: str,
    original_filename: str,
    status: DocumentStatus,
    error: str | None = None,
    stored_path: str = "/app/data/documents/sample",
    memory_ids: list[str] | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        content_hash=f"hash-{document_id}",
        original_filename=original_filename,
        stored_path=stored_path,
        content_type="application/octet-stream",
        byte_size=1,
        uploaded_at="2026-05-03T00:00:00+00:00",
        status=status,
        error=error,
        memory_ids=[] if memory_ids is None else memory_ids,
    )


def _records_for_families(families: tuple[str, ...]) -> list[DocumentRecord]:
    records: list[DocumentRecord] = []
    for index, family in enumerate(families, start=1):
        if family not in _INDEXABLE_SAMPLE_FILENAMES:
            continue
        records.append(
            _record(
                document_id=f"doc-{family}-{index}",
                original_filename=_INDEXABLE_SAMPLE_FILENAMES[family],
                status="indexed",
            )
        )
    return records


def _section(plan: dict[str, object], section_id: str) -> dict[str, object]:
    sections = cast(list[dict[str, object]], plan["sections"])
    for section in sections:
        if section["id"] == section_id:
            return section
    raise AssertionError(f"missing section {section_id}")


def _section_template(section_id: str) -> ReportSectionTemplate:
    for template in GENERAL_PROJECT_DOSSIER_SECTIONS:
        if template.id == section_id:
            return template
    raise AssertionError(f"missing template {section_id}")


def _inactive_reason(template: ReportSectionTemplate) -> str:
    return f"no indexed evidence for families: {', '.join(template.evidence_families)}"


_INDEXABLE_SAMPLE_FILENAMES = {
    "text_documents": "evidence.pdf",
    "engineering_documents": "evidence.docx",
    "engineering_workbooks": "evidence.xlsx",
    "cad_exports": "evidence.dwg",
}
