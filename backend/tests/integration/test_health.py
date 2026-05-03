"""/health and /ready endpoint contracts."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestHealth:
    def test_health_returns_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestReady:
    def test_ready_with_healthy_fakes(self, client: TestClient) -> None:
        r = client.get("/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["kb"] is True
        assert body["checkpointer"] is True

    def test_ready_reports_degraded_when_kb_unhealthy(self, client: TestClient, fake_kb) -> None:
        fake_kb.set_healthy(False)
        r = client.get("/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert body["kb"] is False
