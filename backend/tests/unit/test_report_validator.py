"""Tests for deterministic report projection and validation rules."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from app.services.report_projection import (
    APPENDIX_SECTION_IDS,
    GRUNDLAGEN_SECTION_ID,
    REPORT_DRAFT_BANNER,
    UNSICHERHEITEN_SECTION_ID,
    build_report_projection,
)
from app.services.report_validator import validate_report_artifacts, validate_report_projection

SOURCE_FAMILIES = (
    "text_documents",
    "engineering_documents",
    "engineering_workbooks",
    "cad_exports",
    "engineering_images",
    "backup_or_temp",
    "unsupported",
)
SOURCE_STATUSES = ("indexed", "skipped", "failed")


class TestReportProjection:
    def test_build_report_projection_groups_artifacts_by_section_id(self) -> None:
        projection = build_report_projection(_clean_artifacts())

        assert projection.section_order == (
            "grundlagen",
            UNSICHERHEITEN_SECTION_ID,
            "anlagenverzeichnis",
            "quellennachweise",
            "berechnungen",
        )
        assert projection.paragraph_citations_present is True
        assert projection.source_inventory.present is True
        assert projection.section_plan.present is True
        assert projection.retrieval_manifest.present is True
        assert projection.source_inventory.totals == {
            "indexed": 2,
            "skipped": 1,
            "failed": 1,
            "uploaded": 0,
            "processing": 0,
            "total": 4,
        }
        assert [entry.document_id for entry in projection.source_inventory.by_status["failed"]] == [
            "doc-failed",
        ]
        assert [
            entry.document_id for entry in projection.source_inventory.by_status["skipped"]
        ] == [
            "doc-skipped",
        ]
        assert [
            entry.id for entry in projection.sections_by_id[GRUNDLAGEN_SECTION_ID].recalled_memories
        ] == [
            "mem-indexed-report",
            "mem-failed",
            "mem-skipped",
        ]
        assert [
            evidence.memory_id
            for evidence in projection.sections_by_id[UNSICHERHEITEN_SECTION_ID]
            .paragraph_citations[0]
            .evidence_manifest
        ] == ["mem-failed", "mem-skipped"]


class TestReportValidator:
    def test_clean_projection_returns_only_appendix_consistency_info(self) -> None:
        projection = build_report_projection(_clean_artifacts())

        findings = validate_report_projection(projection)

        assert [finding["severity"] for finding in findings] == ["info"]
        assert [finding["code"] for finding in findings] == [
            "appendix_source_inventory_consistent",
        ]
        assert findings[0]["payload"] == {
            "appendix_section_ids": list(APPENDIX_SECTION_IDS),
            "indexed_count": 2,
            "skipped_count": 1,
            "failed_count": 1,
            "total_count": 4,
        }

    def test_missing_uncertainty_emits_blocker(self) -> None:
        projection = build_report_projection(_artifacts_without_uncertainty())

        findings = validate_report_projection(projection)

        assert any(finding["code"] == "mandatory_uncertainty_missing" for finding in findings)
        assert any(finding["severity"] == "blocker" for finding in findings)
        assert projection.sections_by_id[UNSICHERHEITEN_SECTION_ID].paragraph_citations == ()

    def test_missing_non_certification_notice_emits_blocker(self) -> None:
        projection = replace(
            build_report_projection(_clean_artifacts()),
            non_certification_notice="Dieser Bericht ist ein Entwurf ohne Prüfhinweis.",
        )

        findings = validate_report_projection(projection)

        assert any(
            finding["code"] == "non_certification_notice_missing_or_altered" for finding in findings
        )
        assert any(finding["severity"] == "blocker" for finding in findings)
        assert (
            projection.non_certification_notice
            == "Dieser Bericht ist ein Entwurf ohne Prüfhinweis."
        )
        assert projection.draft_banner == REPORT_DRAFT_BANNER

    def test_failed_and_skipped_sources_must_be_visible(self) -> None:
        projection = build_report_projection(_artifacts_without_failed_skipped_visibility())

        findings = validate_report_projection(projection)
        blocker_codes = [
            finding["code"] for finding in findings if finding["severity"] == "blocker"
        ]

        assert blocker_codes.count("failed_skipped_source_not_visible") == 2
        assert {
            finding["payload"]["status"]
            for finding in findings
            if finding["code"] == "failed_skipped_source_not_visible"
        } == {
            "failed",
            "skipped",
        }
        assert all(
            finding["payload"]["visible_in_sections"] == []
            for finding in findings
            if finding["code"] == "failed_skipped_source_not_visible"
        )

    def test_malformed_and_empty_artifacts_produce_findings_without_crashing(self) -> None:
        bad_artifacts = [
            {"kind": "source_inventory_snapshot", "content": "not a mapping"},
            {
                "kind": "section_plan",
                "content": {
                    "template_id": "general_project_dossier",
                    "sections": [
                        {
                            "id": "",
                            "title": 123,
                            "mandatory": "yes",
                            "evidence_families": "bad",
                            "uncertainty_required": "yes",
                            "active": "no",
                            "reason": None,
                        }
                    ],
                },
            },
            {"kind": "other", "content": {"kind": "wrong", "sections": "nope"}},
            {
                "kind": "paragraph_citations",
                "content": {
                    "section_id": "",
                    "paragraph_index": "two",
                    "text": None,
                    "evidence_manifest": "oops",
                    "no_evidence": "false",
                },
            },
            {"kind": "unexpected_kind", "content": {"foo": "bar"}},
        ]

        projection = build_report_projection(bad_artifacts)
        findings = validate_report_artifacts(bad_artifacts)
        codes = {finding["code"] for finding in findings}

        assert projection.source_inventory.present is True
        assert projection.section_plan.present is True
        assert projection.retrieval_manifest.present is False
        assert projection.paragraph_citations_present is True
        assert projection.source_inventory.by_status == {}
        assert projection.section_plan.sections == ()
        assert projection.sections_by_id == {}
        assert {
            "source_inventory_malformed",
            "source_inventory_by_family_missing",
            "source_inventory_by_status_missing",
            "source_inventory_totals_missing",
            "section_plan_sections_missing",
            "retrieval_manifest_missing",
            "paragraph_citation_missing_section_id",
            "unknown_artifact_kind",
        }.issubset(codes)
        assert any(finding["severity"] == "blocker" for finding in findings)

    def test_citation_coverage_warns_when_evidence_manifest_is_missing(self) -> None:
        artifacts = _clean_artifacts()
        grondlagen = _paragraph_artifact(
            section_id=GRUNDLAGEN_SECTION_ID,
            paragraph_index=1,
            text="Die Unterlagenlage ist nachvollziehbar und vollständig dokumentiert.",
            evidence_manifest=[],
        )
        artifacts = _replace_artifact(
            artifacts, "paragraph_citations", GRUNDLAGEN_SECTION_ID, grondlagen
        )

        findings = validate_report_projection(build_report_projection(artifacts))

        citation_findings = [
            finding for finding in findings if finding["code"] == "citation_coverage_gap"
        ]
        assert len(citation_findings) == 1
        assert citation_findings[0]["severity"] == "warning"
        assert citation_findings[0]["payload"] == {
            "section_id": GRUNDLAGEN_SECTION_ID,
            "paragraph_index": 1,
            "evidence_count": 0,
        }

    def test_numeric_provenance_warns_without_exposing_paragraph_text(self) -> None:
        artifacts = _clean_artifacts()
        private_text = (
            "Interne Notiz: Der sensible Bauteilvermerk darf nicht im Finding "
            "erscheinen. Die maßgebliche Last beträgt 12 kN. "
            "Weitere vertrauliche Erläuterungen bleiben ausschließlich im Absatz."
        )
        berechnungen = _paragraph_artifact(
            section_id="berechnungen",
            paragraph_index=1,
            text=private_text,
            evidence_manifest=[
                {
                    "memory_id": "mem-calc",
                    "provenance": "[source=calc.xlsx]",
                }
            ],
        )
        artifacts = _replace_artifact(
            artifacts, "paragraph_citations", "berechnungen", berechnungen
        )

        findings = validate_report_projection(build_report_projection(artifacts))
        warning = next(
            finding for finding in findings if finding["code"] == "numeric_provenance_weak"
        )

        assert warning["severity"] == "warning"
        assert warning["payload"]["section_id"] == "berechnungen"
        assert warning["payload"]["paragraph_index"] == 1
        assert warning["payload"]["numeric_claims"] == ["12 kN"]
        assert warning["payload"]["provenance_snippets"] == ["[source=calc.xlsx]"]
        assert "sensible Bauteilvermerk" not in str(warning["payload"])
        assert private_text not in str(warning["payload"])


def _clean_artifacts() -> list[dict[str, object]]:
    sources = [
        _source_entry(
            document_id="doc-indexed-report",
            original_filename="site-report.pdf",
            status="indexed",
            family="text_documents",
        ),
        _source_entry(
            document_id="doc-calc",
            original_filename="calc.xlsx",
            status="indexed",
            family="engineering_workbooks",
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
            section_id=GRUNDLAGEN_SECTION_ID,
            paragraph_index=1,
            text=(
                "Die Unterlagenlage berücksichtigt geprüfte, fehlgeschlagene und "
                "übersprungene Quellen."
            ),
            evidence_manifest=[
                {
                    "memory_id": "mem-indexed-report",
                    "provenance": "[source=site-report.pdf; page=2; sheet=1; cell=A1]",
                },
                {
                    "memory_id": "mem-failed",
                    "provenance": "[source=calc-failed.xlsx; page=4; sheet=2; cell=B7]",
                },
                {
                    "memory_id": "mem-skipped",
                    "provenance": "[source=photo.png; page=8; sheet=1; cell=C3]",
                },
            ],
        ),
        _paragraph_artifact(
            section_id=UNSICHERHEITEN_SECTION_ID,
            paragraph_index=1,
            text="Es bleiben Unsicherheiten zu den fehlerbehafteten und übersprungenen Quellen.",
            evidence_manifest=[
                {
                    "memory_id": "mem-failed",
                    "provenance": "[source=calc-failed.xlsx; page=4; sheet=2; cell=B7]",
                },
                {
                    "memory_id": "mem-skipped",
                    "provenance": "[source=photo.png; page=8; sheet=1; cell=C3]",
                },
            ],
        ),
        _paragraph_artifact(
            section_id="berechnungen",
            paragraph_index=1,
            text="Die maßgebliche Last beträgt 12 kN.",
            evidence_manifest=[
                {
                    "memory_id": "mem-calc",
                    "provenance": "[source=calc.xlsx; page=4; sheet=2; cell=B7]",
                }
            ],
        ),
    ]


def _artifacts_without_uncertainty() -> list[dict[str, object]]:
    artifacts = deepcopy(_clean_artifacts())
    return [
        artifact
        for artifact in artifacts
        if not (
            artifact["kind"] == "paragraph_citations"
            and artifact["content"]["section_id"] == UNSICHERHEITEN_SECTION_ID
        )
    ]


def _artifacts_without_failed_skipped_visibility() -> list[dict[str, object]]:
    artifacts = deepcopy(_clean_artifacts())
    replacements = {
        GRUNDLAGEN_SECTION_ID: _paragraph_artifact(
            section_id=GRUNDLAGEN_SECTION_ID,
            paragraph_index=1,
            text="Die Unterlagenlage ist nachvollziehbar und vollständig dokumentiert.",
            evidence_manifest=[
                {
                    "memory_id": "mem-indexed-report",
                    "provenance": "[source=site-report.pdf; page=2; sheet=1; cell=A1]",
                }
            ],
        ),
        UNSICHERHEITEN_SECTION_ID: _paragraph_artifact(
            section_id=UNSICHERHEITEN_SECTION_ID,
            paragraph_index=1,
            text="Es bleiben methodische Unsicherheiten im Bericht.",
            evidence_manifest=[
                {
                    "memory_id": "mem-indexed-report",
                    "provenance": "[source=site-report.pdf; page=2; sheet=1; cell=A1]",
                }
            ],
        ),
    }
    for section_id, artifact in replacements.items():
        artifacts = _replace_artifact(artifacts, "paragraph_citations", section_id, artifact)
    return artifacts


def _replace_artifact(
    artifacts: list[dict[str, object]],
    kind: str,
    section_id: str,
    replacement: dict[str, object],
) -> list[dict[str, object]]:
    updated = deepcopy(artifacts)
    for index, artifact in enumerate(updated):
        if artifact["kind"] != kind:
            continue
        content = artifact.get("content")
        if isinstance(content, dict) and content.get("section_id") == section_id:
            updated[index] = replacement
            break
    return updated


def _source_inventory_artifact(sources: list[dict[str, object]]) -> dict[str, object]:
    by_family: dict[str, list[dict[str, object]]] = {family: [] for family in SOURCE_FAMILIES}
    by_status: dict[str, list[dict[str, object]]] = {status: [] for status in SOURCE_STATUSES}

    for source in sources:
        entry = _source_entry(**source)
        family = entry["family"]
        status = entry["status"]
        by_family.setdefault(family, []).append(entry)
        by_status.setdefault(status, []).append(entry)

    totals = {status: len(by_status.get(status, [])) for status in SOURCE_STATUSES}
    totals["uploaded"] = 0
    totals["processing"] = 0
    totals["total"] = len(sources)

    return {
        "kind": "source_inventory_snapshot",
        "content": {
            "totals": totals,
            "by_family": by_family,
            "by_status": by_status,
        },
    }


def _section_plan_artifact() -> dict[str, object]:
    return {
        "kind": "section_plan",
        "content": {
            "template_id": "general_project_dossier",
            "sections": [
                _section_plan_entry(
                    section_id=GRUNDLAGEN_SECTION_ID,
                    title="Grundlagen und ausgewertete Unterlagen",
                    mandatory=True,
                    evidence_families=[
                        "text_documents",
                        "engineering_documents",
                        "engineering_workbooks",
                        "cad_exports",
                        "engineering_images",
                        "backup_or_temp",
                        "unsupported",
                    ],
                    uncertainty_required=False,
                    active=True,
                ),
                _section_plan_entry(
                    section_id=UNSICHERHEITEN_SECTION_ID,
                    title="Unsicherheiten, Widersprueche und fehlende Nachweise",
                    mandatory=True,
                    evidence_families=[
                        "text_documents",
                        "engineering_documents",
                        "engineering_workbooks",
                        "cad_exports",
                        "engineering_images",
                        "backup_or_temp",
                        "unsupported",
                    ],
                    uncertainty_required=True,
                    active=True,
                ),
                _section_plan_entry(
                    section_id="anlagenverzeichnis",
                    title="Anlagenverzeichnis",
                    mandatory=True,
                    evidence_families=[
                        "text_documents",
                        "engineering_documents",
                        "engineering_workbooks",
                        "cad_exports",
                        "engineering_images",
                        "backup_or_temp",
                        "unsupported",
                    ],
                    uncertainty_required=False,
                    active=True,
                ),
                _section_plan_entry(
                    section_id="quellennachweise",
                    title="Quellennachweise",
                    mandatory=True,
                    evidence_families=[
                        "text_documents",
                        "engineering_documents",
                        "engineering_workbooks",
                        "cad_exports",
                        "engineering_images",
                        "backup_or_temp",
                        "unsupported",
                    ],
                    uncertainty_required=False,
                    active=True,
                ),
                _section_plan_entry(
                    section_id="berechnungen",
                    title="Berechnungen, Tabellen und Werte",
                    mandatory=True,
                    evidence_families=["text_documents", "engineering_workbooks"],
                    uncertainty_required=False,
                    active=True,
                ),
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
                    section_id=GRUNDLAGEN_SECTION_ID,
                    title="Grundlagen und ausgewertete Unterlagen",
                    memories=["mem-indexed-report", "mem-failed", "mem-skipped"],
                    hit_count=3,
                ),
                _retrieval_section(
                    section_id=UNSICHERHEITEN_SECTION_ID,
                    title="Unsicherheiten, Widersprueche und fehlende Nachweise",
                    memories=["mem-failed", "mem-skipped"],
                    hit_count=2,
                ),
                _retrieval_section(
                    section_id="berechnungen",
                    title="Berechnungen, Tabellen und Werte",
                    memories=["mem-calc"],
                    hit_count=1,
                ),
                _retrieval_section(
                    section_id="anlagenverzeichnis",
                    title="Anlagenverzeichnis",
                    memories=[],
                    hit_count=0,
                ),
                _retrieval_section(
                    section_id="quellennachweise",
                    title="Quellennachweise",
                    memories=[],
                    hit_count=0,
                ),
            ],
        },
    }


def _retrieval_section(
    *,
    section_id: str,
    title: str,
    memories: list[str],
    hit_count: int,
) -> dict[str, object]:
    return {
        "id": section_id,
        "title": title,
        "queries": [
            {
                "family": "text_documents",
                "query": f"query for {section_id}",
                "hit_count": hit_count,
                "memory_ids": memories,
            }
        ],
        "recalled_memories": [_retrieved_memory(memory_id) for memory_id in memories],
        "total_hit_count": hit_count,
    }


def _retrieved_memory(memory_id: str) -> dict[str, object]:
    memory_map = {
        "mem-indexed-report": {
            "content": (
                "[source=site-report.pdf; page=2; sheet=1; cell=A1]\n"
                "Die Unterlagenlage ist nachvollziehbar."
            ),
            "metadata": {
                "document_id": "doc-indexed-report",
                "source": "site-report.pdf",
            },
        },
        "mem-calc": {
            "content": "[source=calc.xlsx; page=4; sheet=2; cell=B7]\nDie Last beträgt 12 kN.",
            "metadata": {
                "document_id": "doc-calc",
                "source": "calc.xlsx",
            },
        },
        "mem-failed": {
            "content": (
                "[source=calc-failed.xlsx; page=4; sheet=2; cell=B7]\n"
                "Die fehlerhafte Tabelle wird dokumentiert."
            ),
            "metadata": {
                "document_id": "doc-failed",
                "source": "calc-failed.xlsx",
            },
        },
        "mem-skipped": {
            "content": (
                "[source=photo.png; page=8; sheet=1; cell=C3]\n"
                "Die übersprungene Aufnahme wird dokumentiert."
            ),
            "metadata": {
                "document_id": "doc-skipped",
                "source": "photo.png",
            },
        },
    }
    template = memory_map[memory_id]
    return {
        "id": memory_id,
        "content": template["content"],
        "metadata": template["metadata"],
        "score": 1.0,
        "families": ["text_documents"],
    }


def _paragraph_artifact(
    *,
    section_id: str,
    paragraph_index: int,
    text: str,
    evidence_manifest: list[dict[str, object]],
    no_evidence: bool = False,
) -> dict[str, object]:
    return {
        "kind": "paragraph_citations",
        "content": {
            "section_id": section_id,
            "paragraph_index": paragraph_index,
            "text": text,
            "evidence_manifest": evidence_manifest,
            "no_evidence": no_evidence,
        },
    }


def _section_plan_entry(
    *,
    section_id: str,
    title: str,
    mandatory: bool,
    evidence_families: list[str],
    uncertainty_required: bool,
    active: bool,
) -> dict[str, object]:
    return {
        "id": section_id,
        "title": title,
        "mandatory": mandatory,
        "evidence_families": evidence_families,
        "uncertainty_required": uncertainty_required,
        "active": active,
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
