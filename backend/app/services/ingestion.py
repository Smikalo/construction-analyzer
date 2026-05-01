"""Document ingestion pipeline.

Parses PDF / Markdown / plain-text files into typed document elements, chunks
those elements into reasonable pieces, and writes each chunk into the
KnowledgeBase with inline and metadata provenance.

We deliberately use a tiny hand-rolled chunker so we have zero embedding
dependencies in this layer; MemoryPalace handles embeddings itself when the
real backend is configured.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass

from app.kb.base import KnowledgeBase
from app.schemas import IngestResponse
from app.services import element_memory, parsers
from app.services.document_analysis import DocumentAnalyzer
from app.services.document_elements import DocumentElement
from app.services.document_registry import DocumentRecord, DocumentRegistry
from app.services.visual_elements import VISUAL_ELEMENT_TYPES

SUPPORTED_EXTENSIONS = (".pdf", ".md", ".markdown", ".txt")
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150


@dataclass(frozen=True, slots=True)
class RegisteredIngestFile:
    """A registry row queued for ingestion.

    `is_duplicate` is the result returned by `DocumentRegistry.register_or_get`.
    Duplicate rows are not parsed or remembered again; their persisted memory ids
    are returned so the API response remains backward-compatible.
    """

    record: DocumentRecord
    is_duplicate: bool


async def ingest_files(
    kb: KnowledgeBase,
    paths: Iterable[str],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    document_analyzer: DocumentAnalyzer | None = None,
) -> IngestResponse:
    file_count = 0
    chunk_count = 0
    memory_ids: list[str] = []

    for path in paths:
        file_delta, file_memory_ids = await _ingest_path(
            kb,
            path,
            source=os.path.basename(path),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            document_analyzer=document_analyzer,
        )
        file_count += file_delta
        chunk_count += len(file_memory_ids)
        memory_ids.extend(file_memory_ids)

    return IngestResponse(
        ingested_files=file_count,
        ingested_chunks=chunk_count,
        memory_ids=memory_ids,
    )


async def ingest_registered_files(
    kb: KnowledgeBase,
    registry: DocumentRegistry,
    entries: Iterable[RegisteredIngestFile],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    document_analyzer: DocumentAnalyzer | None = None,
) -> IngestResponse:
    """Ingest registry-backed files and persist lifecycle transitions.

    Duplicate entries are short-circuited: the stored file is not reparsed and no
    new KB memories are created. Parser/remember failures mark the row failed and
    do not abort the rest of the batch, leaving the API response JSON-shaped for
    partial success cases.
    """
    file_count = 0
    chunk_count = 0
    memory_ids: list[str] = []

    for entry in entries:
        record = entry.record
        if entry.is_duplicate:
            latest_record = registry.get_by_id(record.document_id) or record
            memory_ids.extend(latest_record.memory_ids)
            continue

        registry.update_status(record.document_id, "processing", error=None)
        try:
            file_delta, file_memory_ids = await _ingest_path(
                kb,
                record.stored_path,
                source=record.original_filename,
                document_id=record.document_id,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                document_analyzer=document_analyzer,
            )
        except Exception as exc:  # noqa: BLE001 - persist failure and continue batch.
            registry.update_status(record.document_id, "failed", error=str(exc))
            continue

        registry.update_status(
            record.document_id,
            "indexed",
            error=None,
            memory_ids=file_memory_ids,
        )
        file_count += file_delta
        chunk_count += len(file_memory_ids)
        memory_ids.extend(file_memory_ids)

    return IngestResponse(
        ingested_files=file_count,
        ingested_chunks=chunk_count,
        memory_ids=memory_ids,
    )


async def ingest_directory(
    kb: KnowledgeBase,
    directory: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    document_analyzer: DocumentAnalyzer | None = None,
) -> IngestResponse:
    if not os.path.isdir(directory):
        return IngestResponse(ingested_files=0, ingested_chunks=0)
    paths = [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.lower().endswith(SUPPORTED_EXTENSIONS)
    ]
    return await ingest_files(
        kb,
        paths,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        document_analyzer=document_analyzer,
    )


async def _ingest_path(
    kb: KnowledgeBase,
    path: str,
    *,
    source: str,
    document_id: str | None = None,
    chunk_size: int,
    chunk_overlap: int,
    document_analyzer: DocumentAnalyzer | None = None,
) -> tuple[int, list[str]]:
    if not os.path.isfile(path):
        return 0, []

    elements = parsers.parse_document(path, source=source, document_id=document_id)
    enriched_elements = _enrich_document_elements(elements, document_analyzer=document_analyzer)
    memory_ids: list[str] = []
    for element in enriched_elements:
        for content, metadata in element_memory.chunk_and_format(
            element,
            size=chunk_size,
            overlap=chunk_overlap,
        ):
            mid = await kb.remember(content, metadata=metadata)
            memory_ids.append(mid)

    if not memory_ids:
        return 0, []
    return 1, memory_ids


def _enrich_document_elements(
    elements: Iterable[DocumentElement],
    *,
    document_analyzer: DocumentAnalyzer | None,
) -> list[DocumentElement]:
    parsed_elements = list(elements)
    if document_analyzer is None:
        return parsed_elements

    visual_positions = [
        index
        for index, element in enumerate(parsed_elements)
        if element.element_type in VISUAL_ELEMENT_TYPES
    ]
    if not visual_positions:
        return parsed_elements

    visual_elements = [parsed_elements[index] for index in visual_positions]
    analyzed_visual_elements = list(document_analyzer.enrich(visual_elements))
    for index, analyzed_element in zip(
        visual_positions,
        analyzed_visual_elements,
        strict=False,
    ):
        parsed_elements[index] = analyzed_element
    return parsed_elements


def _chunk(text: str, size: int, overlap: int):
    """Yield sliding-window character chunks. Naive but predictable, which is
    what we want for tests."""
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("0 <= overlap < size")

    text = text.strip()
    if not text:
        return

    step = size - overlap
    pos = 0
    while pos < len(text):
        chunk = text[pos : pos + size].strip()
        if chunk:
            yield chunk
        pos += step
