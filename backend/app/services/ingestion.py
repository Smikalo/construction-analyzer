"""Document ingestion pipeline.

Parses PDF / Markdown / plain-text files into typed document elements, chunks
those elements into reasonable pieces, and writes each chunk into the
KnowledgeBase with inline and metadata provenance.

We deliberately use a tiny hand-rolled chunker so we have zero embedding
dependencies in this layer; MemoryPalace handles embeddings itself when the
real backend is configured.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass, replace

from app.kb.base import KnowledgeBase
from app.schemas import IngestResponse
from app.services import element_memory, parsers
from app.services.document_analysis import DocumentAnalyzer
from app.services.document_elements import DocumentElement
from app.services.document_registry import DocumentRecord, DocumentRegistry
from app.services.engineering_converters import (
    ConversionResult,
    EngineeringConverter,
    get_engineering_converter,
)
from app.services.engineering_files import (
    SUPPORTED_INGEST_EXTENSIONS,
    ClassificationResult,
    classify,
)
from app.services.visual_elements import VISUAL_ELEMENT_TYPES

SUPPORTED_EXTENSIONS = tuple(sorted(SUPPORTED_INGEST_EXTENSIONS))
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150


@dataclass(frozen=True, slots=True)
class RegisteredIngestFile:
    """A registry row queued for ingestion.

    `is_duplicate` is the result returned by `DocumentRegistry.register_or_get`.
    Duplicate rows are not parsed or remembered again; their persisted memory ids
    are returned so the API response remains backward-compatible. `folder_segments`
    carries recursive path context for folder ingestion so backup/archive-style
    directories can reuse the shared classifier without duplicating it. The
    optional classification result is carried forward when the caller has already
    resolved it so the converter vs parser route does not need to be re-derived.
    """

    record: DocumentRecord
    is_duplicate: bool
    folder_segments: tuple[str, ...] = ()
    classification: ClassificationResult | None = None


def classify_and_route_registered_files(
    registry: DocumentRegistry,
    entries: Iterable[RegisteredIngestFile],
) -> list[RegisteredIngestFile]:
    """Classify registry-backed uploads and persist classifier skips."""
    routed_entries: list[RegisteredIngestFile] = []
    for entry in entries:
        if entry.is_duplicate:
            routed_entries.append(entry)
            continue

        classification = _classification_for_entry(entry)
        if classification.route == "skip":
            if classification.reason is None:
                raise RuntimeError("classifier returned skip without a reason")
            registry.mark_skipped(entry.record.document_id, reason=classification.reason)
            continue

        routed_entries.append(
            entry
            if entry.classification is not None
            else replace(entry, classification=classification)
        )

    return routed_entries


def _classification_for_entry(entry: RegisteredIngestFile) -> ClassificationResult:
    if entry.classification is not None:
        return entry.classification
    return classify(entry.record.original_filename, folder_segments=entry.folder_segments)


def _conversion_registry_outcome(conversion: ConversionResult) -> tuple[str, str]:
    if conversion.status in {"missing_configuration", "unsupported_extension"}:
        return "skipped", conversion.status
    return "failed", conversion.error or conversion.status


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
    engineering_converter: EngineeringConverter | None = None,
    engineering_converter_output_dir: str | None = None,
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
    converter = engineering_converter or get_engineering_converter()

    for entry in entries:
        record = entry.record
        if entry.is_duplicate:
            latest_record = registry.get_by_id(record.document_id) or record
            memory_ids.extend(latest_record.memory_ids)
            continue

        classification = _classification_for_entry(entry)
        if classification.route == "skip":
            if classification.reason is None:
                raise RuntimeError("classifier returned skip without a reason")
            registry.mark_skipped(record.document_id, reason=classification.reason)
            continue

        if classification.route == "converter":
            registry.update_status(record.document_id, "processing", error=None)
            conversion = converter.convert(record.stored_path)
            if not conversion.success:
                registry_status, registry_error = _conversion_registry_outcome(conversion)
                registry.update_status(
                    record.document_id,
                    registry_status,
                    error=registry_error,
                )
                continue

            if conversion.output_path is None:
                registry.update_status(
                    record.document_id,
                    "failed",
                    error="converter did not provide an output path",
                )
                continue

            try:
                file_delta, file_memory_ids = await _ingest_path(
                    kb,
                    conversion.output_path,
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
    registry: DocumentRegistry,
    directory: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    document_analyzer: DocumentAnalyzer | None = None,
    engineering_converter: EngineeringConverter | None = None,
    engineering_converter_output_dir: str | None = None,
) -> IngestResponse:
    if not os.path.isdir(directory):
        return IngestResponse(ingested_files=0, ingested_chunks=0)

    entries: list[RegisteredIngestFile] = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames[:] = [name for name in sorted(dirnames) if not name.startswith(".")]
        rel_root = os.path.relpath(root, directory)
        folder_segments: tuple[str, ...] = ()
        if rel_root != os.curdir:
            folder_segments = tuple(
                segment for segment in rel_root.split(os.sep) if segment and segment != os.curdir
            )

        for filename in sorted(filenames):
            path = os.path.join(root, filename)
            with open(path, "rb") as file:
                body = file.read()
            content_hash = hashlib.sha256(body).hexdigest()
            record, is_duplicate = registry.register_or_get(
                content_hash,
                original_filename=filename,
                stored_path=path,
                content_type="",
                byte_size=len(body),
            )
            entries.append(
                RegisteredIngestFile(
                    record=record,
                    is_duplicate=is_duplicate,
                    folder_segments=folder_segments,
                    classification=classify(filename, folder_segments=folder_segments),
                )
            )

    routed_entries = classify_and_route_registered_files(registry, entries)
    return await ingest_registered_files(
        kb,
        registry,
        routed_entries,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        document_analyzer=document_analyzer,
        engineering_converter=engineering_converter,
        engineering_converter_output_dir=engineering_converter_output_dir,
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
