"""Integration test for MemoryPalaceKB.

Skipped unless ALL of the following are true:
  - the `memory_palace` package is importable
  - Postgres is reachable at MEMORY_PALACE_DATABASE_URL
  - Ollama is reachable at OLLAMA_HOST and has the embedding model pulled

In CI / hackathon dev mode this means the test runs only inside the docker
compose stack via `make test-backend`, never on a bare host.
"""

from __future__ import annotations

import asyncio
import os
import socket
from urllib.parse import urlparse

import pytest


def _can_connect(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _required_services_available() -> tuple[bool, str]:
    try:
        import memory_palace  # noqa: F401
    except ImportError:
        return False, "memory_palace not installed"

    db_url = os.getenv(
        "MEMORY_PALACE_DATABASE_URL",
        "postgresql://construction:construction@postgres:5432/memory_palace",
    )
    parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://"))
    if not _can_connect(parsed.hostname or "localhost", parsed.port or 5432):
        return False, f"postgres unreachable at {parsed.hostname}:{parsed.port}"

    ollama_host = os.getenv("OLLAMA_HOST", "http://ollama:11434")
    ollama_url = urlparse(ollama_host)
    if not _can_connect(ollama_url.hostname or "localhost", ollama_url.port or 11434):
        return False, f"ollama unreachable at {ollama_host}"

    return True, ""


_AVAILABLE, _SKIP_REASON = _required_services_available()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _AVAILABLE, reason=_SKIP_REASON),
]


@pytest.fixture
def kb():
    from app.kb.memorypalace import MemoryPalaceKB

    return MemoryPalaceKB(
        database_url=os.environ["MEMORY_PALACE_DATABASE_URL"],
        ollama_host=os.environ["OLLAMA_HOST"],
        embedding_model=os.getenv("MEMORY_PALACE_EMBEDDING_MODEL", "nomic-embed-text"),
        llm_model=os.getenv("MEMORY_PALACE_LLM_MODEL", "qwen3:1.7b"),
        instance_id="construction-analyzer-test",
        project="construction-analyzer-test",
    )


class TestMemoryPalaceKB:
    async def test_health_passes_when_services_up(self, kb) -> None:
        assert await kb.health() is True

    async def test_remember_then_recall_round_trip(self, kb) -> None:
        marker = f"test-marker-{asyncio.get_running_loop().time():.6f}"
        content = f"The {marker} secret value is 42."
        mid = await kb.remember(content, metadata={"source": "integration-test"})
        assert mid

        # Embedding is async-ish in MemoryPalace; give it a beat.
        await asyncio.sleep(1.0)

        results = await kb.recall(marker, k=5)
        assert any(marker in r["content"] for r in results)
