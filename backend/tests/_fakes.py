"""Test-only LLM fake that supports `bind_tools` (no-op) and `astream_events`.

LangChain ships `GenericFakeChatModel` but its `bind_tools` is unimplemented,
which prevents us from exercising the agent loop. This shim is the smallest
possible surface that lets the tests assert plan->tool->plan->answer flow
without any network access.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """A chat model that returns the next AIMessage from a scripted iterator
    on each invocation. Supports `bind_tools` as a no-op."""

    responses: list[AIMessage]
    _cursor: int = 0

    def __init__(self, responses: list[AIMessage]):
        super().__init__(responses=responses)
        object.__setattr__(self, "_cursor", 0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _next(self) -> AIMessage:
        idx = object.__getattribute__(self, "_cursor")
        if idx >= len(self.responses):
            return AIMessage(content="(no more scripted responses)")
        resp = self.responses[idx]
        object.__setattr__(self, "_cursor", idx + 1)
        return resp

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def bind_tools(self, tools: Any, **kwargs: Any):  # type: ignore[override]
        return self


def scripted_chat(messages: Iterator[AIMessage] | list[AIMessage]) -> ScriptedChatModel:
    return ScriptedChatModel(responses=list(messages))
