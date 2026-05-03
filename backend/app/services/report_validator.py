"""Pure validation rules for deterministic report projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.report_projection import (
    APPENDIX_SECTION_IDS,
    REPORT_DRAFT_BANNER,
    REPORT_NON_CERTIFICATION_NOTICE,
    SUPPORT_SECTION_IDS,
    UNSICHERHEITEN_SECTION_ID,
    ReportParagraphCitation,
    ReportProjection,
    ReportRetrievedMemory,
    ReportSectionProjection,
    ReportSourceEntry,
    make_finding,
)

_NUMERIC_CLAIM_RE = re.compile(r"\b\d+(?:[.,]\d+)?(?:\s?(?:%|m|cm|mm|kN|MN|t|kg|°C))?\b")
_PROVENANCE_DETAIL_HINTS: tuple[str, ...] = (
    "page=",
    "sheet=",
    "cell=",
    "row=",
    "line=",
    "table=",
    "figure=",
)


def validate_report_projection(projection: ReportProjection) -> list[dict[str, Any]]:
    """Validate a normalized report projection and return JSON-ready findings."""
    findings = [dict(finding) for finding in projection.normalization_findings]

    findings.extend(_validate_required_artifacts(projection))
    findings.extend(_validate_static_notices(projection))
    findings.extend(_validate_appendix_consistency(projection))

    scan = _scan_sections(projection)
    findings.extend(scan.paragraph_findings)
    findings.extend(_validate_uncertainty(projection))
    findings.extend(
        _validate_failed_skipped_visibility(projection, scan.visible_source_keys_by_section)
    )

    if not projection.paragraph_citations_present:
        findings.append(
            make_finding(
                "blocker",
                "paragraph_citations_missing",
                "No paragraph citation artifacts were available for validation.",
                {},
            )
        )

    return findings


def validate_report_artifacts(artifacts: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    """Convenience helper that projects and validates raw artifact records."""
    from app.services.report_projection import build_report_projection

    return validate_report_projection(build_report_projection(artifacts))


def _validate_required_artifacts(projection: ReportProjection) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    if not projection.source_inventory.present:
        findings.append(
            make_finding(
                "blocker",
                "source_inventory_missing",
                "The source inventory snapshot is missing.",
                {
                    "artifact_kind": "source_inventory_snapshot",
                },
            )
        )
    if not projection.section_plan.present:
        findings.append(
            make_finding(
                "blocker",
                "section_plan_missing",
                "The section plan is missing.",
                {
                    "artifact_kind": "section_plan",
                },
            )
        )
    if not projection.retrieval_manifest.present:
        findings.append(
            make_finding(
                "blocker",
                "retrieval_manifest_missing",
                "The retrieval manifest is missing.",
                {
                    "artifact_kind": "other",
                    "content_kind": "retrieval_manifest",
                },
            )
        )

    return findings


def _validate_static_notices(projection: ReportProjection) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    if projection.draft_banner != REPORT_DRAFT_BANNER:
        findings.append(
            make_finding(
                "blocker",
                "draft_banner_missing_or_altered",
                "The required draft banner is missing or altered.",
                {
                    "expected": REPORT_DRAFT_BANNER,
                    "actual": projection.draft_banner,
                },
            )
        )

    if projection.non_certification_notice != REPORT_NON_CERTIFICATION_NOTICE:
        findings.append(
            make_finding(
                "blocker",
                "non_certification_notice_missing_or_altered",
                "The non-certification notice is missing or altered.",
                {
                    "expected": REPORT_NON_CERTIFICATION_NOTICE,
                    "actual": projection.non_certification_notice,
                },
            )
        )

    return findings


def _validate_appendix_consistency(projection: ReportProjection) -> list[dict[str, Any]]:
    if not projection.source_inventory.present:
        return []
    if not projection.section_plan.present:
        return []

    present_ids = [
        section_id for section_id in APPENDIX_SECTION_IDS if section_id in projection.sections_by_id
    ]
    missing_ids = [
        section_id
        for section_id in APPENDIX_SECTION_IDS
        if section_id not in projection.sections_by_id
    ]
    inventory_totals = projection.source_inventory.totals

    if not missing_ids:
        return [
            make_finding(
                "info",
                "appendix_source_inventory_consistent",
                "The source inventory and appendix sections are consistent.",
                {
                    "appendix_section_ids": present_ids,
                    "indexed_count": inventory_totals.get("indexed", 0),
                    "skipped_count": inventory_totals.get("skipped", 0),
                    "failed_count": inventory_totals.get("failed", 0),
                    "total_count": inventory_totals.get("total", 0),
                },
            )
        ]

    return [
        make_finding(
            "warning",
            "appendix_source_inventory_incomplete",
            "The appendix sections are incomplete for the available source inventory.",
            {
                "present_section_ids": present_ids,
                "missing_section_ids": missing_ids,
                "indexed_count": inventory_totals.get("indexed", 0),
                "skipped_count": inventory_totals.get("skipped", 0),
                "failed_count": inventory_totals.get("failed", 0),
                "total_count": inventory_totals.get("total", 0),
            },
        )
    ]


def _validate_uncertainty(projection: ReportProjection) -> list[dict[str, Any]]:
    section = projection.sections_by_id.get(UNSICHERHEITEN_SECTION_ID)
    if section is None:
        return [
            make_finding(
                "blocker",
                "mandatory_uncertainty_missing",
                "The mandatory uncertainty section is missing.",
                {
                    "section_id": UNSICHERHEITEN_SECTION_ID,
                },
            )
        ]

    if not section.plan_present or not section.active or not section.uncertainty_required:
        return [
            make_finding(
                "blocker",
                "mandatory_uncertainty_missing",
                "The mandatory uncertainty section is not configured correctly.",
                {
                    "section_id": UNSICHERHEITEN_SECTION_ID,
                    "plan_present": section.plan_present,
                    "active": section.active,
                    "uncertainty_required": section.uncertainty_required,
                },
            )
        ]

    if any(paragraph.text.strip() for paragraph in section.paragraph_citations):
        return []

    return [
        make_finding(
            "blocker",
            "mandatory_uncertainty_missing",
            "The mandatory uncertainty section does not contain any rendered text.",
            {
                "section_id": UNSICHERHEITEN_SECTION_ID,
                "paragraph_count": len(section.paragraph_citations),
            },
        )
    ]


@dataclass(frozen=True, slots=True)
class _SectionScanResult:
    paragraph_findings: list[dict[str, Any]]
    visible_source_keys_by_section: dict[str, set[tuple[str, str]]]


def _scan_sections(projection: ReportProjection) -> _SectionScanResult:
    paragraph_findings: list[dict[str, Any]] = []
    visible_source_keys_by_section: dict[str, set[tuple[str, str]]] = {
        section_id: set() for section_id in SUPPORT_SECTION_IDS
    }

    for section_id in projection.section_order:
        section = projection.sections_by_id.get(section_id)
        if section is None:
            continue

        for paragraph in section.paragraph_citations:
            paragraph_findings.extend(_validate_paragraph(section, paragraph, projection))
            if section_id not in SUPPORT_SECTION_IDS:
                continue
            for evidence in paragraph.evidence_manifest:
                memory = projection.retrieved_memories_by_id.get(evidence.memory_id)
                if memory is None:
                    continue
                key = _memory_source_key(memory)
                if key is not None:
                    visible_source_keys_by_section[section_id].add(key)

    return _SectionScanResult(
        paragraph_findings=paragraph_findings,
        visible_source_keys_by_section=visible_source_keys_by_section,
    )


def _validate_paragraph(
    section: ReportSectionProjection,
    paragraph: ReportParagraphCitation,
    projection: ReportProjection,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = paragraph.text.strip()

    if not text and not paragraph.no_evidence:
        findings.append(
            make_finding(
                "warning",
                "paragraph_text_missing",
                "A paragraph citation is missing text.",
                {
                    "section_id": section.id,
                    "paragraph_index": paragraph.paragraph_index,
                },
            )
        )
        return findings

    if text and not paragraph.no_evidence:
        missing_memory_ids = [
            evidence.memory_id
            for evidence in paragraph.evidence_manifest
            if evidence.memory_id not in projection.retrieved_memories_by_id
        ]
        if not paragraph.evidence_manifest or missing_memory_ids:
            payload: dict[str, Any] = {
                "section_id": section.id,
                "paragraph_index": paragraph.paragraph_index,
                "evidence_count": len(paragraph.evidence_manifest),
            }
            if missing_memory_ids:
                payload["missing_memory_ids"] = missing_memory_ids
            findings.append(
                make_finding(
                    "warning",
                    "citation_coverage_gap",
                    "A paragraph citation does not have full evidence coverage.",
                    payload,
                )
            )

        if _paragraph_looks_numeric(text) and not any(
            _evidence_provenance_has_location(evidence.provenance)
            for evidence in paragraph.evidence_manifest
        ):
            findings.append(
                make_finding(
                    "warning",
                    "numeric_provenance_weak",
                    "A numeric claim is missing page, sheet, cell, or similar provenance detail.",
                    {
                        "section_id": section.id,
                        "paragraph_index": paragraph.paragraph_index,
                        "numeric_claims": _numeric_claim_samples(text),
                        "provenance_snippets": [
                            evidence.provenance for evidence in paragraph.evidence_manifest[:3]
                        ],
                    },
                )
            )

    return findings


def _validate_failed_skipped_visibility(
    projection: ReportProjection,
    visible_source_keys_by_section: dict[str, set[tuple[str, str]]],
) -> list[dict[str, Any]]:
    if not projection.retrieval_manifest.present:
        return []

    findings: list[dict[str, Any]] = []
    failed_sources = projection.source_inventory.by_status.get("failed", ())
    skipped_sources = projection.source_inventory.by_status.get("skipped", ())

    for source in (*failed_sources, *skipped_sources):
        visible_sections = [
            section_id
            for section_id in SUPPORT_SECTION_IDS
            if _source_is_visible_in_section(
                source,
                visible_source_keys_by_section.get(section_id, set()),
            )
        ]
        if visible_sections:
            continue
        findings.append(
            make_finding(
                "blocker",
                "failed_skipped_source_not_visible",
                (
                    "A failed or skipped source is not surfaced in the grounding or "
                    "uncertainty sections."
                ),
                {
                    "document_id": source.document_id,
                    "status": source.status,
                    "original_filename": source.original_filename,
                    "visible_in_sections": visible_sections,
                },
            )
        )

    return findings


def _source_is_visible_in_section(
    source: ReportSourceEntry,
    section_keys: set[tuple[str, str]],
) -> bool:
    return bool(_source_keys(source) & section_keys)


def _source_keys(source: ReportSourceEntry) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if source.document_id:
        keys.add(("document_id", source.document_id))
    if source.original_filename:
        keys.add(("filename", source.original_filename))
    return keys


def _memory_source_key(memory: ReportRetrievedMemory) -> tuple[str, str] | None:
    document_id = _normalize_string(memory.metadata.get("document_id"), 120)
    source_name = _short_filename(
        memory.metadata.get("source") or memory.metadata.get("original_filename")
    )
    if document_id:
        return ("document_id", document_id)
    if source_name:
        return ("filename", source_name)
    return None


def _evidence_provenance_has_location(provenance: str) -> bool:
    normalized = provenance.lower()
    return "source=" in normalized and any(hint in normalized for hint in _PROVENANCE_DETAIL_HINTS)


def _paragraph_looks_numeric(text: str) -> bool:
    return bool(_NUMERIC_CLAIM_RE.search(text))


def _numeric_claim_samples(text: str) -> list[str]:
    samples: list[str] = []
    for match in _NUMERIC_CLAIM_RE.finditer(text):
        sample = _normalize_string(match.group(0), 40)
        if sample and sample not in samples:
            samples.append(sample)
        if len(samples) == 3:
            break
    return samples


def _normalize_string(value: Any, max_chars: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."


def _short_filename(value: Any) -> str:
    text = _normalize_string(value, 260)
    if not text:
        return ""
    return Path(text).name


__all__ = [
    "validate_report_artifacts",
    "validate_report_projection",
]
