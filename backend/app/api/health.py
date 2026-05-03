"""Liveness and readiness probes.

`/health` is cheap and never depends on external services. It is what container
orchestrators and the frontend connection badge use.

`/ready` actively probes the KB and checkpointer (and, in production, Postgres
and Ollama via the KB) to decide whether the backend can serve real chat
traffic. It always returns 200 and instead encodes status in the body so
single-page apps can render a graceful degraded state.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request

from app.schemas import HealthStatus, ReadinessStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/ready", response_model=ReadinessStatus)
async def ready(request: Request) -> ReadinessStatus:
    state = request.app.state.app_state

    kb_ok = await _safe(state.kb.health())
    ckpt_ok = state.checkpointer is not None

    # Only probe external services when the real KB needs them. In `fake` mode
    # (tests/dev) we report them as available so /ready can be green without
    # Postgres or Ollama running.
    if state.settings.kb_backend == "memorypalace":
        ollama_ok = await _ollama_ok(state.settings.ollama_host)
        pg_ok = await _postgres_ok(state.settings.memory_palace_database_url)
    else:
        ollama_ok = True
        pg_ok = True

    all_ok = kb_ok and ckpt_ok and ollama_ok and pg_ok
    return ReadinessStatus(
        status="ready" if all_ok else "degraded",
        ollama=ollama_ok,
        postgres=pg_ok,
        checkpointer=ckpt_ok,
        kb=kb_ok,
        detail=None
        if all_ok
        else "; ".join(
            label
            for label, ok in [
                ("ollama", ollama_ok),
                ("postgres", pg_ok),
                ("checkpointer", ckpt_ok),
                ("kb", kb_ok),
            ]
            if not ok
        ),
    )


async def _safe(coro) -> bool:
    try:
        return bool(await coro)
    except Exception:
        return False


async def _ollama_ok(host: str) -> bool:
    """Probe Ollama. We treat an unreachable host as degraded but never fail
    the readiness call: in pure-fake test mode there is no Ollama at all and
    the suite must still pass."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(f"{host.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def _postgres_ok(database_url: str) -> bool:
    """Best-effort Postgres reachability check using asyncpg.

    Returns False on any failure (including missing driver). The /ready
    endpoint encodes this in the response rather than raising.
    """
    try:
        import asyncpg  # type: ignore[import-untyped]

        # asyncpg doesn't accept the SQLAlchemy-style "postgresql://" prefix in
        # all versions, normalise to its native form.
        url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn=url, timeout=1.0)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return True
    except Exception:
        return False
