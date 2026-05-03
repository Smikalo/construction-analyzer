"""Section-scoped KB recall for report drafting.

The retriever stays deliberately simple: it turns the persisted section plan
into per-family recall queries, deduplicates memory ids within each active
section, and returns a JSON-serializable manifest the pipeline can persist as an
artifact.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.kb.base import KnowledgeBase, MemoryRecord

_FAMILY_HINTS: dict[str, str] = {
    "text_documents": "Texte Unterlagen ",
    "engineering_documents": "Technische Unterlagen ",
    "engineering_workbooks": "Berechnungen Tabellen Werte ",
    "cad_exports": "CAD Zeichnungen Plaene ",
    "engineering_images": "Fotos Bilder Skizzen ",
    "backup_or_temp": "Sicherung Temp ",
    "unsupported": "Unbekannte Quelle ",
}


async def retrieve_section_evidence(
    section_plan: dict[str, Any],
    kb: KnowledgeBase,
    *,
    per_family_limit: int = 4,
) -> dict[str, Any]:
    """Build a retrieval manifest for the active sections in ``section_plan``."""
    manifest_sections: list[dict[str, Any]] = []
    raw_sections = section_plan.get("sections")
    if not isinstance(raw_sections, list):
        raw_sections = []

    for raw_section in raw_sections:
        if not isinstance(raw_section, dict) or not raw_section.get("active"):
            continue

        section_id = str(raw_section.get("id", "")).strip()
        section_title = str(raw_section.get("title", "")).strip()
        if not section_id or not section_title:
            continue

        families = _normalize_families(raw_section.get("evidence_families"))
        queries: list[dict[str, Any]] = []
        recalled_by_id: dict[str, dict[str, Any]] = {}
        seen_order: list[str] = []

        for family in families:
            query = _build_query(section_title, family)
            records = await kb.recall(query, k=per_family_limit)
            memory_ids: list[str] = []

            for record in records:
                memory_id = str(record.get("id", "")).strip()
                if not memory_id:
                    continue
                memory_ids.append(memory_id)
                _merge_memory(
                    recalled_by_id,
                    seen_order,
                    family=family,
                    record=record,
                )

            queries.append(
                {
                    "family": family,
                    "query": query,
                    "hit_count": len(records),
                    "memory_ids": memory_ids,
                }
            )

        recalled_memories = [
            {
                "id": memory_id,
                "content": entry["content"],
                "metadata": entry["metadata"],
                "score": entry["score"],
                "families": entry["families"],
            }
            for memory_id in seen_order
            for entry in [recalled_by_id[memory_id]]
        ]

        manifest_sections.append(
            {
                "id": section_id,
                "title": section_title,
                "queries": queries,
                "recalled_memories": recalled_memories,
                "total_hit_count": len(recalled_memories),
            }
        )

    return {"sections": manifest_sections}


def _build_query(section_title: str, family: str) -> str:
    hint = _FAMILY_HINTS.get(family, f"{family.replace('_', ' ')} ")
    return f"{hint}{section_title}"


def _normalize_families(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []

    families: list[str] = []
    for family in value:
        if isinstance(family, str):
            family_name = family.strip()
            if family_name:
                families.append(family_name)
    return families


def _merge_memory(
    recalled_by_id: dict[str, dict[str, Any]],
    seen_order: list[str],
    *,
    family: str,
    record: MemoryRecord,
) -> None:
    memory_id = str(record.get("id", "")).strip()
    if not memory_id:
        return

    score = _as_float(record.get("score", 0.0))
    content = str(record.get("content", ""))
    metadata = _coerce_metadata(record.get("metadata"))

    entry = recalled_by_id.get(memory_id)
    if entry is None:
        recalled_by_id[memory_id] = {
            "content": content,
            "metadata": metadata,
            "score": score,
            "families": [family],
        }
        seen_order.append(memory_id)
        return

    if family not in entry["families"]:
        entry["families"].append(family)
    if score > entry["score"]:
        entry["content"] = content
        entry["metadata"] = metadata
        entry["score"] = score


def _coerce_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["retrieve_section_evidence"]
