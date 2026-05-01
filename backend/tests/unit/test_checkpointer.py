"""Checkpointer must persist LangGraph state across two separate `compile()` calls
on the same SQLite file.

This is the property we rely on for `/api/threads/{id}/history` to actually
return the prior turns in a conversation after a backend restart.
"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agent.checkpointer import lifespan_checkpointer


class CounterState(TypedDict):
    n: Annotated[int, operator.add]


def _build_counter_graph(checkpointer):
    def increment(_: CounterState) -> CounterState:
        return {"n": 1}

    builder = StateGraph(CounterState)
    builder.add_node("inc", increment)
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)
    return builder.compile(checkpointer=checkpointer)


class TestAsyncSqliteSaverPersistence:
    async def test_in_memory_saver_works_in_one_session(self) -> None:
        async with lifespan_checkpointer(":memory:") as saver:
            graph = _build_counter_graph(saver)
            cfg = {"configurable": {"thread_id": "t1"}}

            await graph.ainvoke({"n": 0}, cfg)
            await graph.ainvoke({"n": 0}, cfg)

            state = await graph.aget_state(cfg)
            assert state.values["n"] == 2

    async def test_state_persists_to_disk_across_open_close_cycles(
        self, tmp_path: Path
    ) -> None:
        db_path = str(tmp_path / "ckpt.sqlite")
        cfg = {"configurable": {"thread_id": "t-disk"}}

        async with lifespan_checkpointer(db_path) as saver:
            graph = _build_counter_graph(saver)
            await graph.ainvoke({"n": 0}, cfg)
            await graph.ainvoke({"n": 0}, cfg)

        async with lifespan_checkpointer(db_path) as saver:
            graph = _build_counter_graph(saver)
            state = await graph.aget_state(cfg)
            assert state.values["n"] == 2

            await graph.ainvoke({"n": 0}, cfg)
            state2 = await graph.aget_state(cfg)
            assert state2.values["n"] == 3

    async def test_threads_are_isolated(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "iso.sqlite")
        async with lifespan_checkpointer(db_path) as saver:
            graph = _build_counter_graph(saver)
            await graph.ainvoke({"n": 0}, {"configurable": {"thread_id": "a"}})
            await graph.ainvoke({"n": 0}, {"configurable": {"thread_id": "a"}})
            await graph.ainvoke({"n": 0}, {"configurable": {"thread_id": "b"}})

            state_a = await graph.aget_state({"configurable": {"thread_id": "a"}})
            state_b = await graph.aget_state({"configurable": {"thread_id": "b"}})

            assert state_a.values["n"] == 2
            assert state_b.values["n"] == 1
