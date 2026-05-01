"""KnowledgeBase adapter over the MemoryPalace Python library.

MemoryPalace is a synchronous SQLAlchemy-based library that reads its
configuration from environment variables at import time. We:

1. Set the relevant env vars in `__init__` before importing.
2. Run the blocking remember/recall calls in a worker thread so the FastAPI
   event loop never blocks.
3. Adapt the rich MemoryPalace dict format to our minimal `MemoryRecord`.

The real test for this adapter lives in `tests/integration/test_memorypalace_kb.py`
and is gated by `pytest.mark.integration`; it is skipped when Postgres or
Ollama are not reachable, so the default `pytest -q` run stays hermetic.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from app.kb.base import KnowledgeBase, MemoryRecord

logger = logging.getLogger(__name__)


class MemoryPalaceKB(KnowledgeBase):
    def __init__(
        self,
        *,
        database_url: str,
        ollama_host: str,
        embedding_model: str = "nomic-embed-text",
        llm_model: str = "qwen3:1.7b",
        instance_id: str = "construction-analyzer",
        memory_type: str = "document",
        project: str = "construction-analyzer",
    ) -> None:
        self._database_url = database_url
        self._ollama_host = ollama_host
        self._instance_id = instance_id
        self._memory_type = memory_type
        self._project = project

        os.environ["MEMORY_PALACE_DATABASE_URL"] = database_url
        os.environ["OLLAMA_HOST"] = ollama_host
        os.environ["MEMORY_PALACE_EMBEDDING_MODEL"] = embedding_model
        os.environ["MEMORY_PALACE_LLM_MODEL"] = llm_model
        os.environ.setdefault("MEMORY_PALACE_INSTANCE_ID", instance_id)

        # MemoryPalace's `services/__init__.py` eagerly imports `code_service`,
        # which in turn imports `code_transpiler` -- a sibling module that is
        # not packaged with the upstream library. We stub it out so the rest
        # of the services package imports cleanly. We never call code_service
        # in this adapter (only the memory + recall path).
        self._install_code_transpiler_stub()

        try:
            from memory_palace import database_v3  # noqa: WPS433
            from memory_palace.services import memory_service  # noqa: WPS433

            self._service = memory_service
            self._database = database_v3
        except ImportError as exc:  # pragma: no cover - exercised in containers
            raise RuntimeError(
                "memory_palace is not installed in this environment. "
                "Install via `pip install -e git+https://github.com/jeffpierce/"
                "memory-palace.git#egg=memory_palace` or use the docker image."
            ) from exc

        # Eagerly create the schema (and pgvector extension) so the first
        # call -- whether `recall` or `remember` -- doesn't blow up on a
        # missing `memories` table.
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            self._database.ensure_database_exists()
        except Exception as exc:  # pragma: no cover
            logger.warning("ensure_database_exists failed: %s", exc)
        try:
            self._database.init_db()
        except Exception as exc:  # pragma: no cover
            logger.warning("init_db failed: %s", exc)

    @staticmethod
    def _install_code_transpiler_stub() -> None:
        import sys
        import types

        if "code_transpiler" in sys.modules:
            return
        stub = types.ModuleType("code_transpiler")

        def _unsupported(*_args, **_kwargs):
            raise NotImplementedError(
                "code_transpiler is not installed; this adapter does not use code indexing."
            )

        stub.transpile_code_to_prose = _unsupported  # type: ignore[attr-defined]
        stub.transpile_file = _unsupported  # type: ignore[attr-defined]
        sys.modules["code_transpiler"] = stub

    async def remember(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        meta = metadata or {}
        result = await asyncio.to_thread(
            self._service.remember,
            instance_id=self._instance_id,
            memory_type=meta.get("memory_type", self._memory_type),
            content=content,
            subject=meta.get("subject") or meta.get("source"),
            keywords=meta.get("keywords"),
            tags=meta.get("tags"),
            project=meta.get("project", self._project),
            source_type="explicit",
            source_context=meta.get("source"),
        )
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"memory_palace.remember failed: {result['error']}")
        if isinstance(result, dict):
            return str(result.get("id", ""))
        return str(result)

    async def recall(self, query: str, k: int = 5) -> list[MemoryRecord]:
        result = await asyncio.to_thread(
            self._service.recall,
            query=query,
            instance_id=self._instance_id,
            limit=k,
            synthesize=False,
            include_graph=False,
        )
        memories = (result or {}).get("memories", []) if isinstance(result, dict) else []
        records: list[MemoryRecord] = []
        for m in memories[:k]:
            records.append(
                MemoryRecord(
                    id=str(m.get("id", "")),
                    content=str(m.get("content", "")),
                    metadata={
                        "subject": m.get("subject"),
                        "memory_type": m.get("memory_type"),
                        "project": m.get("projects") or m.get("project"),
                        "tags": m.get("tags"),
                        "keywords": m.get("keywords"),
                    },
                    score=float(m.get("score", 0.0) or 0.0),
                )
            )
        return records

    async def health(self) -> bool:
        return await self._ollama_ok() and await self._postgres_ok()

    async def _ollama_ok(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self._ollama_host.rstrip('/')}/api/tags")
                return r.status_code == 200
        except Exception:
            logger.warning("ollama unreachable at %s", self._ollama_host)
            return False

    async def _postgres_ok(self) -> bool:
        try:
            import asyncpg

            url = self._database_url.replace("postgresql+asyncpg://", "postgresql://")
            conn = await asyncpg.connect(dsn=url, timeout=2.0)
            try:
                await conn.execute("SELECT 1")
            finally:
                await conn.close()
            return True
        except Exception:
            logger.warning("postgres unreachable at %s", self._database_url)
            return False
