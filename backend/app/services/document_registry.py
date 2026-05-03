"""SQLite-backed document registry for uploaded document lifecycle state."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

DocumentStatus = Literal["uploaded", "processing", "indexed", "failed", "skipped"]
ALLOWED_DOCUMENT_STATUSES: tuple[DocumentStatus, ...] = (
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "skipped",
)
_ALLOWED_STATUS_SET = set(ALLOWED_DOCUMENT_STATUSES)


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Durable metadata for one unique uploaded document body."""

    document_id: str
    content_hash: str
    original_filename: str
    stored_path: str
    content_type: str
    byte_size: int
    uploaded_at: str
    status: DocumentStatus
    error: str | None
    memory_ids: list[str]


class DocumentRegistry:
    """Owns document metadata and dedupe state in a private SQLite database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensure_schema()

    def register_or_get(
        self,
        content_hash: str,
        *,
        original_filename: str,
        stored_path: str,
        content_type: str,
        byte_size: int,
        document_id: str | None = None,
        uploaded_at: str | None = None,
    ) -> tuple[DocumentRecord, bool]:
        """Create a registry row for a content hash or return the existing row.

        Returns `(record, is_duplicate)`. Duplicate uploads are keyed only by
        `content_hash`; when a row already exists, its original metadata is left
        untouched and returned.
        """
        clean_hash = content_hash.strip()
        if not clean_hash:
            raise ValueError("content_hash must not be empty")
        if byte_size < 0:
            raise ValueError("byte_size must be greater than or equal to 0")

        candidate_id = (document_id or uuid.uuid4().hex).strip()
        if not candidate_id:
            raise ValueError("document_id must not be empty")
        timestamp = uploaded_at or datetime.now(UTC).isoformat()

        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', NULL, '[]')
                    ON CONFLICT(content_hash) DO NOTHING
                    """,
                    (
                        candidate_id,
                        clean_hash,
                        original_filename,
                        stored_path,
                        content_type,
                        byte_size,
                        timestamp,
                    ),
                )
                is_duplicate = cursor.rowcount == 0

            record = self.get_by_hash(clean_hash)
            if record is None:
                raise RuntimeError("document registry insert did not produce a row")
            return record, is_duplicate

    def update_status(
        self,
        document_id: str,
        status: str,
        *,
        error: str | None = None,
        memory_ids: Sequence[str] | None = None,
    ) -> DocumentRecord:
        """Update processing status and optional result metadata for a document."""
        valid_status = _validate_status(status)

        with self._lock:
            with self._conn:
                if memory_ids is None:
                    cursor = self._conn.execute(
                        """
                        UPDATE documents
                        SET status = ?, error = ?
                        WHERE document_id = ?
                        """,
                        (valid_status, error, document_id),
                    )
                else:
                    cursor = self._conn.execute(
                        """
                        UPDATE documents
                        SET status = ?, error = ?, memory_ids = ?
                        WHERE document_id = ?
                        """,
                        (valid_status, error, json.dumps(list(memory_ids)), document_id),
                    )
                if cursor.rowcount == 0:
                    raise KeyError(document_id)

            record = self.get_by_id(document_id)
            if record is None:
                raise KeyError(document_id)
            return record

    def mark_skipped(self, document_id: str, *, reason: str) -> DocumentRecord:
        """Record a classifier-driven skip reason for a document."""
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("reason must not be empty")
        # error carries the SkipReason literal for skipped rows; parser failures keep text.
        return self.update_status(document_id, "skipped", error=clean_reason)

    def get_by_id(self, document_id: str) -> DocumentRecord | None:
        """Return a registry row by stable document id, if present."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT document_id, content_hash, original_filename, stored_path,
                       content_type, byte_size, uploaded_at, status, error, memory_ids
                FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def get_by_hash(self, content_hash: str) -> DocumentRecord | None:
        """Return a registry row by content hash, if present."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT document_id, content_hash, original_filename, stored_path,
                       content_type, byte_size, uploaded_at, status, error, memory_ids
                FROM documents
                WHERE content_hash = ?
                """,
                (content_hash,),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_all(self) -> Sequence[DocumentRecord]:
        """Return every registry row in deterministic upload order."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT document_id, content_hash, original_filename, stored_path,
                       content_type, byte_size, uploaded_at, status, error, memory_ids
                FROM documents
                ORDER BY uploaded_at ASC, document_id ASC
                """,
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def _ensure_schema(self) -> None:
        allowed_statuses = ", ".join(f"'{status}'" for status in ALLOWED_DOCUMENT_STATUSES)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS documents (
                        document_id TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL UNIQUE,
                        original_filename TEXT NOT NULL,
                        stored_path TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        byte_size INTEGER NOT NULL,
                        uploaded_at TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ({allowed_statuses})),
                        error TEXT,
                        memory_ids TEXT NOT NULL DEFAULT '[]'
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_documents_content_hash
                    ON documents(content_hash)
                    """
                )


@asynccontextmanager
async def lifespan_document_registry(
    db_path: str | Path,
) -> AsyncIterator[DocumentRegistry]:
    """Open the document registry for the lifetime of the app.

    Pass `":memory:"` for tests. File-backed databases create parent directories
    before opening so first-run local/container startup is friction-free.
    """
    path = str(db_path)
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    registry = DocumentRegistry(conn)
    try:
        yield registry
    finally:
        registry.close()


def _validate_status(status: str) -> DocumentStatus:
    if status not in _ALLOWED_STATUS_SET:
        raise ValueError(f"invalid document status: {status}")
    return cast(DocumentStatus, status)


def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
    memory_ids = json.loads(row["memory_ids"])
    if not isinstance(memory_ids, list) or not all(isinstance(item, str) for item in memory_ids):
        raise ValueError("document registry memory_ids must be a JSON list of strings")

    return DocumentRecord(
        document_id=row["document_id"],
        content_hash=row["content_hash"],
        original_filename=row["original_filename"],
        stored_path=row["stored_path"],
        content_type=row["content_type"],
        byte_size=row["byte_size"],
        uploaded_at=row["uploaded_at"],
        status=_validate_status(row["status"]),
        error=row["error"],
        memory_ids=memory_ids,
    )
