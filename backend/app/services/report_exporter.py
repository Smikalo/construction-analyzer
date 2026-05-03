"""Backend-owned PDF export for deterministic report projections."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import cm  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report_projection import (
    REPORT_DRAFT_BANNER,
    REPORT_NON_CERTIFICATION_NOTICE,
    ReportParagraphEvidence,
    ReportProjection,
    ReportSectionProjection,
    ReportSourceEntry,
)

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_EVIDENCE_TOKEN_RE = re.compile(r"\s*\[evidence_id=[^\]]+\]")
_MAX_SESSION_SLUG_CHARS = 80
_MAX_TABLE_TEXT_CHARS = 180
_MAX_PROVENANCE_TEXT_CHARS = 320

DiagnosticValue = bool | int | str


class ReportExportError(RuntimeError):
    """Raised when a report projection cannot be exported to PDF."""


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Result returned by the PDF exporter."""

    output_path: Path
    diagnostics: dict[str, DiagnosticValue]


@dataclass(frozen=True, slots=True)
class _CitationEntry:
    marker: int
    memory_id: str
    provenance: str


class _CitationRegistry:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], _CitationEntry] = {}
        self._entries: list[_CitationEntry] = []

    @property
    def entries(self) -> tuple[_CitationEntry, ...]:
        return tuple(self._entries)

    def marker_for(self, evidence: ReportParagraphEvidence) -> int:
        memory_id = _bounded_text(getattr(evidence, "memory_id", ""), _MAX_TABLE_TEXT_CHARS)
        provenance = _bounded_text(
            getattr(evidence, "provenance", ""),
            _MAX_PROVENANCE_TEXT_CHARS,
        )
        if not memory_id:
            memory_id = "unknown-memory"
        key = (memory_id, provenance)
        if key in self._by_key:
            return self._by_key[key].marker

        entry = _CitationEntry(
            marker=len(self._entries) + 1,
            memory_id=memory_id,
            provenance=provenance,
        )
        self._by_key[key] = entry
        self._entries.append(entry)
        return entry.marker


def export_report_pdf(
    projection: ReportProjection,
    *,
    output_dir: str,
    session_id: str,
    validation_findings: Sequence[Mapping[str, Any]] | None = None,
) -> ExportResult:
    """Render a deterministic report projection to a backend-generated PDF file."""
    output_root = _prepare_output_root(output_dir)
    safe_session_id = _safe_session_slug(session_id)
    output_path = _safe_output_path(output_root, safe_session_id)
    temp_output_path = output_path.with_name(f".{output_path.stem}.tmp.pdf")

    sections = _sections_in_order(projection)
    source_entries = _source_entries(projection)
    citation_registry = _CitationRegistry()
    story = _build_story(
        projection,
        sections=sections,
        source_entries=source_entries,
        citation_registry=citation_registry,
        safe_session_id=safe_session_id,
    )

    document = SimpleDocTemplate(
        str(temp_output_path),
        pagesize=A4,
        title="General Project Dossier Draft",
        author="construction-analyzer",
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
    )

    try:
        document.build(story)
        temp_output_path.replace(output_path)
    except Exception as exc:
        _remove_file_if_present(temp_output_path)
        raise ReportExportError("Report PDF rendering failed.") from exc

    try:
        byte_size = output_path.stat().st_size
    except OSError as exc:
        raise ReportExportError("Report PDF was not written.") from exc

    severity_counts = _severity_counts(validation_findings, projection)
    diagnostics: dict[str, DiagnosticValue] = {
        "format": "pdf",
        "output_filename": output_path.name,
        "byte_size": byte_size,
        "page_count": int(getattr(document, "page", 0) or 0),
        "section_count": len(sections),
        "paragraph_count": _paragraph_count(sections),
        "source_count": len(source_entries),
        "citation_count": len(citation_registry.entries),
        "validation_finding_count": severity_counts["total"],
        "validation_warning_count": severity_counts["warning"],
        "validation_blocker_count": severity_counts["blocker"],
    }
    return ExportResult(output_path=output_path, diagnostics=diagnostics)


def _prepare_output_root(output_dir: str) -> Path:
    output_root = Path(output_dir).expanduser()
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        if not output_root.is_dir():
            raise ReportExportError("Report export destination is not a directory.")
        return output_root.resolve()
    except ReportExportError:
        raise
    except OSError as exc:
        raise ReportExportError("Unable to prepare report export directory.") from exc


