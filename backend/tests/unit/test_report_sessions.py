"""Tests for the SQLite-backed report session store."""

from __future__ import annotations

import sqlite3

import pytest

from app.services.report_sessions import lifespan_report_sessions


class TestReportSessionStore:
    async def test_create_session_uses_pending_defaults_and_empty_metadata(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            record = store.create_session(session_id="session-1")

            assert record.session_id == "session-1"
            assert record.status == "pending"
            assert record.current_stage is None
            assert record.last_error is None
            assert record.metadata == {}
            assert record.created_at
            assert record.updated_at == record.created_at
            assert store.get_session("session-1") == record

    async def test_update_session_status_validates_and_persists_transition_fields(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")

            with pytest.raises(ValueError, match="invalid report session status"):
                store.update_session_status("session-1", "bogus")

            updated = store.update_session_status(
                "session-1",
                "active",
                current_stage="drafting",
                last_error="recoverable problem",
                updated_at="2026-05-03T00:10:00+00:00",
            )

            assert updated.status == "active"
            assert updated.current_stage == "drafting"
            assert updated.last_error == "recoverable problem"
            assert updated.updated_at == "2026-05-03T00:10:00+00:00"
            assert store.get_session("session-1") == updated

    async def test_stage_round_trip_and_listing_is_ordered_by_started_at(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")

            later = store.start_stage(
                "session-1",
                "later-stage",
                started_at="2026-05-03T00:10:00+00:00",
            )
            earlier = store.start_stage(
                "session-1",
                "earlier-stage",
                started_at="2026-05-03T00:05:00+00:00",
            )

            completed = store.complete_stage(
                later.stage_id,
                summary="Later stage completed",
                completed_at="2026-05-03T00:11:00+00:00",
            )
            failed = store.fail_stage(
                earlier.stage_id,
                error="Earlier stage failed",
                completed_at="2026-05-03T00:06:00+00:00",
            )

            assert completed.status == "complete"
            assert completed.summary == "Later stage completed"
            assert completed.completed_at == "2026-05-03T00:11:00+00:00"
            assert completed.error is None
            assert failed.status == "failed"
            assert failed.error == "Earlier stage failed"
            assert failed.completed_at == "2026-05-03T00:06:00+00:00"

            stages = store.list_stages("session-1")
            assert [stage.stage_id for stage in stages] == [earlier.stage_id, later.stage_id]
            assert stages[0] == failed
            assert stages[1] == completed

    async def test_gate_round_trip_keeps_json_payloads_and_open_closed_states(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")
            stage = store.start_stage(
                "session-1",
                "drafting",
                started_at="2026-05-03T00:10:00+00:00",
            )

            open_gate = store.open_gate(
                "session-1",
                stage_id=stage.stage_id,
                question={"prompt": "Proceed with export?", "context": ["draft"]},
                gate_id="gate-open",
                created_at="2026-05-03T00:11:00+00:00",
            )
            closed_gate = store.open_gate(
                "session-1",
                stage_id=stage.stage_id,
                question={"prompt": "Need approval?"},
                gate_id="gate-closed",
                created_at="2026-05-03T00:12:00+00:00",
            )
            closed_gate = store.close_gate(
                closed_gate.gate_id,
                answer={"decision": "approved", "by": "reviewer-1"},
                closed_at="2026-05-03T00:13:00+00:00",
            )

            assert open_gate.status == "open"
            assert open_gate.question == {"prompt": "Proceed with export?", "context": ["draft"]}
            assert open_gate.answer == {}
            assert closed_gate.status == "closed"
            assert closed_gate.answer == {"decision": "approved", "by": "reviewer-1"}
            assert closed_gate.closed_at == "2026-05-03T00:13:00+00:00"

            gates = store.list_gates("session-1")
            assert [gate.gate_id for gate in gates] == [open_gate.gate_id, closed_gate.gate_id]
            assert gates[0].status == "open"
            assert gates[1].status == "closed"

    async def test_artifact_round_trip_and_listing_is_ordered_by_created_at(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")
            stage = store.start_stage("session-1", "drafting")

            later = store.record_artifact(
                "session-1",
                stage_id=stage.stage_id,
                kind="section_plan",
                content={"sections": ["later"]},
                created_at="2026-05-03T00:10:00+00:00",
            )
            earlier = store.record_artifact(
                "session-1",
                stage_id=stage.stage_id,
                kind="paragraph_citations",
                content={"sections": ["earlier"]},
                created_at="2026-05-03T00:05:00+00:00",
            )

            artifacts = store.list_artifacts("session-1")
            assert [artifact.artifact_id for artifact in artifacts] == [
                earlier.artifact_id,
                later.artifact_id,
            ]
            assert artifacts[0].content == {"sections": ["earlier"]}
            assert artifacts[1].kind == "section_plan"

    async def test_logs_round_trip_payloads_and_validate_level(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")
            stage = store.start_stage("session-1", "drafting")

            later = store.append_log(
                "session-1",
                stage_id=stage.stage_id,
                level="info",
                message="Stage started for report session",
                payload={"source": "store", "redacted": True},
                created_at="2026-05-03T00:10:00+00:00",
            )
            earlier = store.append_log(
                "session-1",
                stage_id=stage.stage_id,
                level="warning",
                message="Another redaction-friendly message",
                payload={"source": "store", "redacted": False},
                created_at="2026-05-03T00:05:00+00:00",
            )

            with pytest.raises(ValueError, match="invalid report log level"):
                store.append_log(
                    "session-1",
                    stage_id=stage.stage_id,
                    level="verbose",
                    message="bad",
                )

            logs = store.list_logs("session-1")
            assert [log.log_id for log in logs] == [earlier.log_id, later.log_id]
            assert logs[0].payload == {"source": "store", "redacted": False}
            assert logs[1].message == "Stage started for report session"

    async def test_validation_findings_accept_known_severities_and_reject_unknown(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")

            findings = [
                store.record_validation_finding(
                    "session-1",
                    severity=severity,
                    code=f"CODE-{severity}",
                    message=f"{severity} finding",
                    payload={"severity": severity},
                    created_at=f"2026-05-03T00:0{index}:00+00:00",
                )
                for index, severity in enumerate(("info", "warning", "blocker"), start=1)
            ]

            with pytest.raises(ValueError, match="invalid report validation severity"):
                store.record_validation_finding(
                    "session-1",
                    severity="critical",
                    code="CODE-bad",
                    message="bad",
                )

            listed = store.list_validation_findings("session-1")
            assert [finding.severity for finding in listed] == ["info", "warning", "blocker"]
            assert {finding.code for finding in listed} == {finding.code for finding in findings}
            assert listed[0].payload == {"severity": "info"}

    async def test_export_round_trip_and_invalid_status_validation(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")

            export = store.create_export(
                "session-1",
                format="pdf",
                created_at="2026-05-03T00:10:00+00:00",
            )
            ready = store.update_export(
                export.export_id,
                status="ready",
                output_path="reports/final.pdf",
                diagnostics={"pages": 12},
                completed_at="2026-05-03T00:20:00+00:00",
            )

            with pytest.raises(ValueError, match="invalid report export status"):
                store.update_export(export.export_id, status="bogus")

            assert export.status == "pending"
            assert ready.status == "ready"
            assert ready.output_path == "reports/final.pdf"
            assert ready.diagnostics == {"pages": 12}
            assert ready.completed_at == "2026-05-03T00:20:00+00:00"
            assert store.list_exports("session-1") == [ready]

    async def test_lifespan_closes_the_connection(self) -> None:
        async with lifespan_report_sessions(":memory:") as store:
            store.create_session(session_id="session-1")

        with pytest.raises(sqlite3.ProgrammingError):
            store.get_session("session-1")
