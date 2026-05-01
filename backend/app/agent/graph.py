"""LangGraph state graph: agent <-> tools loop with persistent checkpointing.

The graph is intentionally tiny so it stays easy to reason about during a
hackathon: one agent node that calls the LLM, one tool node that dispatches
KB calls, and a conditional edge that loops until the LLM stops emitting
tool calls.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.tools import build_kb_tools
from app.kb.base import KnowledgeBase

SYSTEM_PROMPT = (
    "You are construction-analyzer, a helpful assistant with access to a "
    "long-term knowledge base via the `kb_recall` and `kb_remember` tools. "
    "When the user asks about ingested documents, prior context, or facts that "
    "might already be stored, call `kb_recall` first. When the user explicitly "
    "asks you to remember something, call `kb_remember`. Be concise and helpful."
)


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(
    *,
    llm: BaseChatModel,
    kb: KnowledgeBase,
    checkpointer: BaseCheckpointSaver,
):
    """Build and compile the agent graph.

    The graph is cheap to compile; the checkpointer is the heavyweight thing
    and is owned by the FastAPI lifespan.
    """
    tools = build_kb_tools(kb)
    llm_with_tools = llm.bind_tools(tools)

    async def agent_node(state: AgentState) -> AgentState:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=SYSTEM_PROMPT), *msgs]
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
