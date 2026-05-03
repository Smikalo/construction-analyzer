"""Deterministic normalization of persisted report artifacts.

The projection layer turns loosely-typed report-session artifacts into a frozen,
section-grouped structure that validation and export can consume without knowing
anything about SQLite records or pipeline state transitions.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GRUNDLAGEN_SECTION_ID = "grundlagen"
UNSICHERHEITEN_SECTION_ID = "unsicherheiten"
ANLAGENVERZEICHNIS_SECTION_ID = "anlagenverzeichnis"
QUELLENNACHWEISE_SECTION_ID = "quellennachweise"

REPORT_DRAFT_BANNER = "DRAFT - NOT CERTIFIED"
REPORT_NON_CERTIFICATION_NOTICE = (
    "Dieser Bericht ist ein automatisch erzeugter Entwurf und keine zertifizierte "
    "oder fachlich freigegebene Endfassung. Er dient ausschließlich der internen "
    "Prüfung und darf nicht als geprüfte Schlussfassung verwendet werden."
)

SUPPORT_SECTION_IDS: tuple[str, ...] = (
    GRUNDLAGEN_SECTION_ID,
    UNSICHERHEITEN_SECTION_ID,
)
APPENDIX_SECTION_IDS: tuple[str, ...] = (
    ANLAGENVERZEICHNIS_SECTION_ID,
    QUELLENNACHWEISE_SECTION_ID,
)

_MAX_FINDING_TEXT_CHARS = 180
_MAX_FINDING_DICT_ITEMS = 10
_MAX_FINDING_LIST_ITEMS = 5


@dataclass(frozen=True, slots=True)
class ReportSourceEntry:
    document_id: str
    original_filename: str
    status: str
    family: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ReportSourceInventoryProjection:
    present: bool
    totals: dict[str, int]
    by_family: dict[str, tuple[ReportSourceEntry, ...]]
    by_status: dict[str, tuple[ReportSourceEntry, ...]]


@dataclass(frozen=True, slots=True)
class ReportSectionPlanEntry:
    id: str
    title: str
    mandatory: bool
    evidence_families: tuple[str, ...]
    uncertainty_required: bool
    active: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReportSectionPlanProjection:
    present: bool
    template_id: str | None
    sections: tuple[ReportSectionPlanEntry, ...]


@dataclass(frozen=True, slots=True)
class ReportRetrievalQuery:
    family: str
    query: str
    hit_count: int
    memory_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportRetrievedMemory:
    id: str
    content: str
    metadata: dict[str, Any]
    score: float
    families: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportRetrievalSectionProjection:
    id: str
    title: str
    queries: tuple[ReportRetrievalQuery, ...]
    recalled_memories: tuple[ReportRetrievedMemory, ...]
    total_hit_count: int


@dataclass(frozen=True, slots=True)
class ReportRetrievalManifestProjection:
    present: bool
    sections: tuple[ReportRetrievalSectionProjection, ...]


@dataclass(frozen=True, slots=True)
class ReportParagraphEvidence:
    memory_id: str
    provenance: str


@dataclass(frozen=True, slots=True)
class ReportParagraphCitation:
    section_id: str
    paragraph_index: int
    text: str
    evidence_manifest: tuple[ReportParagraphEvidence, ...]
    no_evidence: bool


@dataclass(frozen=True, slots=True)
class ReportSectionProjection:
    id: str
    title: str
    mandatory: bool
    evidence_families: tuple[str, ...]
    uncertainty_required: bool
    active: bool
    reason: str | None
    retrieval_total_hit_count: int
    retrieval_queries: tuple[ReportRetrievalQuery, ...]
    recalled_memories: tuple[ReportRetrievedMemory, ...]
    paragraph_citations: tuple[ReportParagraphCitation, ...]
    plan_present: bool
    retrieval_present: bool
    paragraph_present: bool


@dataclass(frozen=True, slots=True)
class ReportProjection:
    source_inventory: ReportSourceInventoryProjection
    section_plan: ReportSectionPlanProjection
    retrieval_manifest: ReportRetrievalManifestProjection
    sections_by_id: dict[str, ReportSectionProjection]
    retrieved_memories_by_id: dict[str, ReportRetrievedMemory]
    section_order: tuple[str, ...]
    paragraph_citations_present: bool
    normalization_findings: tuple[dict[str, Any], ...]
    draft_banner: str = REPORT_DRAFT_BANNER
    non_certification_notice: str = REPORT_NON_CERTIFICATION_NOTICE


def build_report_projection(artifacts: Sequence[Any]) -> ReportProjection:
    """Normalize raw report artifacts into a section-grouped projection."""
    normalization_findings: list[dict[str, Any]] = []
    source_inventory = _empty_source_inventory()
    section_plan = _empty_section_plan()
    retrieval_manifest = _empty_retrieval_manifest()
    sections_by_id: dict[str, dict[str, Any]] = {}
    plan_section_order: list[str] = []
    retrieval_section_order: list[str] = []
    paragraph_section_order: list[str] = []
    retrieved_memories_by_id: dict[str, ReportRetrievedMemory] = {}
    paragraph_citations_present = False

    for artifact_index, artifact in enumerate(artifacts, start=1):
        artifact_kind = _artifact_kind(artifact)
        artifact_content = _artifact_content(artifact)

        if artifact_kind == "source_inventory_snapshot":
            if source_inventory.present:
                normalization_findings.append(
                    make_finding(
                        "warning",
                        "duplicate_source_inventory_snapshot",
                        "Multiple source inventory snapshots were provided; the first one is kept.",
                        {
                            "artifact_index": artifact_index,
                        },
                    )
                )
                continue
            source_inventory, issues = _parse_source_inventory(
                artifact_content,
                artifact_index=artifact_index,
            )
            normalization_findings.extend(issues)
            continue

        if artifact_kind == "section_plan":
            if section_plan.present:
                normalization_findings.append(
                    make_finding(
                        "warning",
                        "duplicate_section_plan",
                        "Multiple section plans were provided; the first one is kept.",
                        {
                            "artifact_index": artifact_index,
                        },
                    )
                )
                continue
            section_plan, issues = _parse_section_plan(
                artifact_content,
                artifact_index=artifact_index,
            )
            normalization_findings.extend(issues)
            continue

        if artifact_kind == "other":
            content_kind = _content_kind(artifact_content)
            if content_kind != "retrieval_manifest":
                normalization_findings.append(
                    make_finding(
                        "warning",
                        "other_artifact_not_retrieval_manifest",
                        "An `other` artifact did not contain a retrieval manifest and was ignored.",
                        {
                            "artifact_index": artifact_index,
                            "content_kind": content_kind or None,
                        },
                    )
                )
                continue
            retrieval_manifest, issues, parsed_sections = _parse_retrieval_manifest(
                artifact_content,
                artifact_index=artifact_index,
                retrieved_memories_by_id=retrieved_memories_by_id,
            )
            normalization_findings.extend(issues)
            for retrieval_section_entry in parsed_sections:
                _merge_retrieval_section(sections_by_id, retrieval_section_entry)
                _remember_section_order(
                    retrieval_section_order,
                    retrieval_section_entry.id,
                )
            continue

        if artifact_kind == "paragraph_citations":
            paragraph_citations_present = True
            paragraph, issues = _parse_paragraph_citation(
                artifact_content,
                artifact_index=artifact_index,
            )
            normalization_findings.extend(issues)
            if paragraph is None:
                continue
            section_buffer = sections_by_id.setdefault(
                paragraph.section_id,
                _empty_section_buffer(paragraph.section_id),
            )
            section_buffer["paragraphs"].append(paragraph)
            _remember_section_order(paragraph_section_order, paragraph.section_id)
            continue

        normalization_findings.append(
            make_finding(
                "warning",
                "unknown_artifact_kind",
                "An unsupported report artifact kind was ignored.",
                {
                    "artifact_index": artifact_index,
                    "artifact_kind": artifact_kind or None,
                },
            )
        )

    for plan_section_entry in section_plan.sections:
        buffer = sections_by_id.setdefault(
            plan_section_entry.id,
            _empty_section_buffer(plan_section_entry.id),
        )
        buffer["plan"] = plan_section_entry
        _remember_section_order(plan_section_order, plan_section_entry.id)

    for section_id, buffer in sections_by_id.items():
        section_plan_entry = buffer["plan"]
        retrieval_section = buffer["retrieval"]
        paragraphs = tuple(
            sorted(buffer["paragraphs"], key=lambda paragraph: paragraph.paragraph_index)
        )
        buffer["section"] = ReportSectionProjection(
            id=section_id,
            title=_section_title(section_plan_entry, retrieval_section),
            mandatory=bool(section_plan_entry.mandatory) if section_plan_entry else False,
            evidence_families=(section_plan_entry.evidence_families if section_plan_entry else ()),
            uncertainty_required=(
                bool(section_plan_entry.uncertainty_required) if section_plan_entry else False
            ),
            active=bool(section_plan_entry.active) if section_plan_entry else False,
            reason=section_plan_entry.reason if section_plan_entry else None,
            retrieval_total_hit_count=(
                retrieval_section.total_hit_count if retrieval_section else 0
            ),
            retrieval_queries=(retrieval_section.queries if retrieval_section else ()),
            recalled_memories=(retrieval_section.recalled_memories if retrieval_section else ()),
            paragraph_citations=paragraphs,
            plan_present=section_plan_entry is not None,
            retrieval_present=retrieval_section is not None,
            paragraph_present=bool(paragraphs),
        )

    section_ids = _combine_section_orders(
        plan_section_order,
        retrieval_section_order,
        paragraph_section_order,
    )
    sections_view = {
        section_id: sections_by_id[section_id]["section"]
        for section_id in section_ids
        if "section" in sections_by_id[section_id]
    }

    return ReportProjection(
        source_inventory=source_inventory,
        section_plan=section_plan,
        retrieval_manifest=retrieval_manifest,
        sections_by_id=sections_view,
        retrieved_memories_by_id=retrieved_memories_by_id,
        section_order=section_ids,
        paragraph_citations_present=paragraph_citations_present,
        normalization_findings=tuple(normalization_findings),
    )


def make_finding(
    severity: str,
    code: str,
    message: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded JSON-serializable validation finding dictionary."""
    return {
        "severity": severity.strip().lower(),
        "code": _normalize_string(code, 120),
        "message": _normalize_string(message, _MAX_FINDING_TEXT_CHARS),
        "payload": _normalize_payload(payload or {}),
    }


