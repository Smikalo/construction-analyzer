"""SQLite-backed sidecar for durable report-run sessions and observability."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.schemas import (
    ReportArtifactKind,
    ReportExportStatus,
    ReportGateStatus,
    ReportLogLevel,
    ReportSessionStatus,
    ReportStageStatus,
    ReportValidationSeverity,
)

ALLOWED_REPORT_SESSION_STATUSES: tuple[ReportSessionStatus, ...] = (
    "pending",
    "active",
    "blocked",
    "complete",
    "failed",
)
ALLOWED_REPORT_STAGE_STATUSES: tuple[ReportStageStatus, ...] = (
    "pending",
    "active",
    "complete",
    "failed",
)
ALLOWED_REPORT_GATE_STATUSES: tuple[ReportGateStatus, ...] = ("open", "closed")
ALLOWED_REPORT_LOG_LEVELS: tuple[ReportLogLevel, ...] = ("debug", "info", "warning", "error")
ALLOWED_REPORT_VALIDATION_SEVERITIES: tuple[ReportValidationSeverity, ...] = (
    "info",
    "warning",
    "blocker",
)
ALLOWED_REPORT_EXPORT_STATUSES: tuple[ReportExportStatus, ...] = (
    "pending",
    "ready",
    "failed",
)

_SESSION_STATUS_SET = set(ALLOWED_REPORT_SESSION_STATUSES)
_STAGE_STATUS_SET = set(ALLOWED_REPORT_STAGE_STATUSES)
_GATE_STATUS_SET = set(ALLOWED_REPORT_GATE_STATUSES)
_LOG_LEVEL_SET = set(ALLOWED_REPORT_LOG_LEVELS)
_VALIDATION_SEVERITY_SET = set(ALLOWED_REPORT_VALIDATION_SEVERITIES)
_EXPORT_STATUS_SET = set(ALLOWED_REPORT_EXPORT_STATUSES)


@dataclass(frozen=True, slots=True)
class ReportSessionRecord:
    session_id: str
    status: ReportSessionStatus
    current_stage: str | None
    created_at: str
    updated_at: str | None
    last_error: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReportStageRecord:
    stage_id: str
    session_id: str
    name: str
    status: ReportStageStatus
    started_at: str | None
    completed_at: str | None
    summary: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ReportGateRecord:
    gate_id: str
    session_id: str
    stage_id: str | None
    status: ReportGateStatus
    question: dict[str, Any]
    answer: dict[str, Any]
    created_at: str
    closed_at: str | None


@dataclass(frozen=True, slots=True)
class ReportArtifactRecord:
    artifact_id: str
    session_id: str
    stage_id: str | None
    kind: ReportArtifactKind
    content: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ReportLogRecord:
    log_id: str
    session_id: str
    stage_id: str | None
    level: ReportLogLevel
    message: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ReportValidationFindingRecord:
    finding_id: str
    session_id: str
    severity: ReportValidationSeverity
    code: str | None
    message: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ReportExportRecord:
    export_id: str
    session_id: str
    status: ReportExportStatus
    format: str
    output_path: str | None
    diagnostics: dict[str, Any]
    created_at: str
    completed_at: str | None


class ReportSessionStore:
    """Own durable report-session state in a private SQLite database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensure_schema()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def create_session(
        self,
        session_id: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ReportSessionRecord:
        """Create a new report session with optional stable session id."""
        candidate_id = (session_id or uuid.uuid4().hex).strip()
        if not candidate_id:
            raise ValueError("session_id must not be empty")
        timestamp = created_at or _now_iso()
        metadata_json = _json_dumps_object(metadata, field_name="metadata")

        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO report_sessions (
                        session_id,
                        status,
                        current_stage,
                        created_at,
                        updated_at,
                        last_error,
                        metadata
                    )
                    VALUES (?, 'pending', NULL, ?, ?, NULL, ?)
                    """,
                    (candidate_id, timestamp, timestamp, metadata_json),
                )
                row = self._conn.execute(
                    """
                    SELECT session_id, status, current_stage, created_at, updated_at,
                           last_error, metadata
                    FROM report_sessions
                    WHERE session_id = ?
                    """,
                    (candidate_id,),
                ).fetchone()

        if row is None:
            raise RuntimeError("report session insert did not produce a row")
        return _row_to_session_record(row)

    def get_session(self, session_id: str) -> ReportSessionRecord | None:
        """Return one report session, if present."""
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    """
                    SELECT session_id, status, current_stage, created_at, updated_at,
                           last_error, metadata
                    FROM report_sessions
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
        return _row_to_session_record(row) if row is not None else None

    def update_session_status(
        self,
        session_id: str,
        status: str,
        *,
        current_stage: str | None = None,
        last_error: str | None = None,
        updated_at: str | None = None,
    ) -> ReportSessionRecord:
        """Update the durable status for a report session."""
        valid_status = _validate_session_status(status)
        timestamp = updated_at or _now_iso()

        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    UPDATE report_sessions
                    SET status = ?, current_stage = ?, last_error = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (valid_status, current_stage, last_error, timestamp, session_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError(session_id)
                row = self._conn.execute(
                    """
                    SELECT session_id, status, current_stage, created_at, updated_at,
                           last_error, metadata
                    FROM report_sessions
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()

        if row is None:
            raise KeyError(session_id)
        return _row_to_session_record(row)

    def start_stage(
        self,
        session_id: str,
        name: str,
        *,
        started_at: str | None = None,
    ) -> ReportStageRecord:
        """Create a new stage record for the session."""
        stage_id = uuid.uuid4().hex
        timestamp = started_at or _now_iso()

        with self._lock:
            with self._conn:
                self._require_session(session_id)
                self._conn.execute(
                    """
                    INSERT INTO report_stages (
                        stage_id,
                        session_id,
                        name,
                        status,
                        started_at,
                        completed_at,
                        summary,
                        error
                    )
                    VALUES (?, ?, ?, 'active', ?, NULL, NULL, NULL)
                    """,
                    (stage_id, session_id, name, timestamp),
                )
                row = self._conn.execute(
                    """
                    SELECT stage_id, session_id, name, status, started_at, completed_at,
                           summary, error
                    FROM report_stages
                    WHERE stage_id = ?
                    """,
                    (stage_id,),
                ).fetchone()

        if row is None:
            raise RuntimeError("report stage insert did not produce a row")
        return _row_to_stage_record(row)

    def complete_stage(
        self,
        stage_id: str,
        *,
        summary: str | None = None,
        completed_at: str | None = None,
    ) -> ReportStageRecord:
        """Mark a stage as complete."""
        timestamp = completed_at or _now_iso()

        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    UPDATE report_stages
                    SET status = 'complete', completed_at = ?, summary = ?, error = NULL
                    WHERE stage_id = ?
                    """,
                    (timestamp, summary, stage_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError(stage_id)
                row = self._conn.execute(
                    """
                    SELECT stage_id, session_id, name, status, started_at, completed_at,
                           summary, error
                    FROM report_stages
                    WHERE stage_id = ?
                    """,
                    (stage_id,),
                ).fetchone()

        if row is None:
            raise KeyError(stage_id)
        return _row_to_stage_record(row)

    def fail_stage(
        self,
        stage_id: str,
        *,
        error: str,
        completed_at: str | None = None,
    ) -> ReportStageRecord:
        """Mark a stage as failed with a captured error."""
        timestamp = completed_at or _now_iso()

        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    UPDATE report_stages
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE stage_id = ?
                    """,
                    (timestamp, error, stage_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError(stage_id)
                row = self._conn.execute(
                    """
                    SELECT stage_id, session_id, name, status, started_at, completed_at,
                           summary, error
                    FROM report_stages
                    WHERE stage_id = ?
                    """,
                    (stage_id,),
                ).fetchone()

        if row is None:
            raise KeyError(stage_id)
        return _row_to_stage_record(row)

    def list_stages(self, session_id: str) -> list[ReportStageRecord]:
        """Return all stages for a session ordered by their start time."""
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT stage_id, session_id, name, status, started_at, completed_at,
                           summary, error
                    FROM report_stages
                    WHERE session_id = ?
                    ORDER BY started_at, stage_id
                    """,
                    (session_id,),
                ).fetchall()
        return [_row_to_stage_record(row) for row in rows]

    def open_gate(
        self,
        session_id: str,
        *,
        stage_id: str | None = None,
        question: dict[str, Any],
        gate_id: str | None = None,
        created_at: str | None = None,
    ) -> ReportGateRecord:
        """Record a gate question as open."""
        candidate_id = (gate_id or uuid.uuid4().hex).strip()
        if not candidate_id:
            raise ValueError("gate_id must not be empty")
        timestamp = created_at or _now_iso()
        question_json = _json_dumps_object(question, field_name="question")

        with self._lock:
            with self._conn:
                self._require_session(session_id)
                if stage_id is not None:
                    self._require_stage(stage_id)
                self._conn.execute(
                    """
                    INSERT INTO report_gates (
                        gate_id,
                        session_id,
                        stage_id,
                        question,
                        answer,
                        status,
                        created_at,
                        closed_at
                    )
                    VALUES (?, ?, ?, ?, '{}', 'open', ?, NULL)
                    """,
                    (candidate_id, session_id, stage_id, question_json, timestamp),
                )
                row = self._conn.execute(
                    """
                    SELECT gate_id, session_id, stage_id, question, answer, status,
                           created_at, closed_at
                    FROM report_gates
                    WHERE session_id = ? AND gate_id = ?
                    """,
                    (session_id, candidate_id),
                ).fetchone()

        if row is None:
            raise RuntimeError("report gate insert did not produce a row")
        return _row_to_gate_record(row)

    def close_gate(
        self,
        gate_id: str,
        *,
        answer: dict[str, Any],
        closed_at: str | None = None,
        session_id: str | None = None,
    ) -> ReportGateRecord:
        """Close a gate by persisting the answer payload."""
        timestamp = closed_at or _now_iso()
        answer_json = _json_dumps_object(answer, field_name="answer")

        with self._lock:
            with self._conn:
                target_session_id = self._resolve_gate_session_id(gate_id, session_id=session_id)
                cursor = self._conn.execute(
                    """
                    UPDATE report_gates
                    SET status = 'closed', answer = ?, closed_at = ?
                    WHERE session_id = ? AND gate_id = ?
                    """,
                    (answer_json, timestamp, target_session_id, gate_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError(gate_id)
                row = self._conn.execute(
                    """
                    SELECT gate_id, session_id, stage_id, question, answer, status,
                           created_at, closed_at
                    FROM report_gates
                    WHERE session_id = ? AND gate_id = ?
                    """,
                    (target_session_id, gate_id),
                ).fetchone()

        if row is None:
            raise KeyError(gate_id)
        return _row_to_gate_record(row)

    def _resolve_gate_session_id(self, gate_id: str, *, session_id: str | None) -> str:
        """Resolve the owning session for a gate id, preserving legacy single-id callers."""
        if session_id is not None:
            row = self._conn.execute(
                """
                SELECT session_id
                FROM report_gates
                WHERE session_id = ? AND gate_id = ?
                """,
                (session_id, gate_id),
            ).fetchone()
            if row is None:
                raise KeyError(gate_id)
            return str(row["session_id"])

        rows = self._conn.execute(
            """
            SELECT session_id
            FROM report_gates
            WHERE gate_id = ?
            ORDER BY created_at, session_id
            LIMIT 2
            """,
            (gate_id,),
        ).fetchall()
        if not rows:
            raise KeyError(gate_id)
        if len(rows) > 1:
            raise ValueError("gate_id matches multiple sessions; provide session_id")
        return str(rows[0]["session_id"])

    def list_gates(self, session_id: str) -> list[ReportGateRecord]:
        """Return all gates for a session ordered by creation time."""
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT gate_id, session_id, stage_id, question, answer, status,
                           created_at, closed_at
                    FROM report_gates
                    WHERE session_id = ?
                    ORDER BY created_at, gate_id
                    """,
                    (session_id,),
                ).fetchall()
        return [_row_to_gate_record(row) for row in rows]

    def record_artifact(
        self,
        session_id: str,
        *,
        stage_id: str | None = None,
        kind: ReportArtifactKind,
        content: dict[str, Any],
        created_at: str | None = None,
    ) -> ReportArtifactRecord:
        """Persist a report artifact tied to a session or stage."""
        artifact_id = uuid.uuid4().hex
        timestamp = created_at or _now_iso()
        content_json = _json_dumps_object(content, field_name="content")

        with self._lock:
            with self._conn:
                self._require_session(session_id)
                if stage_id is not None:
                    self._require_stage(stage_id)
                self._conn.execute(
                    """
                    INSERT INTO report_artifacts (
                        artifact_id,
                        session_id,
                        stage_id,
                        kind,
                        content,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (artifact_id, session_id, stage_id, kind, content_json, timestamp),
                )
                row = self._conn.execute(
                    """
                    SELECT artifact_id, session_id, stage_id, kind, content, created_at
                    FROM report_artifacts
                    WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()

        if row is None:
            raise RuntimeError("report artifact insert did not produce a row")
        return _row_to_artifact_record(row)

    def list_artifacts(self, session_id: str) -> list[ReportArtifactRecord]:
        """Return all artifacts for a session ordered by creation time."""
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT artifact_id, session_id, stage_id, kind, content, created_at
                    FROM report_artifacts
                    WHERE session_id = ?
                    ORDER BY created_at, artifact_id
                    """,
                    (session_id,),
                ).fetchall()
        return [_row_to_artifact_record(row) for row in rows]

    def append_log(
        self,
        session_id: str,
        *,
        level: str,
        message: str,
        stage_id: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ReportLogRecord:
        """Append an observability log record for the report run."""
        valid_level = _validate_log_level(level)
        log_id = uuid.uuid4().hex
        timestamp = created_at or _now_iso()
        payload_json = _json_dumps_object(payload, field_name="payload")

        with self._lock:
            with self._conn:
                self._require_session(session_id)
                if stage_id is not None:
                    self._require_stage(stage_id)
                self._conn.execute(
                    """
                    INSERT INTO report_logs (
                        log_id,
                        session_id,
                        stage_id,
                        level,
                        message,
                        payload,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (log_id, session_id, stage_id, valid_level, message, payload_json, timestamp),
                )
                row = self._conn.execute(
                    """
                    SELECT log_id, session_id, stage_id, level, message, payload,
                           created_at
                    FROM report_logs
                    WHERE log_id = ?
                    """,
                    (log_id,),
                ).fetchone()

        if row is None:
            raise RuntimeError("report log insert did not produce a row")
        return _row_to_log_record(row)

    def list_logs(self, session_id: str) -> list[ReportLogRecord]:
        """Return all log entries for a session ordered by time."""
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT log_id, session_id, stage_id, level, message, payload, created_at
                    FROM report_logs
                    WHERE session_id = ?
                    ORDER BY created_at, log_id
                    """,
                    (session_id,),
                ).fetchall()
        return [_row_to_log_record(row) for row in rows]

    def record_validation_finding(
        self,
        session_id: str,
        *,
        severity: str,
        code: str | None,
        message: str,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ReportValidationFindingRecord:
        """Persist a structured validation finding for the report run."""
        valid_severity = _validate_validation_severity(severity)
        finding_id = uuid.uuid4().hex
        timestamp = created_at or _now_iso()
        payload_json = _json_dumps_object(payload, field_name="payload")

        with self._lock:
            with self._conn:
                self._require_session(session_id)
                self._conn.execute(
                    """
                    INSERT INTO report_validation_findings (
                        finding_id,
                        session_id,
                        severity,
                        code,
                        message,
                        payload,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_id,
                        session_id,
                        valid_severity,
                        code,
                        message,
                        payload_json,
                        timestamp,
                    ),
                )
                row = self._conn.execute(
                    """
                    SELECT finding_id, session_id, severity, code, message, payload,
                           created_at
                    FROM report_validation_findings
                    WHERE finding_id = ?
                    """,
                    (finding_id,),
                ).fetchone()

        if row is None:
            raise RuntimeError("report validation finding insert did not produce a row")
        return _row_to_finding_record(row)

    def list_validation_findings(self, session_id: str) -> list[ReportValidationFindingRecord]:
        """Return validation findings ordered by creation time."""
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT finding_id, session_id, severity, code, message, payload,
                           created_at
                    FROM report_validation_findings
                    WHERE session_id = ?
                    ORDER BY created_at, finding_id
                    """,
                    (session_id,),
                ).fetchall()
        return [_row_to_finding_record(row) for row in rows]

    def create_export(
        self,
        session_id: str,
        *,
        format: str,
        status: str = "pending",
        output_path: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ReportExportRecord:
        """Create a report export row."""
        valid_status = _validate_export_status(status)
        export_id = uuid.uuid4().hex
        timestamp = created_at or _now_iso()
        completed_at = timestamp if valid_status != "pending" else None
        diagnostics_json = _json_dumps_object(diagnostics, field_name="diagnostics")

        with self._lock:
            with self._conn:
                self._require_session(session_id)
                self._conn.execute(
                    """
                    INSERT INTO report_exports (
                        export_id,
                        session_id,
                        status,
                        format,
                        output_path,
                        diagnostics,
                        created_at,
                        completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        export_id,
                        session_id,
                        valid_status,
                        format,
                        output_path,
                        diagnostics_json,
                        timestamp,
                        completed_at,
                    ),
                )
                row = self._conn.execute(
                    """
                    SELECT export_id, session_id, status, format, output_path, diagnostics,
                           created_at, completed_at
                    FROM report_exports
                    WHERE export_id = ?
                    """,
                    (export_id,),
                ).fetchone()

        if row is None:
            raise RuntimeError("report export insert did not produce a row")
        return _row_to_export_record(row)

    def update_export(
        self,
        export_id: str,
        *,
        status: str,
        output_path: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> ReportExportRecord:
        """Update an export's status and completion metadata."""
        valid_status = _validate_export_status(status)
        timestamp = completed_at or _now_iso()
        diagnostics_json = _json_dumps_object(diagnostics, field_name="diagnostics")

        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    UPDATE report_exports
                    SET status = ?, output_path = ?, diagnostics = ?, completed_at = ?
                    WHERE export_id = ?
                    """,
                    (valid_status, output_path, diagnostics_json, timestamp, export_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError(export_id)
                row = self._conn.execute(
                    """
                    SELECT export_id, session_id, status, format, output_path, diagnostics,
                           created_at, completed_at
                    FROM report_exports
                    WHERE export_id = ?
                    """,
                    (export_id,),
                ).fetchone()

        if row is None:
            raise KeyError(export_id)
        return _row_to_export_record(row)

    def list_exports(self, session_id: str) -> list[ReportExportRecord]:
        """Return all exports for a session ordered by creation time."""
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT export_id, session_id, status, format, output_path, diagnostics,
                           created_at, completed_at
                    FROM report_exports
                    WHERE session_id = ?
                    ORDER BY created_at, export_id
                    """,
                    (session_id,),
                ).fetchall()
        return [_row_to_export_record(row) for row in rows]

    def _ensure_schema(self) -> None:
        allowed_session_statuses = ", ".join(
            f"'{status}'" for status in ALLOWED_REPORT_SESSION_STATUSES
        )
        allowed_stage_statuses = ", ".join(
            f"'{status}'" for status in ALLOWED_REPORT_STAGE_STATUSES
        )
        allowed_gate_statuses = ", ".join(f"'{status}'" for status in ALLOWED_REPORT_GATE_STATUSES)
        allowed_log_levels = ", ".join(f"'{status}'" for status in ALLOWED_REPORT_LOG_LEVELS)
        allowed_validation_severities = ", ".join(
            f"'{status}'" for status in ALLOWED_REPORT_VALIDATION_SEVERITIES
        )
        allowed_export_statuses = ", ".join(
            f"'{status}'" for status in ALLOWED_REPORT_EXPORT_STATUSES
        )

        with self._lock:
            with self._conn:
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS report_sessions (
                        session_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL CHECK (status IN ({allowed_session_statuses})),
                        current_stage TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT,
                        last_error TEXT,
                        metadata TEXT NOT NULL DEFAULT '{{}}'
                    )
                    """
                )
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS report_stages (
                        stage_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL
                            REFERENCES report_sessions(session_id)
                            ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ({allowed_stage_statuses})),
                        started_at TEXT,
                        completed_at TEXT,
                        summary TEXT,
                        error TEXT
                    )
                    """
                )
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS report_gates (
                        gate_id TEXT NOT NULL,
                        session_id TEXT NOT NULL
                            REFERENCES report_sessions(session_id)
                            ON DELETE CASCADE,
                        stage_id TEXT
                            REFERENCES report_stages(stage_id)
                            ON DELETE SET NULL,
                        question TEXT NOT NULL,
                        answer TEXT NOT NULL DEFAULT '{{}}',
                        status TEXT NOT NULL CHECK (status IN ({allowed_gate_statuses})),
                        created_at TEXT NOT NULL,
                        closed_at TEXT,
                        PRIMARY KEY (session_id, gate_id)
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS report_artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL
                            REFERENCES report_sessions(session_id)
                            ON DELETE CASCADE,
                        stage_id TEXT
                            REFERENCES report_stages(stage_id)
                            ON DELETE SET NULL,
                        kind TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS report_logs (
                        log_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL
                            REFERENCES report_sessions(session_id)
                            ON DELETE CASCADE,
                        stage_id TEXT
                            REFERENCES report_stages(stage_id)
                            ON DELETE SET NULL,
                        level TEXT NOT NULL CHECK (level IN ({allowed_log_levels})),
                        message TEXT NOT NULL,
                        payload TEXT NOT NULL DEFAULT '{{}}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS report_validation_findings (
                        finding_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL
                            REFERENCES report_sessions(session_id)
                            ON DELETE CASCADE,
                        severity TEXT NOT NULL
                            CHECK (severity IN ({allowed_validation_severities})),
                        code TEXT,
                        message TEXT NOT NULL,
                        payload TEXT NOT NULL DEFAULT '{{}}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS report_exports (
                        export_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL
                            REFERENCES report_sessions(session_id)
                            ON DELETE CASCADE,
                        status TEXT NOT NULL CHECK (status IN ({allowed_export_statuses})),
                        format TEXT NOT NULL,
                        output_path TEXT,
                        diagnostics TEXT NOT NULL DEFAULT '{{}}',
                        created_at TEXT NOT NULL,
                        completed_at TEXT
                    )
                    """
                )
                self._ensure_report_gates_session_scoped(allowed_gate_statuses)
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_report_stages_session_id
                    ON report_stages(session_id)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_report_gates_session_id
                    ON report_gates(session_id)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_report_artifacts_session_id
                    ON report_artifacts(session_id)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_report_logs_session_id
                    ON report_logs(session_id)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_report_validation_findings_session_id
                    ON report_validation_findings(session_id)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_report_exports_session_id
                    ON report_exports(session_id)
                    """
                )

    def _ensure_report_gates_session_scoped(self, allowed_gate_statuses: str) -> None:
        """Migrate fixed gate ids from global uniqueness to per-session uniqueness."""
        columns = self._conn.execute("PRAGMA table_info(report_gates)").fetchall()
        primary_key_columns = [
            row["name"] for row in sorted(columns, key=lambda row: row["pk"]) if row["pk"]
        ]
        if primary_key_columns == ["session_id", "gate_id"]:
            return

        self._conn.execute(
            f"""
            CREATE TABLE report_gates_session_scoped (
                gate_id TEXT NOT NULL,
                session_id TEXT NOT NULL
                    REFERENCES report_sessions(session_id)
                    ON DELETE CASCADE,
                stage_id TEXT
                    REFERENCES report_stages(stage_id)
                    ON DELETE SET NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '{{}}',
                status TEXT NOT NULL CHECK (status IN ({allowed_gate_statuses})),
                created_at TEXT NOT NULL,
                closed_at TEXT,
                PRIMARY KEY (session_id, gate_id)
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO report_gates_session_scoped (
                gate_id,
                session_id,
                stage_id,
                question,
                answer,
                status,
                created_at,
                closed_at
            )
            SELECT
                gate_id,
                session_id,
                stage_id,
                question,
                answer,
                status,
                created_at,
                closed_at
            FROM report_gates
            """
        )
        self._conn.execute("DROP TABLE report_gates")
        self._conn.execute("ALTER TABLE report_gates_session_scoped RENAME TO report_gates")

    def _require_session(self, session_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            """
            SELECT session_id
            FROM report_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return row

    def _require_stage(self, stage_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            """
            SELECT stage_id
            FROM report_stages
            WHERE stage_id = ?
            """,
            (stage_id,),
        ).fetchone()
        if row is None:
            raise KeyError(stage_id)
        return row


@asynccontextmanager
async def lifespan_report_sessions(db_path: str | Path) -> AsyncIterator[ReportSessionStore]:
    """Open the report-session store for the app lifespan."""
    path = str(db_path)
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    store = ReportSessionStore(conn)
    try:
        yield store
    finally:
        store.close()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_session_status(status: str) -> ReportSessionStatus:
    if status not in _SESSION_STATUS_SET:
        raise ValueError(f"invalid report session status: {status}")
    return cast(ReportSessionStatus, status)


def _validate_stage_status(status: str) -> ReportStageStatus:
    if status not in _STAGE_STATUS_SET:
        raise ValueError(f"invalid report stage status: {status}")
    return cast(ReportStageStatus, status)


def _validate_gate_status(status: str) -> ReportGateStatus:
    if status not in _GATE_STATUS_SET:
        raise ValueError(f"invalid report gate status: {status}")
    return cast(ReportGateStatus, status)


def _validate_log_level(level: str) -> ReportLogLevel:
    if level not in _LOG_LEVEL_SET:
        raise ValueError(f"invalid report log level: {level}")
    return cast(ReportLogLevel, level)


def _validate_validation_severity(severity: str) -> ReportValidationSeverity:
    if severity not in _VALIDATION_SEVERITY_SET:
        raise ValueError(f"invalid report validation severity: {severity}")
    return cast(ReportValidationSeverity, severity)


def _validate_export_status(status: str) -> ReportExportStatus:
    if status not in _EXPORT_STATUS_SET:
        raise ValueError(f"invalid report export status: {status}")
    return cast(ReportExportStatus, status)


def _json_dumps_object(value: dict[str, Any] | None, *, field_name: str) -> str:
    if value is None:
        return "{}"
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return json.dumps(value)


def _json_loads_object(raw: str | None, *, field_name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _row_to_session_record(row: sqlite3.Row) -> ReportSessionRecord:
    return ReportSessionRecord(
        session_id=row["session_id"],
        status=_validate_session_status(row["status"]),
        current_stage=row["current_stage"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_error=row["last_error"],
        metadata=_json_loads_object(row["metadata"], field_name="metadata"),
    )


def _row_to_stage_record(row: sqlite3.Row) -> ReportStageRecord:
    return ReportStageRecord(
        stage_id=row["stage_id"],
        session_id=row["session_id"],
        name=row["name"],
        status=_validate_stage_status(row["status"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        summary=row["summary"],
        error=row["error"],
    )


def _row_to_gate_record(row: sqlite3.Row) -> ReportGateRecord:
    return ReportGateRecord(
        gate_id=row["gate_id"],
        session_id=row["session_id"],
        stage_id=row["stage_id"],
        status=_validate_gate_status(row["status"]),
        question=_json_loads_object(row["question"], field_name="question"),
        answer=_json_loads_object(row["answer"], field_name="answer"),
        created_at=row["created_at"],
        closed_at=row["closed_at"],
    )


def _row_to_artifact_record(row: sqlite3.Row) -> ReportArtifactRecord:
    return ReportArtifactRecord(
        artifact_id=row["artifact_id"],
        session_id=row["session_id"],
        stage_id=row["stage_id"],
        kind=cast(ReportArtifactKind, row["kind"]),
        content=_json_loads_object(row["content"], field_name="content"),
        created_at=row["created_at"],
    )


def _row_to_log_record(row: sqlite3.Row) -> ReportLogRecord:
    return ReportLogRecord(
        log_id=row["log_id"],
        session_id=row["session_id"],
        stage_id=row["stage_id"],
        level=_validate_log_level(row["level"]),
        message=row["message"],
        payload=_json_loads_object(row["payload"], field_name="payload"),
        created_at=row["created_at"],
    )


def _row_to_finding_record(row: sqlite3.Row) -> ReportValidationFindingRecord:
    return ReportValidationFindingRecord(
        finding_id=row["finding_id"],
        session_id=row["session_id"],
        severity=_validate_validation_severity(row["severity"]),
        code=row["code"],
        message=row["message"],
        payload=_json_loads_object(row["payload"], field_name="payload"),
        created_at=row["created_at"],
    )


def _row_to_export_record(row: sqlite3.Row) -> ReportExportRecord:
    return ReportExportRecord(
        export_id=row["export_id"],
        session_id=row["session_id"],
        status=_validate_export_status(row["status"]),
        format=row["format"],
        output_path=row["output_path"],
        diagnostics=_json_loads_object(row["diagnostics"], field_name="diagnostics"),
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )
