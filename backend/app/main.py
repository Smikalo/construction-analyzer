"""FastAPI app composition.

The app is built by `build_app(state=...)` so tests can inject a fake KB,
fake LLM, and in-memory checkpointer. In production, `lifespan` constructs
the real components from settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.checkpointer import lifespan_checkpointer
from app.agent.graph import build_graph
from app.agent.llm import get_llm
from app.api import chat, health, ingest, threads
from app.config import Settings, get_settings
from app.kb.base import KnowledgeBase
from app.services.document_analysis import DocumentAnalyzer, build_document_analyzer
from app.services.document_registry import DocumentRegistry, lifespan_document_registry


@dataclass
class AppState:
    settings: Settings
    llm: BaseChatModel
    kb: KnowledgeBase
    checkpointer: BaseCheckpointSaver
    registry: DocumentRegistry
    graph: Any  # CompiledStateGraph; not exposed in stable types
    document_analyzer: DocumentAnalyzer | None = None


def build_app_state(
    *,
    llm: BaseChatModel,
    kb: KnowledgeBase,
    checkpointer: BaseCheckpointSaver,
    registry: DocumentRegistry,
    graph: Any,
    settings: Settings | None = None,
    document_analyzer: DocumentAnalyzer | None = None,
) -> AppState:
    return AppState(
        settings=settings or get_settings(),
        llm=llm,
        kb=kb,
        checkpointer=checkpointer,
        registry=registry,
        graph=graph,
        document_analyzer=document_analyzer,
    )


def _build_kb(settings: Settings) -> KnowledgeBase:
    if settings.kb_backend == "memorypalace":
        from app.kb.memorypalace import MemoryPalaceKB

        return MemoryPalaceKB(
            database_url=settings.memory_palace_database_url,
            embedding_model=settings.memory_palace_embedding_model,
            llm_model=settings.memory_palace_llm_model,
            ollama_host=settings.ollama_host,
            instance_id=settings.memory_palace_instance_id,
        )
    from app.kb.fake import FakeKB

    return FakeKB()


@asynccontextmanager
async def _production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    llm = get_llm(settings)
    kb = _build_kb(settings)
    document_analyzer = build_document_analyzer(settings)

    async with lifespan_checkpointer(settings.checkpoint_db_path) as checkpointer:
        async with lifespan_document_registry(settings.registry_db_path) as registry:
            graph = build_graph(llm=llm, kb=kb, checkpointer=checkpointer)
            app.state.app_state = build_app_state(
                llm=llm,
                kb=kb,
                checkpointer=checkpointer,
                registry=registry,
                graph=graph,
                settings=settings,
                document_analyzer=document_analyzer,
            )
            yield


def build_app(*, state: AppState | None = None) -> FastAPI:
    """Build the FastAPI app.

    If `state` is provided (used by tests), the app is wired up directly with
    that state. Otherwise, a production lifespan constructs the real components.
    """
    if state is not None:

        @asynccontextmanager
        async def _injected_lifespan(app: FastAPI) -> AsyncIterator[None]:
            app.state.app_state = state
            yield

        lifespan = _injected_lifespan
    else:
        lifespan = _production_lifespan

    app = FastAPI(
        title="construction-analyzer backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(threads.router)
    app.include_router(ingest.router)

    return app


app = build_app()
