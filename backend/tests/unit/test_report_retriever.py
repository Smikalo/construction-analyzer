"""Tests for the section-scoped report retriever."""

from __future__ import annotations

from typing import Any

from app.kb.base import MemoryRecord
from app.kb.fake import FakeKB
from app.services.report_planner import (
    build_general_project_dossier_section_plan,
    build_source_inventory,
)
from app.services.report_retriever import retrieve_section_evidence


class RecordingFakeKB(FakeKB):
    def __init__(self) -> None:
        super().__init__()
        self.recall_calls: list[tuple[str, int]] = []

    async def recall(self, query: str, k: int = 5) -> list[MemoryRecord]:
        self.recall_calls.append((query, k))
        return await super().recall(query, k=k)


class TestRetrieveSectionEvidence:
    async def test_inactive_section_is_skipped(self) -> None:
        kb = RecordingFakeKB()
        section = _section_from_plan("baugrund")

        manifest = await retrieve_section_evidence({"sections": [section]}, kb=kb)

        assert manifest == {"sections": []}
        assert kb.recall_calls == []

    async def test_active_section_with_multiple_families_deduplicates_memories(self) -> None:
        kb = RecordingFakeKB()
        section = _section_from_plan("berechnungen")
        title = section["title"]

        shared_id = await kb.remember(
            f"Texte Unterlagen {title} | Technische Unterlagen {title}",
            metadata={"document_id": "doc-shared", "source": "shared.pdf"},
        )
        workbook_id = await kb.remember(
            f"Berechnungen Tabellen Werte {title}",
            metadata={"document_id": "doc-workbook", "source": "workbook.xlsx"},
        )

        manifest = await retrieve_section_evidence({"sections": [section]}, kb=kb)

        assert kb.recall_calls == [
            (f"Texte Unterlagen {title}", 4),
            (f"Technische Unterlagen {title}", 4),
            (f"Berechnungen Tabellen Werte {title}", 4),
        ]

        section_entry = manifest["sections"][0]
        assert section_entry["id"] == "berechnungen"
        assert section_entry["title"] == title
        assert section_entry["queries"] == [
            {
                "family": "text_documents",
                "query": f"Texte Unterlagen {title}",
                "hit_count": 1,
                "memory_ids": [shared_id],
            },
            {
                "family": "engineering_documents",
                "query": f"Technische Unterlagen {title}",
                "hit_count": 1,
                "memory_ids": [shared_id],
            },
            {
                "family": "engineering_workbooks",
                "query": f"Berechnungen Tabellen Werte {title}",
                "hit_count": 1,
                "memory_ids": [workbook_id],
            },
        ]
        assert section_entry["total_hit_count"] == 2

        recalled_memories = {item["id"]: item for item in section_entry["recalled_memories"]}
        assert list(recalled_memories) == [shared_id, workbook_id]
        assert recalled_memories[shared_id] == {
            "id": shared_id,
            "content": f"Texte Unterlagen {title} | Technische Unterlagen {title}",
            "metadata": {"document_id": "doc-shared", "source": "shared.pdf"},
            "score": 1.0,
            "families": ["text_documents", "engineering_documents"],
        }
        assert recalled_memories[workbook_id] == {
            "id": workbook_id,
            "content": f"Berechnungen Tabellen Werte {title}",
            "metadata": {"document_id": "doc-workbook", "source": "workbook.xlsx"},
            "score": 1.0,
            "families": ["engineering_workbooks"],
        }

    async def test_empty_fake_kb_returns_zero_hits_and_no_memories(self) -> None:
        kb = RecordingFakeKB()
        section = _section_from_plan("berechnungen")
        title = section["title"]

        manifest = await retrieve_section_evidence({"sections": [section]}, kb=kb)

        assert kb.recall_calls == [
            (f"Texte Unterlagen {title}", 4),
            (f"Technische Unterlagen {title}", 4),
            (f"Berechnungen Tabellen Werte {title}", 4),
        ]

        section_entry = manifest["sections"][0]
        assert section_entry["total_hit_count"] == 0
        assert section_entry["recalled_memories"] == []
        assert section_entry["queries"] == [
            {
                "family": "text_documents",
                "query": f"Texte Unterlagen {title}",
                "hit_count": 0,
                "memory_ids": [],
            },
            {
                "family": "engineering_documents",
                "query": f"Technische Unterlagen {title}",
                "hit_count": 0,
                "memory_ids": [],
            },
            {
                "family": "engineering_workbooks",
                "query": f"Berechnungen Tabellen Werte {title}",
                "hit_count": 0,
                "memory_ids": [],
            },
        ]


def _section_from_plan(section_id: str) -> dict[str, Any]:
    plan = build_general_project_dossier_section_plan(build_source_inventory([]))
    return next(section for section in plan["sections"] if section["id"] == section_id)
