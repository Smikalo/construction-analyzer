"""LangChain tools that expose the KnowledgeBase to the agent.

The KB is captured by closure so we can build a fresh tool list per request
backed by the same in-memory or Postgres-backed KB instance.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.kb.base import KnowledgeBase


class _RecallArgs(BaseModel):
    query: str = Field(description="Natural-language query to search the knowledge base.")
    k: int = Field(default=5, ge=1, le=20, description="Max number of memories to return.")


class _RememberArgs(BaseModel):
    content: str = Field(description="The fact, decision, or note to remember.")


def build_kb_tools(kb: KnowledgeBase) -> list[StructuredTool]:
    async def _recall(query: str, k: int = 5) -> str:
        hits = await kb.recall(query, k=k)
        if not hits:
            return "No relevant memories found."
        return "\n".join(f"- ({h['id']}) {h['content']}" for h in hits)

    async def _remember(content: str) -> str:
        mid = await kb.remember(content)
        return f"Remembered with id {mid}."

    return [
        StructuredTool.from_function(
            coroutine=_recall,
            name="kb_recall",
            description=(
                "Search the knowledge base for memories relevant to a query. "
                "Use this whenever the user asks about prior context, ingested "
                "documents, or facts that may already be stored."
            ),
            args_schema=_RecallArgs,
        ),
        StructuredTool.from_function(
            coroutine=_remember,
            name="kb_remember",
            description=(
                "Persist a new fact or decision to long-term memory. "
                "Use this when the user explicitly tells you to remember something."
            ),
            args_schema=_RememberArgs,
        ),
    ]