def _safe_output_path(output_root: Path, safe_session_id: str) -> Path:
    output_path = (output_root / f"{safe_session_id}-report.pdf").resolve()
    if not output_path.is_relative_to(output_root):
        raise ReportExportError("Derived report export path escaped the export directory.")
    return output_path


def _safe_session_slug(session_id: str) -> str:
    raw_slug = _bounded_text(session_id, _MAX_SESSION_SLUG_CHARS)
    slug = _SAFE_FILENAME_RE.sub("-", raw_slug).strip(".-_")
    return slug or "report-session"


def _build_story(
    projection: ReportProjection,
    *,
    sections: Sequence[ReportSectionProjection],
    source_entries: Sequence[ReportSourceEntry],
    citation_registry: _CitationRegistry,
    safe_session_id: str,
) -> list[Any]:
    styles = _pdf_styles()
    story: list[Any] = []

    story.extend(_cover_page(projection, safe_session_id=safe_session_id, styles=styles))
    story.extend(_table_of_contents(sections, styles=styles))
    story.extend(_report_sections(sections, citation_registry=citation_registry, styles=styles))
    story.extend(_source_appendix(source_entries, styles=styles))
    story.extend(_citation_manifest(citation_registry, styles=styles))

    return story


def _cover_page(
    projection: ReportProjection,
    *,
    safe_session_id: str,
    styles: Mapping[str, Any],
) -> list[Any]:
    draft_banner = _bounded_text(
        getattr(projection, "draft_banner", REPORT_DRAFT_BANNER) or REPORT_DRAFT_BANNER,
        _MAX_TABLE_TEXT_CHARS,
    )
    non_certification_notice = _bounded_text(
        getattr(projection, "non_certification_notice", REPORT_NON_CERTIFICATION_NOTICE)
        or REPORT_NON_CERTIFICATION_NOTICE,
        800,
    )
    return [
        Paragraph("Deckblatt", styles["ReportTitle"]),
        Spacer(1, 0.4 * cm),
        Paragraph(_escape(draft_banner), styles["DraftBanner"]),
        Spacer(1, 0.3 * cm),
        Paragraph(_escape(non_certification_notice), styles["Notice"]),
        Spacer(1, 0.6 * cm),
        Paragraph(f"Session: {_escape(safe_session_id)}", styles["Small"]),
        PageBreak(),
    ]


def _table_of_contents(
    sections: Sequence[ReportSectionProjection],
    *,
    styles: Mapping[str, Any],
) -> list[Any]:
    story: list[Any] = [Paragraph("Inhaltsverzeichnis", styles["Heading1"])]
    if not sections:
        story.append(Paragraph("Keine Berichtskapitel verfügbar.", styles["BodyText"]))
        story.append(PageBreak())
        return story

    for index, section in enumerate(sections, start=1):
        title = _section_title(section)
        story.append(Paragraph(f"{index}. {_escape(title)}", styles["BodyText"]))
    story.append(PageBreak())
    return story


def _report_sections(
    sections: Sequence[ReportSectionProjection],
    *,
    citation_registry: _CitationRegistry,
    styles: Mapping[str, Any],
) -> list[Any]:
    story: list[Any] = []
    for section_index, section in enumerate(sections, start=1):
        title = _section_title(section)
        story.append(Paragraph(f"{section_index}. {_escape(title)}", styles["Heading1"]))

        if not bool(getattr(section, "active", True)):
            reason = _bounded_text(getattr(section, "reason", ""), _MAX_TABLE_TEXT_CHARS)
            inactive_text = "Abschnitt deaktiviert."
            if reason:
                inactive_text = f"{inactive_text} Grund: {reason}"
            story.append(Paragraph(_escape(inactive_text), styles["Small"]))

        paragraphs = _section_paragraphs(section)
        if not paragraphs:
            story.append(Paragraph("Kein Abschnittstext verfügbar.", styles["BodyText"]))
            story.append(Spacer(1, 0.25 * cm))
            continue

        for paragraph in paragraphs:
            story.append(
                Paragraph(
                    _paragraph_with_citations(paragraph, citation_registry),
                    styles["BodyText"],
                )
            )
            story.append(Spacer(1, 0.18 * cm))
        story.append(Spacer(1, 0.2 * cm))
    return story


