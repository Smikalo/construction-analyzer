"""Shared test fixtures.

Most tests need:
  - a FakeKB instance
  - a fake LLM
  - an in-memory AsyncSqliteSaver checkpointer
  - a configured FastAPI TestClient with the above injected
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.checkpointer import lifespan_checkpointer
from app.agent.graph import build_graph
from app.config import reset_settings_for_tests
from app.kb.fake import FakeKB
from app.main import build_app, build_app_state
from app.services.document_registry import lifespan_document_registry
from tests._fakes import ScriptedChatModel, scripted_chat


@pytest.fixture(autouse=True)
def _reset_settings_each_test() -> Iterator[None]:
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


@pytest.fixture
def fake_kb() -> FakeKB:
    return FakeKB()


@pytest.fixture
def scripted_llm_factory():
    def _make(responses: list[AIMessage]) -> ScriptedChatModel:
        return scripted_chat(responses)

    return _make


@pytest_asyncio.fixture
async def app_with_fakes(fake_kb: FakeKB, scripted_llm_factory) -> AsyncIterator:
    """Yield a FastAPI app preloaded with FakeKB, in-memory checkpointer, and
    a default scripted LLM that always replies with 'ok'.

    Tests can replace `app.state.llm` to script different responses.
    """
    default_llm = scripted_llm_factory(
        [AIMessage(content="ok")] * 32  # plenty for any single test
    )
    async with lifespan_checkpointer(":memory:") as checkpointer:
        async with lifespan_document_registry(":memory:") as registry:
            graph = build_graph(llm=default_llm, kb=fake_kb, checkpointer=checkpointer)
            state = build_app_state(
                llm=default_llm,
                kb=fake_kb,
                checkpointer=checkpointer,
                registry=registry,
                graph=graph,
            )
            app = build_app(state=state)
            yield app


@pytest_asyncio.fixture
async def client(app_with_fakes) -> AsyncIterator[TestClient]:
    with TestClient(app_with_fakes) as c:
        yield c
