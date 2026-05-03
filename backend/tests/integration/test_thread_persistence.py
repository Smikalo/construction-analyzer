"""Two requests on the same thread_id must see each other's history.

This is the property that lets the frontend hydrate prior turns after a page
reload (and, in production with a file-backed checkpointer, after a backend
restart).
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.checkpointer import lifespan_checkpointer
from app.agent.graph import build_graph
from app.kb.fake import FakeKB
from app.main import build_app, build_app_state
from app.services.document_registry import lifespan_document_registry
from app.services.report_sessions import lifespan_report_sessions
from tests._fakes import scripted_chat


@pytest.fixture
async def shared_client_and_state():
    kb = FakeKB()
    llm = scripted_chat(
        [
            AIMessage(content="first reply"),
            AIMessage(content="second reply"),
            AIMessage(content="third reply"),
        ]
    )
    stack = AsyncExitStack()
    checkpointer = await stack.enter_async_context(lifespan_checkpointer(":memory:"))
    registry = await stack.enter_async_context(lifespan_document_registry(":memory:"))
    report_sessions = await stack.enter_async_context(lifespan_report_sessions(":memory:"))
    graph = build_graph(llm=llm, kb=kb, checkpointer=checkpointer)
    state = build_app_state(
        llm=llm,
        kb=kb,
        checkpointer=checkpointer,
        registry=registry,
        report_sessions=report_sessions,
        graph=graph,
    )
    app = build_app(state=state)
    try:
        with TestClient(app) as c:
            yield c, graph
    finally:
        await stack.aclose()


class TestThreadPersistence:
    async def test_history_grows_across_two_sync_calls(self, shared_client_and_state) -> None:
        client, _ = shared_client_and_state

        r1 = client.post("/api/chat/sync", json={"message": "hello", "thread_id": "stable"})
        assert r1.status_code == 200

        r2 = client.post("/api/chat/sync", json={"message": "again", "thread_id": "stable"})
        assert r2.status_code == 200

        history = client.get("/api/threads/stable/history").json()
        roles = [m["role"] for m in history["messages"]]
        contents = [m["content"] for m in history["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert contents == ["hello", "first reply", "again", "second reply"]

    async def test_independent_threads_do_not_leak(self, shared_client_and_state) -> None:
        client, _ = shared_client_and_state

        client.post("/api/chat/sync", json={"message": "msg-a", "thread_id": "ta"})
        client.post("/api/chat/sync", json={"message": "msg-b", "thread_id": "tb"})

        ha = client.get("/api/threads/ta/history").json()
        hb = client.get("/api/threads/tb/history").json()

        assert [m["content"] for m in ha["messages"]] == ["msg-a", "first reply"]
        assert [m["content"] for m in hb["messages"]] == ["msg-b", "second reply"]
