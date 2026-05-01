"""Document ingestion pipeline.

Loads PDF / Markdown / plain-text files, chunks them into reasonable pieces,
and writes each chunk into the KnowledgeBase tagged with `source` metadata.

We deliberately use a tiny hand-rolled chunker so we have zero embedding
dependencies in this layer; MemoryPalace handles embeddings itself when the
real backend is configured.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from app.kb.base import KnowledgeBase
from app.schemas import IngestResponse

SUPPORTED_EXTENSIONS = (".pdf", ".md", ".markdown", ".txt")
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150


async def ingest_files(
    kb: KnowledgeBase,
    paths: Iterable[str],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> IngestResponse:
    file_count = 0
    chunk_count = 0
    memory_ids: list[str] = []

    for path in paths:
        if not os.path.isfile(path):
            continue
        text = _load_file(path)
        if not text.strip():
            continue
        file_count += 1
        chunks = list(_chunk(text, chunk_size, chunk_overlap))
        for chunk in chunks:
            mid = await kb.remember(
                chunk,
                metadata={
                    "source": os.path.basename(path),
                    "path": path,
                },
            )
            memory_ids.append(mid)
            chunk_count += 1

    return IngestResponse(
        ingested_files=file_count,
        ingested_chunks=chunk_count,
        memory_ids=memory_ids,
    )


async def ingest_directory(
    kb: KnowledgeBase,
    directory: str,
    **kwargs,
) -> IngestResponse:
    if not os.path.isdir(directory):
        return IngestResponse(ingested_files=0, ingested_chunks=0)
    paths = [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.lower().endswith(SUPPORTED_EXTENSIONS)
    ]
    return await ingest_files(kb, paths, **kwargs)


def _load_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _load_pdf(path)
    if ext in (".md", ".markdown", ".txt"):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return ""


def _load_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


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
