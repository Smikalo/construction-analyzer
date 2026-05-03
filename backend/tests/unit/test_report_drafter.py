"""Tests for the report drafter service."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.report_drafter import (
    ReportDrafterError,
    draft_section,
    extract_provenance_header,
)
from tests._fakes import make_fake_chat_model


class TestDraftSection:
    async def test_happy_path_returns_citation_bearing_paragraphs(self) -> None:
        provenance_header = (
            '[source=bestandsplan.pdf; page=2; element=paragraph; extraction=text]'
        )
        content = (
            f'{provenance_header}\n'
            'Der Nachweis der Standsicherheit liegt vor und verweist auf die Unterlagen.'
        )
        section_entry = _section_entry(
            section_id='berechnungen',
            title='Berechnungen, Tabellen und Werte',
            recalled_memories=[_memory('memory-1', content)],
        )
        payload = json.dumps(
            {
                'paragraphs': [
                    {
                        'text': 'Die Standsicherheit ist belegt. [evidence_id=memory-1]',
                        'evidence_ids': ['memory-1'],
                    }
                ]
            },
            ensure_ascii=False,
        )
        llm = make_fake_chat_model([payload])

        paragraphs = await draft_section(section_entry, llm=llm)

        assert llm.call_count == 1
        assert len(llm.messages_seen) == 1
        assert [type(message) for message in llm.messages_seen[0]] == [
            SystemMessage,
            HumanMessage,
        ]
        system_prompt, human_prompt = llm.messages_seen[0]
        assert 'auf Deutsch' in system_prompt.content
        assert '[evidence_id=' in system_prompt.content
        assert 'Berechnungen, Tabellen und Werte' in human_prompt.content
        expected_memory_line = (
            '[memory-1] [source=bestandsplan.pdf; page=2; element=paragraph; extraction=text]'
        )
        assert expected_memory_line in human_prompt.content
        assert 'Der Nachweis der Standsicherheit liegt vor' in human_prompt.content
        assert extract_provenance_header(content) == provenance_header
        assert paragraphs == [
            {
                'section_id': 'berechnungen',
                'paragraph_index': 1,
                'text': 'Die Standsicherheit ist belegt. [evidence_id=memory-1]',
                'evidence_manifest': [
                    {
                        'memory_id': 'memory-1',
                        'provenance': provenance_header,
                    }
                ],
            }
        ]

    async def test_unknown_memory_ids_drop_only_the_invalid_paragraph(self) -> None:
        provenance_header = '[source=report.pdf; element=paragraph; extraction=text]'
        content = f'{provenance_header}\nDer Bericht erwähnt eine belastbare Unterlage.'
        section_entry = _section_entry(
            section_id='aufgabenstellung',
            title='Aufgabenstellung und Berichtszweck',
            recalled_memories=[_memory('memory-1', content)],
        )
        payload = json.dumps(
            {
                'paragraphs': [
                    {
                        'text': 'Dieser Absatz nennt eine unbekannte Quelle. [evidence_id=ghost]',
                        'evidence_ids': ['ghost'],
                    },
                    {
                        'text': 'Dieser Absatz bleibt erhalten. [evidence_id=memory-1]',
                        'evidence_ids': ['memory-1'],
                    },
                ]
            },
            ensure_ascii=False,
        )
        llm = make_fake_chat_model([payload])

        paragraphs = await draft_section(section_entry, llm=llm)

        assert llm.call_count == 1
        assert paragraphs == [
            {
                'section_id': 'aufgabenstellung',
                'paragraph_index': 1,
                'text': 'Dieser Absatz bleibt erhalten. [evidence_id=memory-1]',
                'evidence_manifest': [
                    {
                        'memory_id': 'memory-1',
                        'provenance': provenance_header,
                    }
                ],
            }
        ]

    async def test_empty_recalled_memories_short_circuit_without_llm_call(self) -> None:
        section_entry = _section_entry(
            section_id='grundlagen',
            title='Grundlagen und ausgewertete Unterlagen',
            recalled_memories=[],
        )
        llm = make_fake_chat_model([
            json.dumps(
                {
                    'paragraphs': [
                        {
                            'text': 'Dieser Text sollte nicht verwendet werden.',
                            'evidence_ids': ['memory-1'],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ])

        paragraphs = await draft_section(section_entry, llm=llm)

        assert paragraphs == []
        assert llm.call_count == 0
        assert llm.messages_seen == []

    async def test_malformed_json_raises_typed_error(self) -> None:
        section_entry = _section_entry(
            section_id='ergebnisse',
            title='Ergebnisse und Empfehlungen',
            recalled_memories=[_memory('memory-1', '[source=result.pdf]\nGute Nachricht.')],
        )
        llm = make_fake_chat_model(['not json at all'])

        with pytest.raises(ReportDrafterError, match='JSON'):
            await draft_section(section_entry, llm=llm)

        assert llm.call_count == 1
        assert len(llm.messages_seen) == 1


def _section_entry(
    *,
    section_id: str,
    title: str,
    recalled_memories: list[dict[str, object]],
) -> dict[str, object]:
    return {
        'id': section_id,
        'title': title,
        'recalled_memories': recalled_memories,
    }


def _memory(memory_id: str, content: str) -> dict[str, object]:
    return {
        'id': memory_id,
        'content': content,
        'metadata': {},
        'score': 1.0,
        'families': ['text_documents'],
    }
