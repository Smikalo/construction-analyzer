"""Document ingestion endpoint.

Accepts one or more uploaded files (PDF / Markdown / plain text), saves them
to the gitignored documents directory, and pushes their chunks into the KB.

The same code path is also used by `services.ingestion.ingest_directory()` to
slurp up files dropped into `backend/data/documents/` at startup.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.schemas import IngestResponse
from app.services.ingestion import ingest_files

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    request: Request,
    files: list[UploadFile] = File(...),
) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    state = request.app.state.app_state
    documents_dir = state.settings.documents_dir
    os.makedirs(documents_dir, exist_ok=True)

    saved_paths: list[str] = []
    for f in files:
        if not f.filename:
            continue
        target = os.path.join(documents_dir, os.path.basename(f.filename))
        body = await f.read()
        with open(target, "wb") as out:
            out.write(body)
        saved_paths.append(target)

    if not saved_paths:
        raise HTTPException(status_code=400, detail="no valid files in upload")

    result = await ingest_files(state.kb, saved_paths)
    return result
