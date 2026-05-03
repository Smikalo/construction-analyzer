"""Pure report planning helpers for source inventory and section plans."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.services.document_registry import DocumentRecord
from app.services.engineering_files import classify

SOURCE_FAMILIES: tuple[str, ...] = (
    "text_documents",
    "engineering_documents",
    "engineering_workbooks",
    "cad_exports",
    "engineering_images",
    "backup_or_temp",
    "unsupported",
)

_SOURCE_STATUS_KEYS: tuple[str, ...] = (
    "indexed",
    "skipped",
    "failed",
)

_TOTAL_STATUS_KEYS: tuple[str, ...] = (
    "indexed",
    "skipped",
    "failed",
    "uploaded",
    "processing",
)


@dataclass(frozen=True, slots=True)
class ReportSectionTemplate:
    """Static template metadata for one report section."""

    id: str
    title: str
    mandatory: bool
    evidence_families: tuple[str, ...]
    uncertainty_required: bool
    conditional_on_evidence: bool


GENERAL_PROJECT_DOSSIER_SECTIONS: tuple[ReportSectionTemplate, ...] = (
    ReportSectionTemplate(
        id="deckblatt",
        title="Deckblatt",
        mandatory=True,
        evidence_families=(),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="aufgabenstellung",
        title="Aufgabenstellung und Berichtszweck",
        mandatory=True,
        evidence_families=("text_documents", "engineering_documents"),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="grundlagen",
        title="Grundlagen und ausgewertete Unterlagen",
        mandatory=True,
        evidence_families=SOURCE_FAMILIES,
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="projekt_beschreibung",
        title="Projekt- und Bauwerksbeschreibung",
        mandatory=True,
        evidence_families=(
            "text_documents",
            "engineering_documents",
            "engineering_workbooks",
            "cad_exports",
        ),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="normen",
        title="Normen, Regelwerke und Randbedingungen",
        mandatory=True,
        evidence_families=("text_documents", "engineering_documents"),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="baugrund",
        title="Baugrund und geotechnische Grundlagen",
        mandatory=False,
        evidence_families=(
            "text_documents",
            "engineering_documents",
            "engineering_workbooks",
        ),
        uncertainty_required=False,
        conditional_on_evidence=True,
    ),
    ReportSectionTemplate(
        id="tragwerk",
        title="Tragwerks- und Standsicherheitsrelevante Angaben",
        mandatory=False,
        evidence_families=(
            "text_documents",
            "engineering_documents",
            "engineering_workbooks",
            "cad_exports",
        ),
        uncertainty_required=False,
        conditional_on_evidence=True,
    ),
    ReportSectionTemplate(
        id="plaene",
        title="Plaene, Zeichnungen und CAD-Auswertungen",
        mandatory=True,
        evidence_families=("text_documents", "engineering_documents", "cad_exports"),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="berechnungen",
        title="Berechnungen, Tabellen und Werte",
        mandatory=True,
        evidence_families=("text_documents", "engineering_documents", "engineering_workbooks"),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="ausfuehrung",
        title="Ausfuehrung, Bauablauf, Abnahme und Uebergabe",
        mandatory=False,
        evidence_families=(
            "text_documents",
            "engineering_documents",
            "engineering_workbooks",
            "cad_exports",
        ),
        uncertainty_required=False,
        conditional_on_evidence=True,
    ),
    ReportSectionTemplate(
        id="ergebnisse",
        title="Ergebnisse und Empfehlungen",
        mandatory=True,
        evidence_families=(
            "text_documents",
            "engineering_documents",
            "engineering_workbooks",
            "cad_exports",
        ),
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="unsicherheiten",
        title="Unsicherheiten, Widersprueche und fehlende Nachweise",
        mandatory=True,
        evidence_families=SOURCE_FAMILIES,
        uncertainty_required=True,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="anlagenverzeichnis",
        title="Anlagenverzeichnis",
        mandatory=True,
        evidence_families=SOURCE_FAMILIES,
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
    ReportSectionTemplate(
        id="quellennachweise",
        title="Quellennachweise",
        mandatory=True,
        evidence_families=SOURCE_FAMILIES,
        uncertainty_required=False,
        conditional_on_evidence=False,
    ),
)

_SOURCE_ROLE_TO_FAMILY: dict[str, str] = {
    "text_document": "text_documents",
    "engineering_document": "engineering_documents",
    "engineering_workbook": "engineering_workbooks",
    "cad_export": "cad_exports",
    "engineering_image": "engineering_images",
    "backup_or_temp": "backup_or_temp",
    "unsupported": "unsupported",
}


def build_source_inventory(records: Sequence[DocumentRecord]) -> dict[str, Any]:
    """Group registry records by family and visible lifecycle status."""
    totals = {status: 0 for status in _TOTAL_STATUS_KEYS}
    totals["total"] = 0

    by_family: dict[str, list[dict[str, Any]]] = {family: [] for family in SOURCE_FAMILIES}
    by_status: dict[str, list[dict[str, Any]]] = {status: [] for status in _SOURCE_STATUS_KEYS}

    for record in records:
        family = _SOURCE_ROLE_TO_FAMILY[classify(record.original_filename).role]
        entry = _build_inventory_entry(record, family)

        by_family[family].append(entry)
        totals[record.status] += 1
        totals["total"] += 1

        if record.status in by_status:
            by_status[record.status].append(entry)

    return {
        "totals": totals,
        "by_family": by_family,
        "by_status": by_status,
    }


def build_general_project_dossier_section_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    """Build the base section plan for a general project dossier."""
    sections: list[dict[str, Any]] = []

    for template in GENERAL_PROJECT_DOSSIER_SECTIONS:
        active, reason = _resolve_section_activity(template, inventory)
        sections.append(
            {
                "id": template.id,
                "title": template.title,
                "mandatory": template.mandatory,
                "evidence_families": list(template.evidence_families),
                "uncertainty_required": template.uncertainty_required,
                "active": active,
                "reason": reason,
            }
        )

    return {
        "template_id": "general_project_dossier",
        "sections": sections,
    }


def _build_inventory_entry(record: DocumentRecord, family: str) -> dict[str, Any]:
    return {
        "document_id": record.document_id,
        "original_filename": record.original_filename,
        "status": record.status,
        "error": record.error,
        "family": family,
    }


def _resolve_section_activity(
    template: ReportSectionTemplate,
    inventory: dict[str, Any],
) -> tuple[bool, str | None]:
    if template.mandatory:
        return True, None

    if not template.conditional_on_evidence:
        return False, None

    if _inventory_has_indexed_family(inventory, template.evidence_families):
        return True, None

    return False, f"no indexed evidence for families: {', '.join(template.evidence_families)}"


def _inventory_has_indexed_family(inventory: dict[str, Any], families: tuple[str, ...]) -> bool:
    indexed_entries = inventory.get("by_status", {}).get("indexed", [])
    indexed_families = {
        entry["family"]
        for entry in indexed_entries
        if isinstance(entry, dict) and isinstance(entry.get("family"), str)
    }
    return any(family in indexed_families for family in families)


__all__ = [
    "GENERAL_PROJECT_DOSSIER_SECTIONS",
    "ReportSectionTemplate",
    "build_general_project_dossier_section_plan",
    "build_source_inventory",
]
