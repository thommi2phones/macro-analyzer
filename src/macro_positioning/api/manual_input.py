"""FastAPI sub-router for the manual input layer.

Endpoints (all under /api/manual):
  POST /preview  — JSON payload, returns suggestions, no persistence.
  POST /ingest   — multipart (file optional + payload JSON), persists.
  GET  /inputs   — recent submissions for the /inbox history view.
  GET  /authors  — known authors for the SPA autocomplete.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from macro_positioning.manual import processor
from macro_positioning.manual.authors import list_authors
from macro_positioning.manual.models import (
    IngestResponse,
    ManualInputPayload,
    PreviewResponse,
)


router = APIRouter(prefix="/api/manual", tags=["manual-input"])


# ── Preview ──────────────────────────────────────────────────────────────────


@router.post("/preview", response_model=PreviewResponse)
def preview(payload: ManualInputPayload) -> PreviewResponse:
    return processor.preview(payload)


# ── Ingest (optional file + JSON payload) ────────────────────────────────────


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    payload: str = Form(..., description="JSON-serialized ManualInputPayload"),
    files: Optional[list[UploadFile]] = File(None),
    # Back-compat: clients still using the single-file form keep working.
    file: Optional[UploadFile] = File(None),
) -> IngestResponse:
    try:
        parsed = ManualInputPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    uploaded: list[UploadFile] = []
    if files:
        uploaded.extend(f for f in files if f and f.filename)
    if file is not None and file.filename:
        uploaded.append(file)

    saved_paths: list[str] = []
    for upload in uploaded:
        body = await upload.read()
        if not body:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file '{upload.filename}' is empty.",
            )
        saved_paths.append(processor.save_attachment(body, upload.filename))

    if saved_paths:
        parsed.attachment_paths = saved_paths
        parsed.attachment_path = saved_paths[0]

    return processor.ingest(parsed)


# ── Listings ─────────────────────────────────────────────────────────────────


@router.get("/inputs")
def recent_inputs(limit: int = 50) -> list[dict]:
    limit = max(1, min(200, int(limit)))
    return processor.list_recent_inputs(limit=limit)


@router.get("/authors")
def authors(limit: int = 200) -> list[dict]:
    limit = max(1, min(500, int(limit)))
    return list_authors(limit=limit)
