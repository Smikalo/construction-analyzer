"""/api/threads CRUD-ish surface."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


class TestThreadsCreate:
    def test_create_returns_uuid(self, client: TestClient) -> None:
        r = client.post("/api/threads")
        assert r.status_code == 201
        body = r.json()
        assert "thread_id" in body
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            body["thread_id"],
        )


class TestThreadsList:
    def test_empty_at_startup(self, client: TestClient) -> None:
        r = client.get("/api/threads")
        assert r.status_code == 200
        assert r.json() == []

    def test_lists_threads_after_chat(self, client: TestClient) -> None:
        client.post(
            "/api/chat/sync", json={"message": "hello", "thread_id": "alpha"}
        )
        client.post(
            "/api/chat/sync", json={"message": "world", "thread_id": "beta"}
        )

        r = client.get("/api/threads")
        assert r.status_code == 200
        ids = sorted(t["thread_id"] for t in r.json())
        assert ids == ["alpha", "beta"]
        for t in r.json():
            assert t["message_count"] >= 2


class TestThreadHistory:
    def test_unknown_thread_returns_empty_history(self, client: TestClient) -> None:
        r = client.get("/api/threads/nonexistent/history")
        assert r.status_code == 200
        body = r.json()
        assert body == {"thread_id": "nonexistent", "messages": []}
