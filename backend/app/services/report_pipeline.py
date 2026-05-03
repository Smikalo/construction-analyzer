"""Deterministic report pipeline state machine and per-session event queues."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.schemas import ChatChunk, ReportCardPayload, ReportGatePayload
from app.services.document_registry import DocumentRegistry
from app.services.report_planner import (
    build_general_project_dossier_section_plan,
    build_source_inventory,
)
from app.services.report_sessions import ReportGateRecord, ReportSessionRecord, ReportSessionStore

BOOTSTRAP_STAGE_NAME = "bootstrap"
INVENTORY_SOURCES_STAGE_NAME = "inventory_sources"
PLAN_REPORT_SECTIONS_STAGE_NAME = "plan_report_sections"
REPORT_TEMPLATE_CONFIRMATION_GATE_ID = "report_template_confirmation"
_ALLOWED_GATE_CHOICES = {"general_project_dossier", "cancel"}


@dataclass(slots=True)
class ReportPipelineHandle:
    """Durable per-session queue used by the SSE stream."""

    session_id: str
    queue: asyncio.Queue[ChatChunk] = field(default_factory=asyncio.Queue)


class ReportPipelineRegistry:
    """Keep one queue handle per report session."""

    def __init__(self) -> None:
        self._handles: dict[str, ReportPipelineHandle] = {}

    def get_or_create(self, session_id: str) -> ReportPipelineHandle:
        normalized_session_id = _normalize_session_id(session_id)
        handle = self._handles.get(normalized_session_id)
        if handle is None:
            handle = ReportPipelineHandle(session_id=normalized_session_id)
            self._handles[normalized_session_id] = handle
        return handle

    def events(self, session_id: str) -> asyncio.Queue[ChatChunk]:
        return self.get_or_create(session_id).queue


class ReportPipeline:
    """Drive report sessions through a deterministic staged workflow."""

    def __init__(
        self,
        store: ReportSessionStore,
        registry: DocumentRegistry,
        registry_pipeline: ReportPipelineRegistry | None = None,
    ) -> None:
        self._store = store
        self._registry_documents = registry
        self._registry = registry_pipeline or ReportPipelineRegistry()

    def events(self, session_id: str) -> asyncio.Queue[ChatChunk]:
        return self._registry.events(session_id)

    async def start(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ReportSessionRecord:
        """Start a new report session or replay an open gate for a blocked one."""
        normalized_session_id = _normalize_session_id(session_id)
        handle = self._registry.get_or_create(normalized_session_id)
        session = self._store.get_session(normalized_session_id)
        if session is None:
            session = self._store.create_session(
                session_id=normalized_session_id,
                metadata=metadata,
            )

        open_gate = self._find_open_gate(normalized_session_id)
        if open_gate is not None and session.status in {"active", "blocked"}:
            self._emit_gate_opened(handle.queue, open_gate)
            return session
        if session.status in {"complete", "failed"}:
            return session

        bootstrap_stage = None
        bootstrap_stage_completed = False
        try:
            bootstrap_stage = self._store.start_stage(normalized_session_id, BOOTSTRAP_STAGE_NAME)
            self._store.update_session_status(
                normalized_session_id,
                "active",
                current_stage=BOOTSTRAP_STAGE_NAME,
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Report bootstrap stage started",
                stage_id=bootstrap_stage.stage_id,
                payload={"stage_name": BOOTSTRAP_STAGE_NAME},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=bootstrap_stage.stage_id,
                stage_name=BOOTSTRAP_STAGE_NAME,
                kind="stage_started",
                message="Bootstrap stage started",
            )

            gate = self._store.open_gate(
                normalized_session_id,
                stage_id=bootstrap_stage.stage_id,
                gate_id=REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
                question=_bootstrap_gate_question(),
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Report template confirmation gate opened",
                stage_id=bootstrap_stage.stage_id,
                payload={"gate_id": gate.gate_id},
            )
            self._emit_gate_opened(handle.queue, gate)

            self._store.complete_stage(
                bootstrap_stage.stage_id,
                summary="Template confirmation gate opened",
            )
            bootstrap_stage_completed = True
            self._append_log(
                normalized_session_id,
                level="info",
                message="Report bootstrap stage completed",
                stage_id=bootstrap_stage.stage_id,
                payload={"gate_id": gate.gate_id},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=bootstrap_stage.stage_id,
                stage_name=BOOTSTRAP_STAGE_NAME,
                kind="stage_completed",
                message="Bootstrap stage completed",
            )

            session = self._store.update_session_status(
                normalized_session_id,
                "blocked",
                current_stage=BOOTSTRAP_STAGE_NAME,
            )
            return session
        except Exception as exc:  # noqa: BLE001
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=bootstrap_stage.stage_id if bootstrap_stage is not None else None,
                stage_name=BOOTSTRAP_STAGE_NAME,
                should_fail_stage=bootstrap_stage is not None and not bootstrap_stage_completed,
            )
            raise

    async def answer_gate(
        self,
        session_id: str,
        answer: dict[str, Any],
        *,
        gate_id: str = REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
    ) -> ReportSessionRecord:
        """Close the bootstrap gate and advance the session."""
        normalized_session_id = _normalize_session_id(session_id)
        handle = self._registry.get_or_create(normalized_session_id)
        gate = self._find_gate(normalized_session_id, gate_id)
        if gate is None:
            raise KeyError(gate_id)
        if gate.status != "open":
            raise RuntimeError(f"gate {gate_id} is already closed")

        choice = self._extract_choice(answer)
        if choice not in _ALLOWED_GATE_CHOICES:
            raise ValueError(f"invalid gate choice: {choice}")

        inventory_stage = None
        plan_stage = None
        inventory: dict[str, Any] = {}
        try:
            closed_gate = self._store.close_gate(gate.gate_id, answer=answer)
            self._append_log(
                normalized_session_id,
                level="info",
                message="Report template confirmation gate closed",
                stage_id=closed_gate.stage_id,
                payload={"gate_id": closed_gate.gate_id, "choice": choice},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=closed_gate.stage_id or normalized_session_id,
                stage_name=BOOTSTRAP_STAGE_NAME,
                kind="gate_closed",
                message="Template confirmation gate closed",
                payload={"gate_id": closed_gate.gate_id, "choice": choice},
            )

            if choice == "cancel":
                session = self._store.update_session_status(
                    normalized_session_id,
                    "complete",
                    current_stage=None,
                )
                self._append_log(
                    normalized_session_id,
                    level="info",
                    message="Report session completed",
                    stage_id=closed_gate.stage_id,
                    payload={"gate_id": closed_gate.gate_id, "choice": choice},
                )
                return session
        except Exception as exc:  # noqa: BLE001
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=None,
                stage_name=BOOTSTRAP_STAGE_NAME,
                should_fail_stage=True,
            )
            raise

        try:
            inventory_stage = self._store.start_stage(
                normalized_session_id,
                INVENTORY_SOURCES_STAGE_NAME,
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Inventory sources stage started",
                stage_id=inventory_stage.stage_id,
                payload={"stage_name": INVENTORY_SOURCES_STAGE_NAME},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=inventory_stage.stage_id,
                stage_name=INVENTORY_SOURCES_STAGE_NAME,
                kind="stage_started",
                message="Inventory sources stage started",
            )

            inventory = build_source_inventory(self._registry_documents.list_all())
            totals = inventory["totals"]
            self._store.record_artifact(
                normalized_session_id,
                stage_id=inventory_stage.stage_id,
                kind="source_inventory_snapshot",
                content=inventory,
            )
            inventory_counts = {
                "indexed_count": totals["indexed"],
                "skipped_count": totals["skipped"],
                "failed_count": totals["failed"],
            }
            self._append_log(
                normalized_session_id,
                level="info",
                message="Source inventory snapshot recorded",
                stage_id=inventory_stage.stage_id,
                payload={"stage_name": INVENTORY_SOURCES_STAGE_NAME, **inventory_counts},
            )
            self._store.complete_stage(
                inventory_stage.stage_id,
                summary=(
                    f"Indexed {totals['indexed']}, skipped {totals['skipped']}, "
                    f"failed {totals['failed']}"
                ),
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Inventory sources stage completed",
                stage_id=inventory_stage.stage_id,
                payload={"stage_name": INVENTORY_SOURCES_STAGE_NAME, **inventory_counts},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=inventory_stage.stage_id,
                stage_name=INVENTORY_SOURCES_STAGE_NAME,
                kind="stage_completed",
                message="Inventory sources stage completed",
            )
        except Exception as exc:  # noqa: BLE001
            failure_stage_id = (
                inventory_stage.stage_id if inventory_stage is not None else gate.stage_id
            )
            failure_stage_name = (
                INVENTORY_SOURCES_STAGE_NAME
                if inventory_stage is not None
                else BOOTSTRAP_STAGE_NAME
            )
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=failure_stage_id,
                stage_name=failure_stage_name,
                should_fail_stage=inventory_stage is not None,
            )
            raise

        try:
            plan_stage = self._store.start_stage(
                normalized_session_id,
                PLAN_REPORT_SECTIONS_STAGE_NAME,
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Section planning stage started",
                stage_id=plan_stage.stage_id,
                payload={"stage_name": PLAN_REPORT_SECTIONS_STAGE_NAME},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=plan_stage.stage_id,
                stage_name=PLAN_REPORT_SECTIONS_STAGE_NAME,
                kind="stage_started",
                message="Section planning stage started",
            )

            section_plan = build_general_project_dossier_section_plan(inventory)
            sections = section_plan["sections"]
            active_section_count = sum(1 for section in sections if section["active"])
            self._store.record_artifact(
                normalized_session_id,
                stage_id=plan_stage.stage_id,
                kind="section_plan",
                content=section_plan,
            )
            section_counts = {
                "section_count": len(sections),
                "active_section_count": active_section_count,
            }
            self._append_log(
                normalized_session_id,
                level="info",
                message="Section plan recorded",
                stage_id=plan_stage.stage_id,
                payload={"stage_name": PLAN_REPORT_SECTIONS_STAGE_NAME, **section_counts},
            )
            self._store.complete_stage(
                plan_stage.stage_id,
                summary=f"Planned {len(sections)} sections, {active_section_count} active",
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Section planning stage completed",
                stage_id=plan_stage.stage_id,
                payload={"stage_name": PLAN_REPORT_SECTIONS_STAGE_NAME, **section_counts},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=plan_stage.stage_id,
                stage_name=PLAN_REPORT_SECTIONS_STAGE_NAME,
                kind="stage_completed",
                message="Section planning stage completed",
            )
        except Exception as exc:  # noqa: BLE001
            failure_stage_id = (
                plan_stage.stage_id if plan_stage is not None else inventory_stage.stage_id
            )
            failure_stage_name = (
                PLAN_REPORT_SECTIONS_STAGE_NAME
                if plan_stage is not None
                else INVENTORY_SOURCES_STAGE_NAME
            )
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=failure_stage_id,
                stage_name=failure_stage_name,
                should_fail_stage=plan_stage is not None,
            )
            raise

        try:
            session = self._store.update_session_status(
                normalized_session_id,
                "active",
                current_stage=PLAN_REPORT_SECTIONS_STAGE_NAME,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=plan_stage.stage_id,
                stage_name=PLAN_REPORT_SECTIONS_STAGE_NAME,
                should_fail_stage=False,
            )
            raise
        return session

    def _record_failure(
        self,
        *,
        session_id: str,
        handle: ReportPipelineHandle,
        exc: Exception,
        stage_id: str | None,
        stage_name: str,
        should_fail_stage: bool,
    ) -> None:
        error_message = str(exc)
        if should_fail_stage and stage_id is not None:
            try:
                self._store.fail_stage(stage_id, error=error_message)
            except Exception:  # noqa: BLE001, S110
                pass
        try:
            self._store.update_session_status(
                session_id,
                "failed",
                current_stage=stage_name,
                last_error=error_message,
            )
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            self._store.append_log(
                session_id,
                level="error",
                message="Report pipeline failed",
                stage_id=stage_id,
                payload={
                    "error": error_message,
                    "session_id": session_id,
                    "stage_id": stage_id,
                    "stage_name": stage_name,
                },
            )
        except Exception:  # noqa: BLE001, S110
            pass
        self._emit_card(
            handle.queue,
            session_id=session_id,
            stage_id=stage_id or session_id,
            stage_name=stage_name,
            kind="failure",
            message=error_message,
            payload={
                "error": error_message,
                "stage_id": stage_id,
                "stage_name": stage_name,
            },
        )

    def _find_open_gate(self, session_id: str) -> ReportGateRecord | None:
        for gate in self._store.list_gates(session_id):
            if gate.status == "open":
                return gate
        return None

    def _find_gate(self, session_id: str, gate_id: str) -> ReportGateRecord | None:
        normalized_gate_id = _normalize_gate_id(gate_id)
        for gate in self._store.list_gates(session_id):
            if gate.gate_id == normalized_gate_id:
                return gate
        return None

    def _append_log(
        self,
        session_id: str,
        *,
        level: str,
        message: str,
        stage_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._store.append_log(
            session_id,
            level=level,
            message=message,
            stage_id=stage_id,
            payload=payload or {},
        )

    def _emit_card(
        self,
        queue: asyncio.Queue[ChatChunk],
        *,
        session_id: str,
        stage_id: str,
        stage_name: str,
        kind: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        card = ReportCardPayload(
            session_id=session_id,
            stage_id=stage_id,
            stage_name=stage_name,
            kind=kind,  # type: ignore[arg-type]
            message=message,
            created_at=_now_iso(),
            payload=payload or {},
        )
        queue.put_nowait(ChatChunk(type="report_card", data=message, payload=card.model_dump()))

    def _emit_gate_opened(
        self,
        queue: asyncio.Queue[ChatChunk],
        gate: ReportGateRecord,
    ) -> None:
        gate_payload = ReportGatePayload(
            session_id=gate.session_id,
            gate_id=gate.gate_id,
            stage_id=gate.stage_id,
            question=gate.question,
            status=gate.status,
            created_at=gate.created_at,
        )
        prompt = gate.question.get("prompt")
        queue.put_nowait(
            ChatChunk(
                type="report_gate",
                data=prompt if isinstance(prompt, str) and prompt else gate.gate_id,
                payload=gate_payload.model_dump(),
            )
        )

    def _extract_choice(self, answer: dict[str, Any]) -> str:
        if not isinstance(answer, dict):
            raise ValueError("gate answer must be a JSON object")
        choice = answer.get("choice")
        if not isinstance(choice, str) or not choice.strip():
            raise ValueError("gate answer must include a non-empty choice")
        return choice.strip()


def _normalize_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("session_id must not be empty")
    return normalized


def _normalize_gate_id(gate_id: str) -> str:
    normalized = gate_id.strip()
    if not normalized:
        raise ValueError("gate_id must not be empty")
    return normalized


def _bootstrap_gate_question() -> dict[str, Any]:
    return {
        "gate_id": REPORT_TEMPLATE_CONFIRMATION_GATE_ID,
        "prompt": "Confirm the report template for this session.",
        "options": [
            {
                "id": "general_project_dossier",
                "label": "General project dossier",
            },
            {
                "id": "cancel",
                "label": "Cancel",
            },
        ],
    }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