def _source_appendix(
    source_entries: Sequence[ReportSourceEntry],
    *,
    styles: Mapping[str, Any],
) -> list[Any]:
    story: list[Any] = [
        PageBreak(),
        Paragraph("Anhang: Anlagenverzeichnis", styles["Heading1"]),
        Paragraph("Quelleninventar nach Status und Dokumentfamilie", styles["Heading2"]),
    ]
    if not source_entries:
        story.append(Paragraph("Keine Quellen im Inventar verfügbar.", styles["BodyText"]))
        return story

    rows: list[list[Any]] = [
        [
            Paragraph("Status", styles["TableHeader"]),
            Paragraph("Familie", styles["TableHeader"]),
            Paragraph("Dateiname", styles["TableHeader"]),
            Paragraph("Dokument-ID", styles["TableHeader"]),
            Paragraph("Hinweis", styles["TableHeader"]),
        ]
    ]
    for entry in source_entries:
        rows.append(
            [
                Paragraph(_escape(_bounded_text(entry.status, 40)), styles["TableCell"]),
                Paragraph(_escape(_bounded_text(entry.family, 80)), styles["TableCell"]),
                Paragraph(
                    _escape(_safe_display_filename(entry.original_filename)),
                    styles["TableCell"],
                ),
                Paragraph(_escape(_bounded_text(entry.document_id, 120)), styles["TableCell"]),
                Paragraph(
                    _escape(_bounded_text(entry.error or "", _MAX_TABLE_TEXT_CHARS)),
                    styles["TableCell"],
                ),
            ]
        )

    table = Table(rows, colWidths=[1.7 * cm, 3.3 * cm, 4.0 * cm, 3.0 * cm, 4.0 * cm], repeatRows=1)
    table.setStyle(_table_style())
    story.append(table)
    return story


def _citation_manifest(
    citation_registry: _CitationRegistry,
    *,
    styles: Mapping[str, Any],
) -> list[Any]:
    story: list[Any] = [
        Spacer(1, 0.5 * cm),
        Paragraph("Anhang: Quellennachweise", styles["Heading1"]),
        Paragraph("Nummerierte Zitiernachweise", styles["Heading2"]),
    ]
    if not citation_registry.entries:
        story.append(Paragraph("Keine Zitate im Bericht vorhanden.", styles["BodyText"]))
        return story

    rows: list[list[Any]] = [
        [
            Paragraph("Marker", styles["TableHeader"]),
            Paragraph("Evidence-ID", styles["TableHeader"]),
            Paragraph("Provenienz", styles["TableHeader"]),
        ]
    ]
    for entry in citation_registry.entries:
        provenance = entry.provenance or "keine Provenance angegeben"
        rows.append(
            [
                Paragraph(f"[{entry.marker}]", styles["TableCell"]),
                Paragraph(_escape(entry.memory_id), styles["TableCell"]),
                Paragraph(_escape(provenance), styles["TableCell"]),
            ]
        )

    table = Table(rows, colWidths=[2.0 * cm, 4.0 * cm, 10.0 * cm], repeatRows=1)
    table.setStyle(_table_style())
    story.append(table)
    return story


def _paragraph_with_citations(paragraph: Any, citation_registry: _CitationRegistry) -> str:
    text = _clean_paragraph_text(getattr(paragraph, "text", ""))
    if not text:
        text = "Kein Absatztext verfügbar."
    markers = [
        f"[{citation_registry.marker_for(evidence)}]"
        for evidence in _paragraph_evidence(paragraph)
    ]
    if markers:
        text = f"{text} {' '.join(markers)}"
    elif bool(getattr(paragraph, "no_evidence", False)):
        text = f"{text} [ohne Nachweis]"
    return _escape(text)


def _sections_in_order(projection: ReportProjection) -> tuple[ReportSectionProjection, ...]:
    raw_sections = getattr(projection, "sections_by_id", {})
    if not isinstance(raw_sections, Mapping):
        return ()

    raw_order = getattr(projection, "section_order", ())
    ordered_ids: list[str] = []
    if isinstance(raw_order, Sequence) and not isinstance(raw_order, str):
        ordered_ids.extend(str(section_id) for section_id in raw_order)
    ordered_ids.extend(str(section_id) for section_id in raw_sections.keys())

    seen: set[str] = set()
    sections: list[ReportSectionProjection] = []
    for section_id in ordered_ids:
        if section_id in seen:
            continue
        section = raw_sections.get(section_id)
        if section is None:
            continue
        seen.add(section_id)
        sections.append(section)
    return tuple(sections)


def _source_entries(projection: ReportProjection) -> tuple[ReportSourceEntry, ...]:
    inventory = getattr(projection, "source_inventory", None)
    by_status = getattr(inventory, "by_status", {})
    by_family = getattr(inventory, "by_family", {})
    groups = by_status if isinstance(by_status, Mapping) and by_status else by_family
    if not isinstance(groups, Mapping):
        return ()

    seen: set[tuple[str, str, str, str]] = set()
    entries: list[ReportSourceEntry] = []
    for group_key in sorted(groups):
        raw_entries = groups[group_key]
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, str):
            continue
        for entry in raw_entries:
            document_id = _bounded_text(getattr(entry, "document_id", ""), 120)
            status = _bounded_text(getattr(entry, "status", ""), 40)
            family = _bounded_text(getattr(entry, "family", ""), 80)
            filename = _safe_display_filename(getattr(entry, "original_filename", ""))
            key = (document_id, status, family, filename)
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                _bounded_text(getattr(entry, "status", ""), 40),
                _bounded_text(getattr(entry, "family", ""), 80),
                _safe_display_filename(getattr(entry, "original_filename", "")),
                _bounded_text(getattr(entry, "document_id", ""), 120),
            ),
        )
    )


def _section_title(section: ReportSectionProjection) -> str:
    title = _bounded_text(getattr(section, "title", ""), _MAX_TABLE_TEXT_CHARS)
    return title or _bounded_text(getattr(section, "id", ""), _MAX_TABLE_TEXT_CHARS) or "Abschnitt"


def _section_paragraphs(section: ReportSectionProjection) -> tuple[Any, ...]:
    paragraphs = getattr(section, "paragraph_citations", ())
    if not isinstance(paragraphs, Sequence) or isinstance(paragraphs, str):
        return ()
    return tuple(sorted(paragraphs, key=lambda paragraph: getattr(paragraph, "paragraph_index", 0)))


def _paragraph_evidence(paragraph: Any) -> tuple[ReportParagraphEvidence, ...]:
    evidence_manifest = getattr(paragraph, "evidence_manifest", ())
    if not isinstance(evidence_manifest, Sequence) or isinstance(evidence_manifest, str):
        return ()
    return tuple(evidence_manifest)


def _paragraph_count(sections: Sequence[ReportSectionProjection]) -> int:
    return sum(len(_section_paragraphs(section)) for section in sections)


def _severity_counts(
    validation_findings: Sequence[Mapping[str, Any]] | None,
    projection: ReportProjection,
) -> dict[str, int]:
    findings = validation_findings
    if findings is None:
        findings = tuple(
            finding
            for finding in getattr(projection, "normalization_findings", ())
            if isinstance(finding, Mapping)
        )

    counts = {"total": 0, "warning": 0, "blocker": 0}
    for finding in findings:
        counts["total"] += 1
        severity = str(finding.get("severity", "")).strip().lower()
        if severity in ("warning", "blocker"):
            counts[severity] += 1
    return counts


def _pdf_styles() -> Mapping[str, Any]:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontSize=24,
            leading=30,
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DraftBanner",
            parent=styles["Title"],
            textColor=colors.HexColor("#B42318"),
            fontSize=18,
            leading=22,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Notice",
            parent=styles["BodyText"],
            borderColor=colors.HexColor("#B42318"),
            borderPadding=8,
            borderWidth=1,
            leading=15,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["BodyText"],
            fontSize=8,
            leading=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
        )
    )
    return styles


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#344054")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ]
    )


def _safe_display_filename(value: object) -> str:
    filename = _bounded_text(value, _MAX_TABLE_TEXT_CHARS)
    if not filename:
        return ""
    return re.split(r"[\\/]+", filename)[-1]


def _clean_paragraph_text(value: object) -> str:
    text = _bounded_text(value, 8_000)
    return _EVIDENCE_TOKEN_RE.sub("", text).strip()


def _bounded_text(value: object, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", " ")
    text = re.sub(r"[\r\t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ ]{2,}", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _escape(value: str) -> str:
    return html.escape(value).replace("\n", "<br/>")


def _remove_file_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return
