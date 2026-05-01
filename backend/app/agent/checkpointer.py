"""LangGraph checkpointer wiring.

We use `AsyncSqliteSaver` from `langgraph-checkpoint-sqlite`. It is intentionally
file-backed so thread history survives backend restarts. Routes never construct
the saver themselves; they receive it from `app.state.checkpointer` populated by
the FastAPI lifespan.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@asynccontextmanager
async def lifespan_checkpointer(db_path: str) -> AsyncIterator[AsyncSqliteSaver]:
    """Open the checkpointer for the lifetime of the app.

    Pass `":memory:"` for tests. For real deployments pass a file path; parent
    directories are created on the fly so first-run is friction-free.
    """
    if db_path != ":memory:":
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        yield saver
