"""Document ingestion endpoint.

Accepts one or more uploaded files (PDF / Markdown / plain text), saves them
to the gitignored documents directory, and pushes their chunks into the KB.

The same code path is also used by `services.ingestion.ingest_directory()` to
slurp up files dropped into `backend/data/documents/` at startup.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.schemas import IngestResponse
from app.services.ingestion import (
    SUPPORTED_EXTENSIONS,
    RegisteredIngestFile,
    ingest_registered_files,
)

router = APIRouter(prefix="/api", tags=["ingest"])


@dataclass(frozen=True, slots=True)
class _PreparedUpload:
    original_filename: str
    extension: str
    content_type: str
    body: bytes
    content_hash: str
    byte_size: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    request: Request,
    files: Annotated[list[UploadFile], File(...)],
) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    state = request.app.state.app_state
    documents_dir = state.settings.documents_dir
    os.makedirs(documents_dir, exist_ok=True)

    prepared_uploads = await _prepare_uploads(
        files,
        max_upload_bytes=state.settings.max_upload_bytes,
    )
    entries: list[RegisteredIngestFile] = []
    processing_document_ids: set[str] = set()

    for upload in prepared_uploads:
        document_id = uuid.uuid4().hex
        stored_path = os.path.join(documents_dir, f"{document_id}{upload.extension}")
        record, is_duplicate = state.registry.register_or_get(
            upload.content_hash,
            original_filename=upload.original_filename,
            stored_path=stored_path,
            content_type=upload.content_type,
            byte_size=upload.byte_size,
            document_id=document_id,
        )
        should_process = not is_duplicate
        if (
            is_duplicate
            and record.status == "uploaded"
            and record.document_id not in processing_document_ids
        ):
            should_process = True
        if should_process:
            processing_document_ids.add(record.document_id)
        if should_process and (not is_duplicate or not os.path.exists(record.stored_path)):
            with open(record.stored_path, "wb") as out:
                out.write(upload.body)
        entries.append(RegisteredIngestFile(record=record, is_duplicate=not should_process))

    return await ingest_registered_files(
        state.kb,
        state.registry,
        entries,
        document_analyzer=state.document_analyzer,
    )


async def _prepare_uploads(
    files: list[UploadFile],
    *,
    max_upload_bytes: int,
) -> list[_PreparedUpload]:
    prepared: list[_PreparedUpload] = []
    for upload in files:
        filename = _validated_filename(upload.filename)
        extension = _validated_extension(filename)
        body = await upload.read(max_upload_bytes + 1)
        if len(body) > max_upload_bytes:
            raise HTTPException(status_code=413, detail="uploaded file is too large")
        if not body:
            raise HTTPException(status_code=400, detail="uploaded file is empty")
        prepared.append(
            _PreparedUpload(
                original_filename=filename,
                extension=extension,
                content_type=upload.content_type or "",
                body=body,
                content_hash=hashlib.sha256(body).hexdigest(),
                byte_size=len(body),
            )
        )

    if not prepared:
        raise HTTPException(status_code=400, detail="no valid files in upload")
    return prepared


def _validated_filename(filename: str | None) -> str:
    clean_name = (filename or "").strip()
    basename = os.path.basename(clean_name)
    if not basename:
        raise HTTPException(status_code=400, detail="uploaded file is missing a filename")
    return basename


def _validated_extension(filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported file type")
    return extension