def _parse_source_inventory(
    content: Any,
    *,
    artifact_index: int,
) -> tuple[ReportSourceInventoryProjection, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    content_map = _coerce_mapping(content)
    if not isinstance(content, Mapping):
        issues.append(
            make_finding(
                "warning",
                "source_inventory_malformed",
                "The source inventory snapshot was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        issues.extend(_missing_source_inventory_field_findings(artifact_index))
        return _empty_source_inventory(present=True), issues

    by_family: dict[str, list[ReportSourceEntry]] = defaultdict(list)
    by_status: dict[str, list[ReportSourceEntry]] = defaultdict(list)

    raw_by_family = _coerce_mapping(content_map.get("by_family"))
    if not raw_by_family:
        issues.append(
            make_finding(
                "warning",
                "source_inventory_by_family_missing",
                "The source inventory snapshot did not include a usable family grouping.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
    else:
        for family_name, raw_entries in raw_by_family.items():
            family = _normalize_string(family_name, 80)
            for entry_index, raw_entry in enumerate(_coerce_list(raw_entries), start=1):
                entry = _parse_source_entry(
                    raw_entry,
                    family=family,
                    status_hint=None,
                    artifact_index=artifact_index,
                    entry_index=entry_index,
                    issues=issues,
                )
                if entry is not None:
                    by_family[family].append(entry)

    raw_by_status = _coerce_mapping(content_map.get("by_status"))
    if not raw_by_status:
        issues.append(
            make_finding(
                "warning",
                "source_inventory_by_status_missing",
                "The source inventory snapshot did not include a usable status grouping.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
    else:
        for status_name, raw_entries in raw_by_status.items():
            status = _normalize_string(status_name, 40)
            for entry_index, raw_entry in enumerate(_coerce_list(raw_entries), start=1):
                entry = _parse_source_entry(
                    raw_entry,
                    family=None,
                    status_hint=status,
                    artifact_index=artifact_index,
                    entry_index=entry_index,
                    issues=issues,
                )
                if entry is not None:
                    by_status[status].append(entry)

    totals = _parse_totals(
        content_map.get("totals"),
        by_status=by_status,
        artifact_index=artifact_index,
        issues=issues,
    )
    return (
        ReportSourceInventoryProjection(
            present=True,
            totals=totals,
            by_family={key: tuple(value) for key, value in by_family.items()},
            by_status={key: tuple(value) for key, value in by_status.items()},
        ),
        issues,
    )


def _missing_source_inventory_field_findings(artifact_index: int) -> list[dict[str, Any]]:
    return [
        make_finding(
            "warning",
            "source_inventory_by_family_missing",
            "The source inventory snapshot did not include a usable family grouping.",
            {
                "artifact_index": artifact_index,
            },
        ),
        make_finding(
            "warning",
            "source_inventory_by_status_missing",
            "The source inventory snapshot did not include a usable status grouping.",
            {
                "artifact_index": artifact_index,
            },
        ),
        make_finding(
            "warning",
            "source_inventory_totals_missing",
            (
                "The source inventory snapshot did not include totals; they were "
                "derived from status groups."
            ),
            {
                "artifact_index": artifact_index,
            },
        ),
    ]


def _parse_totals(
    content: Any,
    *,
    by_status: Mapping[str, list[ReportSourceEntry]],
    artifact_index: int,
    issues: list[dict[str, Any]],
) -> dict[str, int]:
    raw_totals = _coerce_mapping(content)
    if not raw_totals:
        issues.append(
            make_finding(
                "warning",
                "source_inventory_totals_missing",
                (
                    "The source inventory snapshot did not include totals; they were "
                    "derived from status groups."
                ),
                {
                    "artifact_index": artifact_index,
                },
            )
        )
    totals = {
        "indexed": _coerce_int(raw_totals.get("indexed"), len(by_status.get("indexed", []))),
        "skipped": _coerce_int(raw_totals.get("skipped"), len(by_status.get("skipped", []))),
        "failed": _coerce_int(raw_totals.get("failed"), len(by_status.get("failed", []))),
        "uploaded": _coerce_int(raw_totals.get("uploaded"), 0),
        "processing": _coerce_int(raw_totals.get("processing"), 0),
    }
    totals["total"] = _coerce_int(
        raw_totals.get("total"),
        sum(value for key, value in totals.items() if key != "total"),
    )
    return totals


def _parse_source_entry(
    raw_entry: Any,
    *,
    family: str | None,
    status_hint: str | None,
    artifact_index: int,
    entry_index: int,
    issues: list[dict[str, Any]],
) -> ReportSourceEntry | None:
    entry_map = _coerce_mapping(raw_entry)
    if not entry_map:
        issues.append(
            make_finding(
                "warning",
                "source_inventory_entry_malformed",
                "A source inventory entry was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                    "entry_index": entry_index,
                },
            )
        )
        return None

    document_id = _normalize_string(entry_map.get("document_id"), 120)
    original_filename = _short_filename(entry_map.get("original_filename"))
    status = _normalize_string(entry_map.get("status") or status_hint, 40)
    resolved_family = _normalize_string(entry_map.get("family") or family or "", 80)
    error = _normalize_string(entry_map.get("error"), 180) if entry_map.get("error") else None

    if not document_id or not original_filename or not status:
        issues.append(
            make_finding(
                "warning",
                "source_inventory_entry_incomplete",
                "A source inventory entry was missing a document id, filename, or status.",
                {
                    "artifact_index": artifact_index,
                    "entry_index": entry_index,
                    "status": status or None,
                    "original_filename": original_filename or None,
                    "document_id": document_id or None,
                },
            )
        )
        return None

    return ReportSourceEntry(
        document_id=document_id,
        original_filename=original_filename,
        status=status,
        family=resolved_family,
        error=error,
    )


def _parse_section_plan(
    content: Any,
    *,
    artifact_index: int,
) -> tuple[ReportSectionPlanProjection, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    content_map = _coerce_mapping(content)
    if not isinstance(content, Mapping):
        issues.append(
            make_finding(
                "warning",
                "section_plan_malformed",
                "The section plan was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        return _empty_section_plan(present=True), issues

    template_id = _normalize_string(content_map.get("template_id"), 120) or None
    raw_sections = _coerce_list(content_map.get("sections"))
    if not raw_sections:
        issues.append(
            make_finding(
                "warning",
                "section_plan_sections_missing",
                "The section plan did not include a usable sections list.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        return (
            ReportSectionPlanProjection(
                present=True,
                template_id=template_id,
                sections=(),
            ),
            issues,
        )

    sections: list[ReportSectionPlanEntry] = []
    seen_ids: set[str] = set()
    for section_index, raw_section in enumerate(raw_sections, start=1):
        section_map = _coerce_mapping(raw_section)
        if not section_map:
            issues.append(
                make_finding(
                    "warning",
                    "section_plan_section_malformed",
                    "A section plan entry was not a JSON object.",
                    {
                        "artifact_index": artifact_index,
                        "section_index": section_index,
                    },
                )
            )
            continue

        section_id = _normalize_string(section_map.get("id"), 80)
        if not section_id:
            issues.append(
                make_finding(
                    "warning",
                    "section_plan_section_missing_id",
                    "A section plan entry was missing its id.",
                    {
                        "artifact_index": artifact_index,
                        "section_index": section_index,
                    },
                )
            )
            continue

        if section_id in seen_ids:
            issues.append(
                make_finding(
                    "warning",
                    "section_plan_duplicate_section_id",
                    "The section plan contained duplicate section ids; the first one is kept.",
                    {
                        "artifact_index": artifact_index,
                        "section_index": section_index,
                        "section_id": section_id,
                    },
                )
            )
            continue
        seen_ids.add(section_id)

        title = _normalize_string(section_map.get("title"), 160)
        evidence_families = tuple(
            family
            for family in (
                _normalize_string(family, 80)
                for family in _coerce_list(section_map.get("evidence_families"))
            )
            if family
        )
        sections.append(
            ReportSectionPlanEntry(
                id=section_id,
                title=title,
                mandatory=_coerce_bool(section_map.get("mandatory")),
                evidence_families=evidence_families,
                uncertainty_required=_coerce_bool(section_map.get("uncertainty_required")),
                active=_coerce_bool(section_map.get("active")),
                reason=_normalize_string(section_map.get("reason"), 180)
                if section_map.get("reason")
                else None,
            )
        )

    if not sections:
        issues.append(
            make_finding(
                "warning",
                "section_plan_sections_missing",
                "The section plan did not include any valid sections.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )

    return (
        ReportSectionPlanProjection(
            present=True,
            template_id=template_id,
            sections=tuple(sections),
        ),
        issues,
    )


def _parse_retrieval_manifest(
    content: Any,
    *,
    artifact_index: int,
    retrieved_memories_by_id: dict[str, ReportRetrievedMemory],
) -> tuple[
    ReportRetrievalManifestProjection,
    list[dict[str, Any]],
    tuple[ReportRetrievalSectionProjection, ...],
]:
    issues: list[dict[str, Any]] = []
    content_map = _coerce_mapping(content)
    if not content_map:
        issues.append(
            make_finding(
                "warning",
                "retrieval_manifest_malformed",
                "The retrieval manifest was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        return _empty_retrieval_manifest(present=False), issues, ()

    raw_sections = _coerce_list(content_map.get("sections"))
    if not raw_sections:
        issues.append(
            make_finding(
                "warning",
                "retrieval_manifest_sections_missing",
                "The retrieval manifest did not include a usable sections list.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        return (
            ReportRetrievalManifestProjection(
                present=True,
                sections=(),
            ),
            issues,
            (),
        )

    sections: list[ReportRetrievalSectionProjection] = []
    for section_index, raw_section in enumerate(raw_sections, start=1):
        section_map = _coerce_mapping(raw_section)
        if not section_map:
            issues.append(
                make_finding(
                    "warning",
                    "retrieval_manifest_section_malformed",
                    "A retrieval manifest section was not a JSON object.",
                    {
                        "artifact_index": artifact_index,
                        "section_index": section_index,
                    },
                )
            )
            continue

        section_id = _normalize_string(section_map.get("id"), 80)
        if not section_id:
            issues.append(
                make_finding(
                    "warning",
                    "retrieval_manifest_section_missing_id",
                    "A retrieval manifest section was missing its id.",
                    {
                        "artifact_index": artifact_index,
                        "section_index": section_index,
                    },
                )
            )
            continue

        title = _normalize_string(section_map.get("title"), 160)
        queries = tuple(
            query
            for query in (
                _parse_retrieval_query(
                    raw_query,
                    artifact_index=artifact_index,
                    section_index=section_index,
                    query_index=query_index,
                    issues=issues,
                )
                for query_index, raw_query in enumerate(
                    _coerce_list(section_map.get("queries")),
                    start=1,
                )
            )
            if query is not None
        )
        recalled_memories = tuple(
            memory
            for memory in (
                _parse_retrieved_memory(
                    raw_memory,
                    artifact_index=artifact_index,
                    section_id=section_id,
                    memory_index=memory_index,
                    issues=issues,
                )
                for memory_index, raw_memory in enumerate(
                    _coerce_list(section_map.get("recalled_memories")),
                    start=1,
                )
            )
            if memory is not None
        )
        total_hit_count = _coerce_int(
            section_map.get("total_hit_count"),
            len(recalled_memories),
        )
        sections.append(
            ReportRetrievalSectionProjection(
                id=section_id,
                title=title,
                queries=queries,
                recalled_memories=recalled_memories,
                total_hit_count=total_hit_count,
            )
        )
        _merge_retrieved_memories(
            retrieved_memories_by_id,
            recalled_memories,
        )

    return (
        ReportRetrievalManifestProjection(
            present=True,
            sections=tuple(sections),
        ),
        issues,
        tuple(sections),
    )


def _parse_retrieval_query(
    raw_query: Any,
    *,
    artifact_index: int,
    section_index: int,
    query_index: int,
    issues: list[dict[str, Any]],
) -> ReportRetrievalQuery | None:
    query_map = _coerce_mapping(raw_query)
    if not query_map:
        issues.append(
            make_finding(
                "warning",
                "retrieval_manifest_query_malformed",
                "A retrieval query was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                    "section_index": section_index,
                    "query_index": query_index,
                },
            )
        )
        return None

    family = _normalize_string(query_map.get("family"), 80)
    query = _normalize_string(query_map.get("query"), 200)
    memory_ids = tuple(
        memory_id
        for memory_id in (
            _normalize_string(raw_memory_id, 120)
            for raw_memory_id in _coerce_list(query_map.get("memory_ids"))
        )
        if memory_id
    )
    return ReportRetrievalQuery(
        family=family,
        query=query,
        hit_count=_coerce_int(query_map.get("hit_count"), len(memory_ids)),
        memory_ids=memory_ids,
    )


def _parse_retrieved_memory(
    raw_memory: Any,
    *,
    artifact_index: int,
    section_id: str,
    memory_index: int,
    issues: list[dict[str, Any]],
) -> ReportRetrievedMemory | None:
    memory_map = _coerce_mapping(raw_memory)
    if not memory_map:
        issues.append(
            make_finding(
                "warning",
                "retrieval_manifest_memory_malformed",
                "A retrieved memory entry was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                    "section_id": section_id,
                    "memory_index": memory_index,
                },
            )
        )
        return None

    memory_id = _normalize_string(memory_map.get("id"), 120)
    if not memory_id:
        issues.append(
            make_finding(
                "warning",
                "retrieval_manifest_memory_missing_id",
                "A retrieved memory entry was missing its id.",
                {
                    "artifact_index": artifact_index,
                    "section_id": section_id,
                    "memory_index": memory_index,
                },
            )
        )
        return None

    metadata = _coerce_mapping(memory_map.get("metadata"))
    families = tuple(
        family
        for family in (
            _normalize_string(raw_family, 80)
            for raw_family in _coerce_list(memory_map.get("families"))
        )
        if family
    )
    return ReportRetrievedMemory(
        id=memory_id,
        content=_normalize_string(memory_map.get("content"), 3000),
        metadata=metadata,
        score=_coerce_float(memory_map.get("score"), 0.0),
        families=families,
    )


def _merge_retrieved_memories(
    retrieved_memories_by_id: dict[str, ReportRetrievedMemory],
    retrieved_memories: tuple[ReportRetrievedMemory, ...],
) -> None:
    for memory in retrieved_memories:
        existing = retrieved_memories_by_id.get(memory.id)
        if existing is None:
            retrieved_memories_by_id[memory.id] = memory
            continue
        if memory.score > existing.score:
            retrieved_memories_by_id[memory.id] = memory


def _parse_paragraph_citation(
    content: Any,
    *,
    artifact_index: int,
) -> tuple[ReportParagraphCitation | None, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    content_map = _coerce_mapping(content)
    if not content_map:
        issues.append(
            make_finding(
                "warning",
                "paragraph_citation_malformed",
                "The paragraph citation artifact was not a JSON object.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        return None, issues

    section_id = _normalize_string(content_map.get("section_id"), 80)
    if not section_id:
        issues.append(
            make_finding(
                "warning",
                "paragraph_citation_missing_section_id",
                "A paragraph citation artifact was missing its section id.",
                {
                    "artifact_index": artifact_index,
                },
            )
        )
        return None, issues

    paragraph_index = _coerce_int(content_map.get("paragraph_index"), 0)
    text = _normalize_string(content_map.get("text"), 3000)
    no_evidence = _coerce_bool(content_map.get("no_evidence"))
    raw_evidence_manifest = content_map.get("evidence_manifest")
    if not isinstance(raw_evidence_manifest, list):
        issues.append(
            make_finding(
                "warning",
                "paragraph_citation_evidence_manifest_malformed",
                "A paragraph citation artifact did not include a usable evidence manifest.",
                {
                    "artifact_index": artifact_index,
                    "section_id": section_id,
                    "paragraph_index": paragraph_index,
                },
            )
        )
        raw_evidence_manifest = []

    evidence_manifest: list[ReportParagraphEvidence] = []
    for evidence_index, raw_evidence in enumerate(raw_evidence_manifest, start=1):
        evidence_map = _coerce_mapping(raw_evidence)
        if not evidence_map:
            issues.append(
                make_finding(
                    "warning",
                    "paragraph_citation_evidence_malformed",
                    "A paragraph citation evidence entry was not a JSON object.",
                    {
                        "artifact_index": artifact_index,
                        "section_id": section_id,
                        "paragraph_index": paragraph_index,
                        "evidence_index": evidence_index,
                    },
                )
            )
            continue
        memory_id = _normalize_string(evidence_map.get("memory_id") or evidence_map.get("id"), 120)
        provenance = _normalize_string(evidence_map.get("provenance"), 180)
        if not memory_id:
            issues.append(
                make_finding(
                    "warning",
                    "paragraph_citation_evidence_missing_id",
                    "A paragraph citation evidence entry was missing its memory id.",
                    {
                        "artifact_index": artifact_index,
                        "section_id": section_id,
                        "paragraph_index": paragraph_index,
                        "evidence_index": evidence_index,
                    },
                )
            )
            continue
        if not provenance:
            issues.append(
                make_finding(
                    "warning",
                    "paragraph_citation_evidence_missing_provenance",
                    "A paragraph citation evidence entry was missing provenance.",
                    {
                        "artifact_index": artifact_index,
                        "section_id": section_id,
                        "paragraph_index": paragraph_index,
                        "evidence_index": evidence_index,
                        "memory_id": memory_id,
                    },
                )
            )
            continue
        evidence_manifest.append(
            ReportParagraphEvidence(memory_id=memory_id, provenance=provenance)
        )

    return (
        ReportParagraphCitation(
            section_id=section_id,
            paragraph_index=paragraph_index,
            text=text,
            evidence_manifest=tuple(evidence_manifest),
            no_evidence=no_evidence,
        ),
        issues,
    )


def _empty_source_inventory(*, present: bool = False) -> ReportSourceInventoryProjection:
    return ReportSourceInventoryProjection(
        present=present,
        totals={
            "indexed": 0,
            "skipped": 0,
            "failed": 0,
            "uploaded": 0,
            "processing": 0,
            "total": 0,
        },
        by_family={},
        by_status={},
    )


def _empty_section_plan(*, present: bool = False) -> ReportSectionPlanProjection:
    return ReportSectionPlanProjection(present=present, template_id=None, sections=())


def _empty_retrieval_manifest(
    *,
    present: bool = False,
) -> ReportRetrievalManifestProjection:
    return ReportRetrievalManifestProjection(present=present, sections=())


def _empty_section_buffer(section_id: str) -> dict[str, Any]:
    return {
        "plan": None,
        "retrieval": None,
        "paragraphs": [],
        "section": None,
        "id": section_id,
    }


def _merge_retrieval_section(
    sections_by_id: dict[str, dict[str, Any]],
    retrieval_section: ReportRetrievalSectionProjection,
) -> None:
    buffer = sections_by_id.setdefault(
        retrieval_section.id,
        _empty_section_buffer(retrieval_section.id),
    )
    existing = buffer["retrieval"]
    if existing is None:
        buffer["retrieval"] = retrieval_section
        return

    merged_queries = existing.queries + retrieval_section.queries
    merged_memories = _merge_retrieval_memories(
        existing.recalled_memories,
        retrieval_section.recalled_memories,
    )
    buffer["retrieval"] = ReportRetrievalSectionProjection(
        id=retrieval_section.id,
        title=existing.title or retrieval_section.title,
        queries=merged_queries,
        recalled_memories=merged_memories,
        total_hit_count=max(existing.total_hit_count, retrieval_section.total_hit_count),
    )


def _merge_retrieval_memories(
    first: tuple[ReportRetrievedMemory, ...],
    second: tuple[ReportRetrievedMemory, ...],
) -> tuple[ReportRetrievedMemory, ...]:
    merged: dict[str, ReportRetrievedMemory] = {memory.id: memory for memory in first}
    for memory in second:
        existing = merged.get(memory.id)
        if existing is None or memory.score > existing.score:
            merged[memory.id] = memory
    return tuple(merged.values())


def _combine_section_orders(*orders: list[str]) -> tuple[str, ...]:
    combined: list[str] = []
    for order in orders:
        for section_id in order:
            if section_id and section_id not in combined:
                combined.append(section_id)
    return tuple(combined)


def _remember_section_order(section_order: list[str], section_id: str) -> None:
    if section_id and section_id not in section_order:
        section_order.append(section_id)


def _section_title(
    section_plan_entry: ReportSectionPlanEntry | None,
    retrieval_section: ReportRetrievalSectionProjection | None,
) -> str:
    if section_plan_entry and section_plan_entry.title:
        return section_plan_entry.title
    if retrieval_section and retrieval_section.title:
        return retrieval_section.title
    return ""


def _artifact_kind(artifact: Any) -> str:
    if isinstance(artifact, Mapping):
        kind = artifact.get("kind")
    else:
        kind = getattr(artifact, "kind", None)
    return _normalize_string(kind, 80)


def _artifact_content(artifact: Any) -> Any:
    if isinstance(artifact, Mapping):
        return artifact.get("content")
    return getattr(artifact, "content", None)


def _content_kind(content: Any) -> str:
    content_map = _coerce_mapping(content)
    if not content_map:
        return ""
    return _normalize_string(content_map.get("kind"), 80)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _normalize_payload(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _normalize_string(value, _MAX_FINDING_TEXT_CHARS)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in list(value.items())[:_MAX_FINDING_DICT_ITEMS]:
            normalized[str(key)] = _normalize_payload(item)
        return normalized
    if isinstance(value, tuple):
        return [_normalize_payload(item) for item in list(value)[:_MAX_FINDING_LIST_ITEMS]]
    if isinstance(value, list):
        return [_normalize_payload(item) for item in value[:_MAX_FINDING_LIST_ITEMS]]
    return _normalize_string(value, _MAX_FINDING_TEXT_CHARS)


__all__ = [
    "ANLAGENVERZEICHNIS_SECTION_ID",
    "APPENDIX_SECTION_IDS",
    "GRUNDLAGEN_SECTION_ID",
    "QUELLENNACHWEISE_SECTION_ID",
    "REPORT_DRAFT_BANNER",
    "REPORT_NON_CERTIFICATION_NOTICE",
    "ReportParagraphCitation",
    "ReportParagraphEvidence",
    "ReportProjection",
    "ReportRetrievedMemory",
    "ReportRetrievalManifestProjection",
    "ReportRetrievalQuery",
    "ReportRetrievalSectionProjection",
    "ReportSectionPlanEntry",
    "ReportSectionPlanProjection",
    "ReportSectionProjection",
    "ReportSourceEntry",
    "ReportSourceInventoryProjection",
    "SUPPORT_SECTION_IDS",
    "UNSICHERHEITEN_SECTION_ID",
    "build_report_projection",
    "make_finding",
]
