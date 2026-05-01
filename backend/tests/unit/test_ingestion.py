"""Tests for the document ingestion pipeline (text + markdown loaders, chunker)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.kb.fake import FakeKB
from app.services.ingestion import (
    DEFAULT_CHUNK_SIZE,
    _chunk,
    ingest_directory,
    ingest_files,
)


class TestChunker:
    def test_short_text_yields_one_chunk(self) -> None:
        out = list(_chunk("hello world", size=100, overlap=10))
        assert out == ["hello world"]

    def test_long_text_yields_overlapping_chunks(self) -> None:
        text = "ABCDEFGHIJ" * 5  # 50 chars
        out = list(_chunk(text, size=20, overlap=5))
        assert all(len(c) <= 20 for c in out)
        # Step is 15, so we expect ceil(50 / 15) = 4 chunks.
        assert len(out) == 4
        # Overlap is observable.
        assert out[0][-5:] == out[1][:5]

    def test_empty_text_yields_nothing(self) -> None:
        assert list(_chunk("", size=20, overlap=5)) == []

    def test_invalid_overlap_raises(self) -> None:
        with pytest.raises(ValueError):
            list(_chunk("abc", size=10, overlap=10))


class TestIngestFiles:
    async def test_ingest_text_file(self, tmp_path: Path) -> None:
        path = tmp_path / "note.txt"
        path.write_text("the cat sat on the mat")
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 1
        assert result.ingested_chunks == 1
        records = kb.dump()
        assert len(records) == 1
        assert records[0]["metadata"]["source"] == "note.txt"

    async def test_ingest_markdown_file(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.md"
        path.write_text("# Title\n\nSome content here")
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 1
        assert result.ingested_chunks >= 1

    async def test_ingest_skips_missing_files(self, tmp_path: Path) -> None:
        kb = FakeKB()
        result = await ingest_files(kb, [str(tmp_path / "missing.txt")])
        assert result.ingested_files == 0
        assert result.ingested_chunks == 0

    async def test_ingest_chunks_long_file(self, tmp_path: Path) -> None:
        path = tmp_path / "big.txt"
        path.write_text("X" * (DEFAULT_CHUNK_SIZE * 3))
        kb = FakeKB()
        result = await ingest_files(kb, [str(path)])
        assert result.ingested_files == 1
        assert result.ingested_chunks >= 3


class TestIngestDirectory:
    async def test_ingests_supported_extensions_only(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        (tmp_path / "c.bin").write_bytes(b"\x00\x01\x02")
        kb = FakeKB()
        result = await ingest_directory(kb, str(tmp_path))
        assert result.ingested_files == 2

    async def test_missing_directory_is_a_noop(self, tmp_path: Path) -> None:
        kb = FakeKB()
        result = await ingest_directory(kb, str(tmp_path / "nope"))
        assert result.ingested_files == 0
