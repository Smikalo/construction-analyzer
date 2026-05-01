"""Tests for /api/chat (SSE) and /api/chat/sync.

We use scripted LLM responses so the assertions are deterministic. The chat
sync test pins the JSON shape and the SSE test pins the framing on the wire.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.checkpointer import lifespan_checkpointer
from app.agent.graph import build_graph
from app.kb.fake import FakeKB
from app.main import build_app, build_app_state
from app.services.document_registry import lifespan_document_registry
from tests._fakes import scripted_chat


@pytest.fixture
def make_client():
    """Return a factory for fresh TestClients with a custom scripted LLM."""

    async def _build(responses: list[AIMessage]):
        kb = FakeKB()
        llm = scripted_chat(responses)
        stack = AsyncExitStack()
        checkpointer = await stack.enter_async_context(lifespan_checkpointer(":memory:"))
        registry = await stack.enter_async_context(lifespan_document_registry(":memory:"))
        graph = build_graph(llm=llm, kb=kb, checkpointer=checkpointer)
        state = build_app_state(
            llm=llm,
            kb=kb,
            checkpointer=checkpointer,
            registry=registry,
            graph=graph,
        )
        app = build_app(state=state)
        return TestClient(app), stack, kb

    yield _build


class TestChatSync:
    async def test_sync_returns_assistant_message(self, make_client) -> None:
        client, cm, _ = await make_client([AIMessage(content="hello world")])
        try:
            with client:
                r = client.post("/api/chat/sync", json={"message": "hi"})
            assert r.status_code == 200
            body = r.json()
            assert body["message"]["role"] == "assistant"
            assert body["message"]["content"] == "hello world"
            assert isinstance(body["thread_id"], str) and body["thread_id"]
        finally:
            await cm.__aexit__(None, None, None)

    async def test_sync_uses_provided_thread_id(self, make_client) -> None:
        client, cm, _ = await make_client([AIMessage(content="ok")])
        try:
            with client:
                r = client.post(
                    "/api/chat/sync",
                    json={"message": "hi", "thread_id": "fixed-thread"},
                )
            assert r.json()["thread_id"] == "fixed-thread"
        finally:
            await cm.__aexit__(None, None, None)

    async def test_sync_rejects_empty_message(self, make_client) -> None:
        client, cm, _ = await make_client([AIMessage(content="ok")])
        try:
            with client:
                r = client.post("/api/chat/sync", json={"message": ""})
            assert r.status_code == 422
        finally:
            await cm.__aexit__(None, None, None)


class TestChatStream:
    async def test_stream_emits_thread_id_and_done(self, make_client) -> None:
        client, cm, _ = await make_client([AIMessage(content="hello")])
        try:
            with client:
                with client.stream(
                    "POST", "/api/chat", json={"message": "hi"}
                ) as r:
                    assert r.status_code == 200
                    body = "".join(r.iter_text())
            # SSE frames are "event: <name>\ndata: <json>\n\n"
            assert "event: thread" in body
            assert "thread_id" in body
            assert "\"type\":\"done\"" in body
        finally:
            await cm.__aexit__(None, None, None)

    async def test_stream_includes_done_chunk_even_on_error(
        self, make_client
    ) -> None:
        client, cm, _ = await make_client([AIMessage(content="ok")])
        try:
            with client:
                async def boom(*args, **kwargs):
                    raise RuntimeError("nope")
                    yield  # pragma: no cover

                client.app.state.app_state.graph.astream_events = boom  # type: ignore[assignment]
                with client.stream(
                    "POST", "/api/chat", json={"message": "hi"}
                ) as r:
                    body = "".join(r.iter_text())
            assert "\"type\":\"error\"" in body
            assert "\"type\":\"done\"" in body
        finally:
            await cm.__aexit__(None, None, None)


def _parse_sse_events(blob: str) -> list[tuple[str, str]]:
    blob = blob.replace("\r\n", "\n")
    events: list[tuple[str, str]] = []
    for frame in blob.split("\n\n"):
        if not frame.strip():
            continue
        ev = "message"
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                ev = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        events.append((ev, "\n".join(data_lines)))
    return events


class TestChatStreamFraming:
    async def test_first_thread_event_carries_thread_id(self, make_client) -> None:
        client, cm, _ = await make_client([AIMessage(content="hello")])
        try:
            with client:
                with client.stream(
                    "POST",
                    "/api/chat",
                    json={"message": "hi", "thread_id": "abc"},
                ) as r:
                    body = "".join(r.iter_text())
            events = _parse_sse_events(body)
            thread_events = [e for e in events if e[0] == "thread"]
            assert thread_events, f"no thread event in {events!r}"
            assert json.loads(thread_events[0][1]) == {"thread_id": "abc"}
        finally:
            await cm.__aexit__(None, None, None)
