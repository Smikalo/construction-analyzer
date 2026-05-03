"""Tests for the LangGraph agent that wires the LLM + KB tools together.

We use a fake LLM that responds with deterministic tool-call sequences so we can
assert the full plan->tool->plan->answer loop without any network access.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.checkpointer import lifespan_checkpointer
from app.agent.graph import build_graph
from app.kb.fake import FakeKB
from tests._fakes import scripted_chat


def _scripted_llm(responses: list[AIMessage]):
    return scripted_chat(responses)


@pytest.fixture
async def kb() -> FakeKB:
    kb = FakeKB()
    await kb.remember("the eiffel tower is in paris, france")
    await kb.remember("the colosseum is in rome, italy")
    return kb


class TestBuildGraph:
    async def test_graph_returns_assistant_response_for_simple_message(self, kb: FakeKB) -> None:
        llm = _scripted_llm([AIMessage(content="hello there!")])
        async with lifespan_checkpointer(":memory:") as saver:
            graph = build_graph(llm=llm, kb=kb, checkpointer=saver)
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config={"configurable": {"thread_id": "t1"}},
            )
            assert result["messages"][-1].content == "hello there!"

    async def test_graph_invokes_kb_recall_tool(self, kb: FakeKB) -> None:
        llm = _scripted_llm(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "kb_recall",
                            "args": {"query": "eiffel"},
                            "id": "call_1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="The Eiffel Tower is in Paris, France."),
            ]
        )
        async with lifespan_checkpointer(":memory:") as saver:
            graph = build_graph(llm=llm, kb=kb, checkpointer=saver)
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="where is the eiffel tower?")]},
                config={"configurable": {"thread_id": "t-recall"}},
            )

        msgs = result["messages"]
        assert any(m.type == "tool" for m in msgs), "expected a ToolMessage in history"
        assert msgs[-1].content == "The Eiffel Tower is in Paris, France."

    async def test_graph_persists_messages_in_checkpointer(self, kb: FakeKB) -> None:
        llm = _scripted_llm(
            [
                AIMessage(content="first reply"),
                AIMessage(content="second reply"),
            ]
        )
        async with lifespan_checkpointer(":memory:") as saver:
            graph = build_graph(llm=llm, kb=kb, checkpointer=saver)
            cfg = {"configurable": {"thread_id": "t-persist"}}

            await graph.ainvoke({"messages": [HumanMessage(content="hi")]}, cfg)
            await graph.ainvoke({"messages": [HumanMessage(content="and again")]}, cfg)

            state = await graph.aget_state(cfg)
            roles = [m.type for m in state.values["messages"]]
            assert roles == ["human", "ai", "human", "ai"]
