'''Turn a section retrieval manifest into citation-bearing German paragraphs.'''

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

MAX_PROMPT_SNIPPET_CHARS = 600

SYSTEM_PROMPT = (
    'Du schreibst Absätze für einen deutschsprachigen Bauwerksbericht. Antworte ausschließlich '
    'auf Deutsch. Jede inhaltliche Aussage muss ein Inline-Token im Format '
    '[evidence_id=<memory_id>] tragen; <memory_id> muss aus der bereitgestellten Liste stammen. '
    'Zitiere niemals eine Erinnerung außerhalb der bereitgestellten Liste und zitiere keine '
    'interne implementation guidance. Gib ausschließlich ein JSON-Objekt im exakten Schema '
    'paragraphs -> [{text, evidence_ids}] zurück und keinen weiteren Text.'
)


class ReportDrafterError(RuntimeError):
    '''Base exception for report-drafting failures.'''


async def draft_section(
    section_entry: dict[str, Any],
    *,
    llm: BaseChatModel,
    max_paragraphs: int = 3,
) -> list[dict[str, Any]]:
    recalled_memories, recalled_memory_index = _normalize_recalled_memories(
        section_entry.get('recalled_memories')
    )
    if not recalled_memories:
        return []

    section_id = str(section_entry.get('id', '')).strip()
    section_title = str(section_entry.get('title', '')).strip()
    messages = _build_messages(
        section_id=section_id,
        section_title=section_title,
        recalled_memories=recalled_memories,
        max_paragraphs=max_paragraphs,
    )

    response = await llm.ainvoke(messages)
    content = getattr(response, 'content', None)
    if not isinstance(content, str):
        raise ReportDrafterError('Report drafter response did not include text content')

    payload = _parse_response_payload(content)
    return _draft_paragraphs(
        payload,
        section_id=section_id,
        recalled_memory_index=recalled_memory_index,
        max_paragraphs=max_paragraphs,
    )


def extract_provenance_header(content: str) -> str:
    '''Return the leading bracketed provenance line, if present.'''
    normalized = content.replace('\r\n', '\n')
    first_line = normalized.split('\n', 1)[0].strip()
    if first_line.startswith('[') and first_line.endswith(']'):
        return first_line
    return ''


def _build_messages(
    *,
    section_id: str,
    section_title: str,
    recalled_memories: list[dict[str, Any]],
    max_paragraphs: int,
) -> list[SystemMessage | HumanMessage]:
    lines = [
        f'Abschnitts-ID: {section_id or "(unbekannt)"}',
        f'Abschnittstitel: {section_title or "(ohne Titel)"}',
        f'Maximale Absatzanzahl: {max_paragraphs}',
        '',
        'Verfügbare Erinnerungen:',
    ]

    for position, memory in enumerate(recalled_memories, start=1):
        memory_id = memory['id']
        provenance_header = _memory_provenance_header(memory)
        header_line = f'[{memory_id}]'
        if provenance_header:
            header_line = f'{header_line} {provenance_header}'
        lines.append(f'{position}. {header_line}')
        snippet = _truncate_prompt_snippet(_memory_body(memory['content']))
        if snippet:
            lines.append(snippet)
        lines.append('')

    paragraph_clause = (
        'genau 1 kurzen Absatz'
        if max_paragraphs == 1
        else f'zwischen 1 und {max_paragraphs} kurzen Absätzen'
    )
    lines.extend(
        [
            f'Schreibe {paragraph_clause} auf Deutsch.',
            'Nutze nur die aufgeführten Erinnerungen.',
            'Gib ausschließlich JSON zurück.',
        ]
    )
    human_content = '\n'.join(lines).strip()
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]


def _parse_response_payload(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ReportDrafterError('Report drafter response was not valid JSON') from exc

    if not isinstance(payload, dict):
        raise ReportDrafterError('Report drafter response must be a JSON object')
    return payload


def _draft_paragraphs(
    payload: dict[str, Any],
    *,
    section_id: str,
    recalled_memory_index: dict[str, dict[str, Any]],
    max_paragraphs: int,
) -> list[dict[str, Any]]:
    paragraphs = payload.get('paragraphs')
    if not isinstance(paragraphs, list):
        raise ReportDrafterError('Report drafter response must include a paragraphs list')

    drafted: list[dict[str, Any]] = []
    for raw_paragraph in paragraphs[:max_paragraphs]:
        if not isinstance(raw_paragraph, Mapping):
            continue

        text = raw_paragraph.get('text')
        evidence_ids = raw_paragraph.get('evidence_ids')
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue
        if not isinstance(evidence_ids, list) or not evidence_ids:
            continue

        normalized_evidence_ids: list[str] = []
        paragraph_is_valid = True
        for raw_memory_id in evidence_ids:
            if not isinstance(raw_memory_id, str):
                paragraph_is_valid = False
                break
            memory_id = raw_memory_id.strip()
            if not memory_id or memory_id not in recalled_memory_index:
                paragraph_is_valid = False
                break
            if memory_id not in normalized_evidence_ids:
                normalized_evidence_ids.append(memory_id)

        if not paragraph_is_valid or not normalized_evidence_ids:
            continue

        drafted.append(
            {
                'section_id': section_id,
                'paragraph_index': len(drafted) + 1,
                'text': text,
                'evidence_manifest': [
                    {
                        'memory_id': memory_id,
                        'provenance': _memory_provenance_header(
                            recalled_memory_index[memory_id]
                        ),
                    }
                    for memory_id in normalized_evidence_ids
                ],
            }
        )

    return drafted


def _normalize_recalled_memories(
    recalled_memories: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(recalled_memories, list):
        return [], {}

    ordered_memories: list[dict[str, Any]] = []
    memory_index: dict[str, dict[str, Any]] = {}
    for raw_memory in recalled_memories:
        if not isinstance(raw_memory, Mapping):
            continue

        memory_id = str(raw_memory.get('id', '')).strip()
        content = raw_memory.get('content')
        if not memory_id or not isinstance(content, str):
            continue
        if memory_id in memory_index:
            continue

        memory_entry = {
            'id': memory_id,
            'content': content,
            'metadata': _coerce_metadata(raw_memory.get('metadata')),
        }
        ordered_memories.append(memory_entry)
        memory_index[memory_id] = memory_entry

    return ordered_memories, memory_index


def _memory_provenance_header(memory: Mapping[str, Any]) -> str:
    metadata = memory.get('metadata')
    if isinstance(metadata, Mapping):
        for key in ('provenance_header', 'provenance'):
            value = metadata.get(key)
            if isinstance(value, str):
                header = extract_provenance_header(value)
                if header:
                    return header

    content = memory.get('content')
    if isinstance(content, str):
        return extract_provenance_header(content)
    return ''


def _memory_body(content: str) -> str:
    normalized = content.replace('\r\n', '\n')
    _header, separator, body = normalized.partition('\n')
    if not separator:
        return normalized
    return body


def _truncate_prompt_snippet(content: str) -> str:
    snippet = content.strip()
    if len(snippet) <= MAX_PROMPT_SNIPPET_CHARS:
        return snippet
    return snippet[:MAX_PROMPT_SNIPPET_CHARS]


def _coerce_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


__all__ = ['ReportDrafterError', 'draft_section', 'extract_provenance_header']
