"""Tests for the SQLite-backed document registry."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.services.document_registry import lifespan_document_registry


class TestDocumentRegistry:
    async def test_registers_document_and_reads_by_id_or_hash(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "hash-1",
                document_id="doc-1",
                original_filename="plan.pdf",
                stored_path="/app/data/documents/doc-1.pdf",
                content_type="application/pdf",
                byte_size=123,
                uploaded_at="2026-05-01T10:00:00+00:00",
            )

            assert is_duplicate is False
            assert record.document_id == "doc-1"
            assert record.content_hash == "hash-1"
            assert record.original_filename == "plan.pdf"
            assert record.stored_path == "/app/data/documents/doc-1.pdf"
            assert record.content_type == "application/pdf"
            assert record.byte_size == 123
            assert record.uploaded_at == "2026-05-01T10:00:00+00:00"
            assert record.status == "uploaded"
            assert record.error is None
            assert record.memory_ids == []
            assert registry.get_by_id("doc-1") == record
            assert registry.get_by_hash("hash-1") == record

    async def test_duplicate_content_hash_returns_existing_row_untouched(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, is_duplicate = registry.register_or_get(
                "same-hash",
                document_id="doc-original",
                original_filename="first.txt",
                stored_path="/app/data/documents/doc-original.txt",
                content_type="text/plain",
                byte_size=5,
                uploaded_at="2026-05-01T10:00:00+00:00",
            )
            assert is_duplicate is False

            indexed = registry.update_status(
                record.document_id,
                "indexed",
                memory_ids=["memory-1", "memory-2"],
            )
            duplicate, duplicate_flag = registry.register_or_get(
                "same-hash",
                document_id="doc-duplicate",
                original_filename="second.txt",
                stored_path="/app/data/documents/doc-duplicate.txt",
                content_type="text/plain",
                byte_size=999,
                uploaded_at="2026-05-01T11:00:00+00:00",
            )

            assert duplicate_flag is True
            assert duplicate == indexed
            assert duplicate.document_id == "doc-original"
            assert duplicate.original_filename == "first.txt"
            assert duplicate.stored_path == "/app/data/documents/doc-original.txt"
            assert duplicate.byte_size == 5
            assert duplicate.memory_ids == ["memory-1", "memory-2"]
            assert registry.get_by_id("doc-duplicate") is None

    async def test_updates_status_error_and_memory_ids(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-2",
                document_id="doc-2",
                original_filename="notes.md",
                stored_path="/app/data/documents/doc-2.md",
                content_type="text/markdown",
                byte_size=50,
            )

            processing = registry.update_status(record.document_id, "processing")
            assert processing.status == "processing"
            assert processing.error is None
            assert processing.memory_ids == []

            failed = registry.update_status(record.document_id, "failed", error="parser boom")
            assert failed.status == "failed"
            assert failed.error == "parser boom"
            assert failed.memory_ids == []

            indexed = registry.update_status(
                record.document_id,
                "indexed",
                memory_ids=["memory-final"],
            )
            assert indexed.status == "indexed"
            assert indexed.error is None
            assert indexed.memory_ids == ["memory-final"]

    async def test_mark_skipped_persists_reason(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-skip",
                document_id="doc-skip",
                original_filename="skip.docx",
                stored_path="/app/data/documents/doc-skip.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                byte_size=22,
            )

            skipped = registry.mark_skipped(record.document_id, reason="docx_extractor_pending")

            assert skipped.status == "skipped"
            assert skipped.error == "docx_extractor_pending"
            assert skipped.memory_ids == []
            assert registry.get_by_id(record.document_id) == skipped

    async def test_list_all_returns_empty_sequence_when_no_documents(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            assert registry.list_all() == []

    async def test_list_all_returns_indexed_skipped_and_failed_rows(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            indexed_record, _ = registry.register_or_get(
                "hash-indexed",
                document_id="doc-indexed",
                original_filename="indexed.txt",
                stored_path="/app/data/documents/doc-indexed.txt",
                content_type="text/plain",
                byte_size=10,
                uploaded_at="2026-05-01T10:00:00+00:00",
            )
            skipped_record, _ = registry.register_or_get(
                "hash-skipped",
                document_id="doc-skipped",
                original_filename="skipped.txt",
                stored_path="/app/data/documents/doc-skipped.txt",
                content_type="text/plain",
                byte_size=11,
                uploaded_at="2026-05-01T11:00:00+00:00",
            )
            failed_record, _ = registry.register_or_get(
                "hash-failed",
                document_id="doc-failed",
                original_filename="failed.txt",
                stored_path="/app/data/documents/doc-failed.txt",
                content_type="text/plain",
                byte_size=12,
                uploaded_at="2026-05-01T12:00:00+00:00",
            )

            indexed = registry.update_status(
                indexed_record.document_id,
                "indexed",
                memory_ids=["memory-indexed"],
            )
            skipped = registry.mark_skipped(
                skipped_record.document_id,
                reason="docx_extractor_pending",
            )
            failed = registry.update_status(
                failed_record.document_id,
                "failed",
                error="parser boom",
            )

            assert registry.list_all() == [indexed, skipped, failed]
            assert indexed.error is None
            assert indexed.memory_ids == ["memory-indexed"]
            assert skipped.error == "docx_extractor_pending"
            assert skipped.memory_ids == []
            assert failed.error == "parser boom"
            assert failed.memory_ids == []

    async def test_list_all_orders_by_uploaded_at_then_document_id(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            later_record, _ = registry.register_or_get(
                "hash-later",
                document_id="doc-z",
                original_filename="later.txt",
                stored_path="/app/data/documents/doc-z.txt",
                content_type="text/plain",
                byte_size=20,
                uploaded_at="2026-05-01T10:00:00+00:00",
            )
            earlier_record, _ = registry.register_or_get(
                "hash-earlier",
                document_id="doc-a",
                original_filename="earlier.txt",
                stored_path="/app/data/documents/doc-a.txt",
                content_type="text/plain",
                byte_size=21,
                uploaded_at="2026-05-01T10:00:00+00:00",
            )

            assert registry.list_all() == [earlier_record, later_record]

    async def test_mark_skipped_rejects_blank_reason(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-skip-empty",
                document_id="doc-skip-empty",
                original_filename="skip-empty.docx",
                stored_path="/app/data/documents/doc-skip-empty.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                byte_size=23,
            )

            with pytest.raises(ValueError, match="reason must not be empty"):
                registry.mark_skipped(record.document_id, reason="   ")

    async def test_update_status_accepts_skipped_and_rejects_bogus(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-skip-update",
                document_id="doc-skip-update",
                original_filename="skip-update.docx",
                stored_path="/app/data/documents/doc-skip-update.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                byte_size=24,
            )

            skipped = registry.update_status(
                record.document_id,
                "skipped",
                error="missing_configuration",
            )
            assert skipped.status == "skipped"
            assert skipped.error == "missing_configuration"
            assert skipped.memory_ids == []

            with pytest.raises(ValueError, match="invalid document status"):
                registry.update_status(record.document_id, "bogus")

    async def test_database_check_constraint_still_rejects_unknown_status(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-constraint",
                document_id="doc-constraint",
                original_filename="plan.pdf",
                stored_path="/app/data/documents/doc-constraint.pdf",
                content_type="application/pdf",
                byte_size=12,
            )
            indexed = registry.update_status(record.document_id, "indexed", memory_ids=["memory-1"])
            assert indexed.status == "indexed"

            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                with registry._conn:
                    registry._conn.execute(
                        """
                        INSERT INTO documents (
                            document_id,
                            content_hash,
                            original_filename,
                            stored_path,
                            content_type,
                            byte_size,
                            uploaded_at,
                            status,
                            error,
                            memory_ids
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "doc-bad",
                            "hash-bad",
                            "bad.txt",
                            "/app/data/documents/bad.txt",
                            "text/plain",
                            1,
                            "2026-05-01T12:00:00+00:00",
                            "bogus",
                            None,
                            "[]",
                        ),
                    )

    async def test_rejects_invalid_status(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            record, _ = registry.register_or_get(
                "hash-3",
                document_id="doc-3",
                original_filename="note.txt",
                stored_path="/app/data/documents/doc-3.txt",
                content_type="text/plain",
                byte_size=1,
            )

            with pytest.raises(ValueError, match="invalid document status"):
                registry.update_status(record.document_id, "unknown")

    async def test_rejects_empty_content_hash(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            with pytest.raises(ValueError, match="content_hash"):
                registry.register_or_get(
                    "   ",
                    document_id="doc-empty",
                    original_filename="note.txt",
                    stored_path="/app/data/documents/doc-empty.txt",
                    content_type="text/plain",
                    byte_size=1,
                )

    async def test_update_unknown_document_raises_key_error(self) -> None:
        async with lifespan_document_registry(":memory:") as registry:
            with pytest.raises(KeyError):
                registry.update_status("missing-document", "processing")

    async def test_file_registry_persists_across_reopen_cycles(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "registry.sqlite"

        async with lifespan_document_registry(db_path) as registry:
            record, is_duplicate = registry.register_or_get(
                "persistent-hash",
                document_id="doc-persistent",
                original_filename="persist.txt",
                stored_path="/app/data/documents/doc-persistent.txt",
                content_type="text/plain",
                byte_size=10,
            )
            assert is_duplicate is False
            registry.update_status(record.document_id, "indexed", memory_ids=["memory-1"])

        assert db_path.exists()

        async with lifespan_document_registry(db_path) as registry:
            restored = registry.get_by_hash("persistent-hash")
            assert restored is not None
            assert restored.document_id == "doc-persistent"
            assert restored.status == "indexed"
            assert restored.memory_ids == ["memory-1"]

            duplicate, is_duplicate = registry.register_or_get(
                "persistent-hash",
                document_id="doc-new",
                original_filename="new-name.txt",
                stored_path="/app/data/documents/doc-new.txt",
                content_type="text/plain",
                byte_size=99,
            )
            assert is_duplicate is True
            assert duplicate == restored


def test_settings_exposes_registry_db_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REGISTRY_DB_PATH", raising=False)

    assert Settings(_env_file=None).registry_db_path == "/app/data/registry.sqlite"
