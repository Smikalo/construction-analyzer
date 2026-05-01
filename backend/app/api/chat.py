"""Chat endpoints.

`/api/chat` streams Server-Sent Events of `ChatChunk` payloads as the agent
plans, calls tools, and emits tokens.
`/api/chat/sync` is a non-streaming convenience for tests and curl-based smoke
checks; it returns the final assistant message as JSON.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage
from sse_starlette.sse import EventSourceResponse

from app.schemas import ChatChunk, ChatRequest, Message

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat_stream(req: ChatRequest, request: Request):
    state = request.app.state.app_state
    thread_id = req.thread_id or str(uuid.uuid4())
    cfg = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }

    async def event_gen():
        # Tell the client which thread this stream belongs to so a brand-new
        # session can persist the id immediately (before the first token).
        yield {
            "event": "message",
            "data": ChatChunk(type="token", data="").model_dump_json(),
        }
        yield {
            "event": "thread",
            "data": json.dumps({"thread_id": thread_id}),
        }

        graph = state.graph
        try:
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=req.message)]},
                config=cfg,
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    text = getattr(chunk, "content", "") if chunk is not None else ""
                    if text:
                        yield {
                            "event": "message",
                            "data": ChatChunk(type="token", data=text).model_dump_json(),
                        }
                elif kind == "on_tool_start":
                    name = event.get("name", "tool")
                    yield {
                        "event": "message",
                        "data": ChatChunk(
                            type="tool_call", data=name
                        ).model_dump_json(),
                    }
                elif kind == "on_tool_end":
                    name = event.get("name", "tool")
                    yield {
                        "event": "message",
                        "data": ChatChunk(
                            type="tool_result", data=name
                        ).model_dump_json(),
                    }
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "message",
                "data": ChatChunk(type="error", data=str(exc)).model_dump_json(),
            }
        finally:
            yield {
                "event": "message",
                "data": ChatChunk(type="done", data="").model_dump_json(),
            }

    return EventSourceResponse(event_gen())


DEFAULT_RECURSION_LIMIT = 8


@router.post("/chat/sync")
async def chat_sync(req: ChatRequest, request: Request) -> dict:
    """Non-streaming version: invoke the graph and return the final assistant
    message. Used by tests and the smoke script."""
    state = request.app.state.app_state
    thread_id = req.thread_id or str(uuid.uuid4())
    cfg = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }

    try:
        result = await state.graph.ainvoke(
            {"messages": [HumanMessage(content=req.message)]},
            config=cfg,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    last = result["messages"][-1]
    if isinstance(last, AIMessage):
        content = last.content if isinstance(last.content, str) else str(last.content)
    else:
        content = str(getattr(last, "content", ""))

    return {
        "thread_id": thread_id,
        "message": Message(role="assistant", content=content).model_dump(),
    }
