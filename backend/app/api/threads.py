"""Thread management routes.

The checkpointer is the source of truth. We never keep a parallel thread
table; `/api/threads` lists the distinct thread ids it has seen, and
`/api/threads/{id}/history` replays the latest checkpointed state.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    Message,
    ThreadCreated,
    ThreadHistory,
    ThreadInfo,
)

router = APIRouter(prefix="/api/threads", tags=["threads"])


@router.post("", response_model=ThreadCreated, status_code=201)
async def create_thread() -> ThreadCreated:
    return ThreadCreated(thread_id=str(uuid.uuid4()))


@router.get("", response_model=list[ThreadInfo])
async def list_threads(request: Request) -> list[ThreadInfo]:
    state = request.app.state.app_state
    seen: dict[str, ThreadInfo] = {}

    async for ckpt in state.checkpointer.alist(config=None):
        cfg = ckpt.config or {}
        tid = cfg.get("configurable", {}).get("thread_id")
        if not tid:
            continue
        msgs = (ckpt.checkpoint.get("channel_values", {}) or {}).get("messages") or []
        ts = ckpt.checkpoint.get("ts")
        info = seen.get(tid)
        if info is None or (ts and (info.last_message_at or 0) < _ts(ts)):
            seen[tid] = ThreadInfo(
                thread_id=tid,
                message_count=len(msgs),
                last_message_at=_ts(ts),
            )

    return sorted(
        seen.values(),
        key=lambda t: t.last_message_at or 0.0,
        reverse=True,
    )


@router.get("/{thread_id}/history", response_model=ThreadHistory)
async def get_history(thread_id: str, request: Request) -> ThreadHistory:
    state = request.app.state.app_state
    snapshot = await state.graph.aget_state({"configurable": {"thread_id": thread_id}})
    if snapshot is None or not snapshot.values:
        return ThreadHistory(thread_id=thread_id, messages=[])

    messages: list[Message] = []
    for m in snapshot.values.get("messages", []):
        role = _role_for(m)
        if role is None:
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        if role == "tool" and not content:
            continue
        messages.append(Message(role=role, content=content))

    return ThreadHistory(thread_id=thread_id, messages=messages)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request) -> None:
    state = request.app.state.app_state
    deleter = getattr(state.checkpointer, "adelete_thread", None)
    if deleter is None:
        raise HTTPException(
            status_code=501,
            detail="checkpointer does not support thread deletion",
        )
    await deleter(thread_id)


def _ts(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _role_for(message: Any) -> str | None:
    t = getattr(message, "type", None)
    return {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "tool": "tool",
    }.get(t)
