"""Deterministic report pipeline state machine and per-session event queues."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.kb.base import KnowledgeBase
from app.schemas import ChatChunk, ReportCardPayload, ReportGatePayload
from app.services import report_drafter, report_exporter, report_retriever
from app.services.document_registry import DocumentRegistry
from app.services.report_planner import (
    build_general_project_dossier_section_plan,
    build_source_inventory,
)
from app.services.report_projection import build_report_projection
from app.services.report_sessions import (
    ReportGateRecord,
    ReportSessionRecord,
    ReportSessionStore,
)
from app.services.report_validator import validate_report_projection

BOOTSTRAP_STAGE_NAME = "bootstrap"
INVENTORY_SOURCES_STAGE_NAME = "inventory_sources"
PLAN_REPORT_SECTIONS_STAGE_NAME = "plan_report_sections"
RETRIEVE_SECTION_EVIDENCE_STAGE_NAME = "retrieve_section_evidence"
DRAFT_REPORT_SECTIONS_STAGE_NAME = "draft_report_sections"
VALIDATE_REPORT_STAGE_NAME = "validate_report"
EXPORT_REPORT_STAGE_NAME = "export_report"
REPORT_TEMPLATE_CONFIRMATION_GATE_ID = "report_template_confirmation"
REPORT_VALIDATION_EXPORT_GATE_ID = "report_validation_export_confirmation"
_ALLOWED_BOOTSTRAP_GATE_CHOICES = {"general_project_dossier", "cancel"}
_ALLOWED_VALIDATION_GATE_CHOICES = {"proceed_with_blockers", "do_not_export", "cancel"}
_REPORT_PROJECTION_ARTIFACT_KINDS = {
    "source_inventory_snapshot",
    "section_plan",
    "paragraph_citations",
    "other",
}
_VALIDATION_SEVERITIES = {"info", "warning", "blocker"}
_MAX_LOG_PAYLOAD_CODES = 20
_MAX_ERROR_CHARS = 240


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
        kb: KnowledgeBase,
        llm_factory: Callable[[], BaseChatModel],
        registry_pipeline: ReportPipelineRegistry | None = None,
        report_exports_dir: str = "/app/data/exports",
    ) -> None:
        self._store = store
        self._registry_documents = registry
        self._kb = kb
        self._llm_factory = llm_factory
        self._registry = registry_pipeline or ReportPipelineRegistry()
        self._report_exports_dir = report_exports_dir

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
        """Close a report gate and advance the session."""
        normalized_session_id = _normalize_session_id(session_id)
        handle = self._registry.get_or_create(normalized_session_id)
        gate = self._find_gate(normalized_session_id, gate_id)
        if gate is None:
            raise KeyError(gate_id)
        if gate.status != "open":
            raise RuntimeError(f"gate {gate_id} is already closed")

        choice = self._extract_choice(answer)
        if gate.gate_id == REPORT_VALIDATION_EXPORT_GATE_ID:
            return await self._answer_validation_export_gate(
                normalized_session_id,
                answer=answer,
                choice=choice,
                gate=gate,
                handle=handle,
            )
        if gate.gate_id != REPORT_TEMPLATE_CONFIRMATION_GATE_ID:
            raise ValueError(f"unsupported report gate: {gate.gate_id}")
        if choice not in _ALLOWED_BOOTSTRAP_GATE_CHOICES:
            raise ValueError(f"invalid gate choice: {choice}")

        inventory_stage = None
        plan_stage = None
        retrieval_stage = None
        draft_stage = None
        inventory: dict[str, Any] = {}
        manifest_sections: list[dict[str, Any]] = []
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
            retrieval_stage = self._store.start_stage(
                normalized_session_id,
                RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Section evidence retrieval started",
                stage_id=retrieval_stage.stage_id,
                payload={"stage_name": RETRIEVE_SECTION_EVIDENCE_STAGE_NAME},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=retrieval_stage.stage_id,
                stage_name=RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
                kind="stage_started",
                message="Section evidence retrieval started",
            )

            artifacts = self._store.list_artifacts(normalized_session_id)
            section_plan_artifact = next(
                (
                    artifact
                    for artifact in reversed(artifacts)
                    if artifact.kind == "section_plan"
                ),
                None,
            )
            if section_plan_artifact is None:
                raise RuntimeError("section plan artifact not found")

            manifest = await report_retriever.retrieve_section_evidence(
                section_plan_artifact.content,
                kb=self._kb,
            )
            raw_sections = manifest.get("sections")
            if isinstance(raw_sections, list):
                manifest_sections = [
                    section for section in raw_sections if isinstance(section, dict)
                ]
            else:
                manifest_sections = []

            self._store.record_artifact(
                normalized_session_id,
                stage_id=retrieval_stage.stage_id,
                kind="other",
                content={"kind": "retrieval_manifest", **manifest},
            )

            retrieval_sections_summary: list[dict[str, Any]] = []
            for section_entry in manifest_sections:
                section_id = str(section_entry.get("id", "")).strip()
                if not section_id:
                    continue
                total_hit_count = int(section_entry.get("total_hit_count") or 0)
                retrieval_sections_summary.append(
                    {"id": section_id, "total_hit_count": total_hit_count}
                )
                raw_queries = section_entry.get("queries")
                if isinstance(raw_queries, list):
                    for query_entry in raw_queries:
                        if not isinstance(query_entry, dict):
                            continue
                        family = str(query_entry.get("family", "")).strip()
                        if not family:
                            continue
                        hit_count = int(query_entry.get("hit_count") or 0)
                        self._append_log(
                            normalized_session_id,
                            level="info",
                            message=(
                                f"Recalled {hit_count} memories for section {section_id} "
                                f"in family {family}"
                            ),
                            stage_id=retrieval_stage.stage_id,
                            payload={
                                "section_id": section_id,
                                "family": family,
                                "hit_count": hit_count,
                            },
                        )

            self._store.complete_stage(
                retrieval_stage.stage_id,
                summary=(
                    f"Retrieved evidence for {len(retrieval_sections_summary)} sections"
                ),
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Section evidence retrieval completed",
                stage_id=retrieval_stage.stage_id,
                payload={
                    "stage_name": RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
                    "sections": retrieval_sections_summary,
                },
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=retrieval_stage.stage_id,
                stage_name=RETRIEVE_SECTION_EVIDENCE_STAGE_NAME,
                kind="stage_completed",
                message="Section evidence retrieval completed",
            )
        except Exception as exc:  # noqa: BLE001
            failure_stage_id = (
                retrieval_stage.stage_id if retrieval_stage is not None else plan_stage.stage_id
            )
            failure_stage_name = (
                RETRIEVE_SECTION_EVIDENCE_STAGE_NAME
                if retrieval_stage is not None
                else PLAN_REPORT_SECTIONS_STAGE_NAME
            )
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=failure_stage_id,
                stage_name=failure_stage_name,
                should_fail_stage=retrieval_stage is not None,
            )
            raise

        try:
            draft_stage = self._store.start_stage(
                normalized_session_id,
                DRAFT_REPORT_SECTIONS_STAGE_NAME,
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Report section drafting started",
                stage_id=draft_stage.stage_id,
                payload={"stage_name": DRAFT_REPORT_SECTIONS_STAGE_NAME},
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=draft_stage.stage_id,
                stage_name=DRAFT_REPORT_SECTIONS_STAGE_NAME,
                kind="stage_started",
                message="Report section drafting started",
            )

            llm = self._llm_factory()
            drafted_sections_summary: list[dict[str, Any]] = []
            for section_entry in manifest_sections:
                section_id = str(section_entry.get("id", "")).strip()
                if not section_id:
                    continue
                total_hit_count = int(section_entry.get("total_hit_count") or 0)
                if total_hit_count == 0:
                    self._store.record_artifact(
                        normalized_session_id,
                        stage_id=draft_stage.stage_id,
                        kind="paragraph_citations",
                        content={
                            "section_id": section_id,
                            "paragraph_index": 0,
                            "text": "",
                            "evidence_manifest": [],
                            "no_evidence": True,
                        },
                    )
                    self._append_log(
                        normalized_session_id,
                        level="warning",
                        message=f"Section {section_id} drafted with no evidence",
                        stage_id=draft_stage.stage_id,
                        payload={
                            "section_id": section_id,
                            "paragraph_count": 0,
                            "no_evidence": True,
                            "total_hit_count": total_hit_count,
                        },
                    )
                    drafted_sections_summary.append(
                        {
                            "id": section_id,
                            "paragraph_count": 0,
                            "no_evidence": True,
                        }
                    )
                    continue

                self._append_log(
                    normalized_session_id,
                    level="info",
                    message=f"Drafting section {section_id}",
                    stage_id=draft_stage.stage_id,
                    payload={
                        "section_id": section_id,
                        "total_hit_count": total_hit_count,
                    },
                )
                try:
                    paragraphs = await report_drafter.draft_section(
                        section_entry,
                        llm=llm,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._append_log(
                        normalized_session_id,
                        level="error",
                        message=f"Section drafting failed: {exc}",
                        stage_id=draft_stage.stage_id,
                        payload={
                            "section_id": section_id,
                            "error": str(exc),
                        },
                    )
                    raise

                for paragraph in paragraphs:
                    self._store.record_artifact(
                        normalized_session_id,
                        stage_id=draft_stage.stage_id,
                        kind="paragraph_citations",
                        content={
                            "section_id": paragraph["section_id"],
                            "paragraph_index": paragraph["paragraph_index"],
                            "text": paragraph["text"],
                            "evidence_manifest": paragraph["evidence_manifest"],
                            "no_evidence": False,
                        },
                    )
                self._append_log(
                    normalized_session_id,
                    level="info",
                    message=(
                        f"Section {section_id} drafted with {len(paragraphs)} paragraphs"
                    ),
                    stage_id=draft_stage.stage_id,
                    payload={
                        "section_id": section_id,
                        "paragraph_count": len(paragraphs),
                        "total_hit_count": total_hit_count,
                    },
                )
                drafted_sections_summary.append(
                    {
                        "id": section_id,
                        "paragraph_count": len(paragraphs),
                        "no_evidence": False,
                    }
                )

            self._store.complete_stage(
                draft_stage.stage_id,
                summary=(
                    f"Drafted evidence for {len(drafted_sections_summary)} sections"
                ),
            )
            self._append_log(
                normalized_session_id,
                level="info",
                message="Report section drafting completed",
                stage_id=draft_stage.stage_id,
                payload={
                    "stage_name": DRAFT_REPORT_SECTIONS_STAGE_NAME,
                    "sections": drafted_sections_summary,
                },
            )
            self._emit_card(
                handle.queue,
                session_id=normalized_session_id,
                stage_id=draft_stage.stage_id,
                stage_name=DRAFT_REPORT_SECTIONS_STAGE_NAME,
                kind="stage_completed",
                message="Report section drafting completed",
            )
        except Exception as exc:  # noqa: BLE001
            failure_stage_id = (
                draft_stage.stage_id if draft_stage is not None else retrieval_stage.stage_id
            )
            failure_stage_name = (
                DRAFT_REPORT_SECTIONS_STAGE_NAME
                if draft_stage is not None
                else RETRIEVE_SECTION_EVIDENCE_STAGE_NAME
            )
            self._record_failure(
                session_id=normalized_session_id,
                handle=handle,
                exc=exc,
                stage_id=failure_stage_id,
                stage_name=failure_stage_name,
                should_fail_stage=draft_stage is not None,
            )
            raise

        return await self._run_validation_stage(normalized_session_id, handle=handle)

    async def _answer_validation_export_gate(
        self,
        session_id: str,
        *,
        answer: dict[str, Any],
        choice: str,
        gate: ReportGateRecord,
        handle: ReportPipelineHandle,
    ) -> ReportSessionRecord:
        if choice not in _ALLOWED_VALIDATION_GATE_CHOICES:
            raise ValueError(f"invalid gate choice: {choice}")

        try:
            closed_gate = self._store.close_gate(gate.gate_id, answer=answer)
            self._append_log(
                session_id,
                level="info",
                message="Report validation export gate closed",
                stage_id=closed_gate.stage_id,
                payload={"gate_id": closed_gate.gate_id, "choice": choice},
            )
            self._emit_card(
                handle.queue,
                session_id=session_id,
                stage_id=closed_gate.stage_id or session_id,
                stage_name=VALIDATE_REPORT_STAGE_NAME,
                kind="gate_closed",
                message="Validation export gate closed",
                payload={"gate_id": closed_gate.gate_id, "choice": choice},
            )
        except Exception as exc:  # noqa: BLE001
            self._record_failure(
                session_id=session_id,
                handle=handle,
                exc=exc,
                stage_id=gate.stage_id,
                stage_name=VALIDATE_REPORT_STAGE_NAME,
                should_fail_stage=False,
            )
            raise

        if choice == "proceed_with_blockers":
            return await self._run_export_stage(
                session_id,
                handle=handle,
                validation_findings=self._stored_validation_findings(session_id),
                blockers_overridden=True,
                validation_gate_id=gate.gate_id,
            )

        session = self._store.update_session_status(
            session_id,
            "complete",
            current_stage=VALIDATE_REPORT_STAGE_NAME,
        )
        self._append_log(
            session_id,
            level="warning",
            message="Report export skipped after validation blockers",
            stage_id=closed_gate.stage_id,
            payload={"gate_id": closed_gate.gate_id, "choice": choice},
        )
        return session

    async def _run_validation_stage(
        self,
        session_id: str,
        *,
        handle: ReportPipelineHandle,
    ) -> ReportSessionRecord:
        validation_stage = None
        export_started = False
        try:
            validation_stage = self._store.start_stage(session_id, VALIDATE_REPORT_STAGE_NAME)
            self._store.update_session_status(
                session_id,
                "active",
                current_stage=VALIDATE_REPORT_STAGE_NAME,
            )
            self._append_log(
                session_id,
                level="info",
                message="Report validation stage started",
                stage_id=validation_stage.stage_id,
                payload={"stage_name": VALIDATE_REPORT_STAGE_NAME},
            )
            self._emit_card(
                handle.queue,
                session_id=session_id,
                stage_id=validation_stage.stage_id,
                stage_name=VALIDATE_REPORT_STAGE_NAME,
                kind="stage_started",
                message="Report validation stage started",
            )

            projection = build_report_projection(self._projection_artifacts(session_id))
            findings = [
                _normalize_validation_finding(finding)
                for finding in validate_report_projection(projection)
            ]
            for finding in findings:
                self._store.record_validation_finding(
                    session_id,
                    severity=str(finding["severity"]),
                    code=finding["code"],
                    message=str(finding["message"]),
                    payload=finding["payload"],
                )

            finding_counts = _validation_finding_counts(findings)
            self._store.record_artifact(
                session_id,
                stage_id=validation_stage.stage_id,
                kind="validation_finding",
                content={
                    "kind": "validation_summary",
                    "finding_counts": finding_counts,
                    "blocker_codes": _finding_codes(findings, severity="blocker"),
                },
            )
            self._store.complete_stage(
                validation_stage.stage_id,
                summary=(
                    f"Validated report with {finding_counts['total']} findings, "
                    f"{finding_counts['blocker']} blockers"
                ),
            )
            self._append_log(
                session_id,
                level="info",
                message="Report validation stage completed",
                stage_id=validation_stage.stage_id,
                payload={
                    "stage_name": VALIDATE_REPORT_STAGE_NAME,
                    "finding_counts": finding_counts,
                },
            )
            self._emit_card(
                handle.queue,
                session_id=session_id,
                stage_id=validation_stage.stage_id,
                stage_name=VALIDATE_REPORT_STAGE_NAME,
                kind="stage_completed",
                message="Report validation stage completed",
                payload={"finding_counts": finding_counts},
            )

            if finding_counts["blocker"] > 0:
                gate = self._store.open_gate(
                    session_id,
                    stage_id=validation_stage.stage_id,
                    gate_id=REPORT_VALIDATION_EXPORT_GATE_ID,
                    question=_validation_export_gate_question(findings, finding_counts),
                )
                self._append_log(
                    session_id,
                    level="warning",
                    message="Report validation blockers gate opened",
                    stage_id=validation_stage.stage_id,
                    payload={
                        "gate_id": gate.gate_id,
                        "finding_counts": finding_counts,
                        "blocker_codes": _finding_codes(findings, severity="blocker"),
                    },
                )
                self._emit_gate_opened(handle.queue, gate)
                return self._store.update_session_status(
                    session_id,
                    "blocked",
                    current_stage=VALIDATE_REPORT_STAGE_NAME,
                )

            export_started = True
            return await self._run_export_stage(
                session_id,
                handle=handle,
                projection=projection,
                validation_findings=findings,
                blockers_overridden=False,
                validation_gate_id=None,
            )
        except Exception as exc:  # noqa: BLE001
            if export_started:
                raise
            self._record_failure(
                session_id=session_id,
                handle=handle,
                exc=exc,
                stage_id=validation_stage.stage_id if validation_stage is not None else None,
                stage_name=VALIDATE_REPORT_STAGE_NAME,
                should_fail_stage=validation_stage is not None,
            )
            raise

    async def _run_export_stage(
        self,
        session_id: str,
        *,
        handle: ReportPipelineHandle,
        validation_findings: Sequence[Mapping[str, Any]],
        blockers_overridden: bool,
        validation_gate_id: str | None,
        projection: Any | None = None,
    ) -> ReportSessionRecord:
        export_stage = None
        export_record = None
        try:
            export_stage = self._store.start_stage(session_id, EXPORT_REPORT_STAGE_NAME)
            self._store.update_session_status(
                session_id,
                "active",
                current_stage=EXPORT_REPORT_STAGE_NAME,
            )
            self._append_log(
                session_id,
                level="info",
                message="Report export stage started",
                stage_id=export_stage.stage_id,
                payload={
                    "stage_name": EXPORT_REPORT_STAGE_NAME,
                    "format": "pdf",
                    "blockers_overridden": blockers_overridden,
                },
            )
            self._emit_card(
                handle.queue,
                session_id=session_id,
                stage_id=export_stage.stage_id,
                stage_name=EXPORT_REPORT_STAGE_NAME,
                kind="stage_started",
                message="Report export stage started",
                payload={"format": "pdf", "blockers_overridden": blockers_overridden},
            )

            active_projection = projection or build_report_projection(
                self._projection_artifacts(session_id)
            )
            finding_counts = _validation_finding_counts(validation_findings)
            export_record = self._store.create_export(
                session_id,
                format="pdf",
                status="pending",
                diagnostics=_export_pending_diagnostics(
                    finding_counts,
                    blockers_overridden=blockers_overridden,
                    validation_gate_id=validation_gate_id,
                ),
            )
            result = report_exporter.export_report_pdf(
                active_projection,
                output_dir=self._report_exports_dir,
                session_id=session_id,
                validation_findings=validation_findings,
            )
            diagnostics = _export_ready_diagnostics(
                result.diagnostics,
                blockers_overridden=blockers_overridden,
                validation_gate_id=validation_gate_id,
            )
            ready_export = self._store.update_export(
                export_record.export_id,
                status="ready",
                output_path=str(result.output_path),
                diagnostics=diagnostics,
            )
            self._store.record_artifact(
                session_id,
                stage_id=export_stage.stage_id,
                kind="pdf_export",
                content={
                    "kind": "pdf_export",
                    "export_id": ready_export.export_id,
                    "status": ready_export.status,
                    "format": ready_export.format,
                    "output_filename": diagnostics.get("output_filename"),
                    "diagnostics": diagnostics,
                },
            )
            self._store.complete_stage(
                export_stage.stage_id,
                summary=f"PDF export ready ({diagnostics.get('byte_size', 0)} bytes)",
            )
            export_payload = _export_log_payload(ready_export.export_id, diagnostics)
            self._append_log(
                session_id,
                level="info",
                message="Report PDF export ready",
                stage_id=export_stage.stage_id,
                payload=export_payload,
            )
            self._emit_card(
                handle.queue,
                session_id=session_id,
                stage_id=export_stage.stage_id,
                stage_name=EXPORT_REPORT_STAGE_NAME,
                kind="stage_completed",
                message="Report PDF export ready",
                payload=export_payload,
            )
            return self._store.update_session_status(
                session_id,
                "complete",
                current_stage=EXPORT_REPORT_STAGE_NAME,
            )
        except Exception as exc:  # noqa: BLE001
            safe_error = _safe_export_error_message(exc)
            if export_record is not None:
                try:
                    self._store.update_export(
                        export_record.export_id,
                        status="failed",
                        output_path=None,
                        diagnostics=_export_failure_diagnostics(
                            safe_error,
                            validation_findings,
                            blockers_overridden=blockers_overridden,
                            validation_gate_id=validation_gate_id,
                        ),
                    )
                except Exception:  # noqa: BLE001, S110
                    pass
            self._record_failure(
                session_id=session_id,
                handle=handle,
                exc=RuntimeError(safe_error),
                stage_id=export_stage.stage_id if export_stage is not None else None,
                stage_name=EXPORT_REPORT_STAGE_NAME,
                should_fail_stage=export_stage is not None,
            )
            raise

    def _projection_artifacts(self, session_id: str) -> list[Any]:
        return [
            artifact
            for artifact in self._store.list_artifacts(session_id)
            if artifact.kind in _REPORT_PROJECTION_ARTIFACT_KINDS
        ]

    def _stored_validation_findings(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {
                "severity": finding.severity,
                "code": finding.code,
                "message": finding.message,
                "payload": finding.payload,
            }
            for finding in self._store.list_validation_findings(session_id)
        ]

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


def _validation_export_gate_question(
    findings: Sequence[Mapping[str, Any]],
    finding_counts: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "gate_id": REPORT_VALIDATION_EXPORT_GATE_ID,
        "prompt": "Report validation found blocker findings. Proceed with PDF export?",
        "finding_counts": dict(finding_counts),
        "blocker_codes": _finding_codes(findings, severity="blocker"),
        "options": [
            {
                "id": "proceed_with_blockers",
                "label": "Proceed with blockers",
            },
            {
                "id": "do_not_export",
                "label": "Do not export PDF",
            },
        ],
    }


def _normalize_validation_finding(finding: Mapping[str, Any]) -> dict[str, Any]:
    severity = str(finding.get("severity", "warning")).strip().lower()
    if severity not in _VALIDATION_SEVERITIES:
        severity = "warning"
    code = _bounded_text(finding.get("code"), 120) or None
    message = _bounded_text(finding.get("message"), 180) or "Report validation finding."
    payload = finding.get("payload")
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "payload": dict(payload) if isinstance(payload, Mapping) else {},
    }


def _validation_finding_counts(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "total": len(findings),
        "info": 0,
        "warning": 0,
        "blocker": 0,
        "codes": {},
    }
    codes: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity", "")).strip().lower()
        if severity in _VALIDATION_SEVERITIES:
            counts[severity] += 1
        code = _bounded_text(finding.get("code"), 120)
        if code:
            codes[code] = codes.get(code, 0) + 1
    counts["codes"] = dict(list(sorted(codes.items()))[:_MAX_LOG_PAYLOAD_CODES])
    return counts


def _finding_codes(
    findings: Sequence[Mapping[str, Any]],
    *,
    severity: str | None = None,
) -> list[str]:
    codes: list[str] = []
    for finding in findings:
        finding_severity = str(finding.get("severity", "")).strip().lower()
        if severity is not None and finding_severity != severity:
            continue
        code = _bounded_text(finding.get("code"), 120)
        if code and code not in codes:
            codes.append(code)
        if len(codes) == _MAX_LOG_PAYLOAD_CODES:
            break
    return codes


def _export_pending_diagnostics(
    finding_counts: Mapping[str, Any],
    *,
    blockers_overridden: bool,
    validation_gate_id: str | None,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "format": "pdf",
        "status": "pending",
        "validation_finding_count": finding_counts.get("total", 0),
        "validation_blocker_count": finding_counts.get("blocker", 0),
        "blockers_overridden": blockers_overridden,
    }
    if validation_gate_id is not None:
        diagnostics["validation_gate_id"] = validation_gate_id
    return diagnostics


def _export_ready_diagnostics(
    diagnostics: Mapping[str, Any],
    *,
    blockers_overridden: bool,
    validation_gate_id: str | None,
) -> dict[str, Any]:
    bounded = dict(diagnostics)
    bounded["blockers_overridden"] = blockers_overridden
    if validation_gate_id is not None:
        bounded["validation_gate_id"] = validation_gate_id
    return bounded


def _export_failure_diagnostics(
    error: str,
    validation_findings: Sequence[Mapping[str, Any]],
    *,
    blockers_overridden: bool,
    validation_gate_id: str | None,
) -> dict[str, Any]:
    finding_counts = _validation_finding_counts(validation_findings)
    diagnostics = _export_pending_diagnostics(
        finding_counts,
        blockers_overridden=blockers_overridden,
        validation_gate_id=validation_gate_id,
    )
    diagnostics.update({"status": "failed", "error": error})
    return diagnostics


def _export_log_payload(export_id: str, diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "format",
        "output_filename",
        "byte_size",
        "page_count",
        "section_count",
        "paragraph_count",
        "source_count",
        "citation_count",
        "validation_finding_count",
        "validation_blocker_count",
        "blockers_overridden",
        "validation_gate_id",
    )
    payload = {key: diagnostics[key] for key in keys if key in diagnostics}
    payload["export_id"] = export_id
    return payload


def _safe_export_error_message(exc: Exception) -> str:
    if isinstance(exc, report_exporter.ReportExportError):
        return _bounded_text(str(exc), _MAX_ERROR_CHARS) or "Report export failed."
    return "Report export failed."


def _bounded_text(value: object, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


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
