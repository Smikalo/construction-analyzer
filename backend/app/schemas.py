"""Public API schemas shared between routes, the agent, and the frontend.

These are the wire format. Treat changes here as breaking.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["user", "assistant", "system", "tool"]
ChunkType = Literal["token", "tool_call", "tool_result", "error", "done"]


class Message(BaseModel):
    role: Role
    content: str = ""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None

    @field_validator("message")
    @classmethod
    def _no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be whitespace only")
        return v


class ChatChunk(BaseModel):
    """One frame of an SSE stream."""

    type: ChunkType
    data: str = ""


class ThreadInfo(BaseModel):
    thread_id: str
    message_count: int = 0
    last_message_at: float | None = None


class ThreadHistory(BaseModel):
    thread_id: str
    messages: list[Message] = Field(default_factory=list)


class ThreadCreated(BaseModel):
    thread_id: str


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessStatus(BaseModel):
    status: Literal["ready", "degraded"]
    ollama: bool
    postgres: bool
    checkpointer: bool
    kb: bool
    detail: str | None = None


class IngestResponse(BaseModel):
    ingested_files: int
    ingested_chunks: int
    memory_ids: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
