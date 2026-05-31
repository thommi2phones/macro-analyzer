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
    AuthorRef,
    IngestResponse,
    ManualInputPayload,
    PreviewResponse,
)


router = APIRouter(prefix="/api/manual", tags=["manual-input"])


# ── Preview ──────────────────────────────────────────────────────────────────


@router.post("/preview", response_model=PreviewResponse)
async def preview(payload: ManualInputPayload) -> PreviewResponse:
    """JSON-only preview path (no image OCR). Kept for back-compat with the
    earlier client that posted application/json directly."""
    return processor.preview(payload)


@router.post("/preview/multipart", response_model=PreviewResponse)
async def preview_multipart(
    payload: str = Form(..., description="JSON-serialized ManualInputPayload"),
    files: Optional[list[UploadFile]] = File(None),
) -> PreviewResponse:
    """Multipart preview that runs heuristic OCR over uploaded image bytes.

    Files are saved under uploads/charts/YYYY-MM/{uuid}.{ext} so a later
    /ingest call can reference them — the SPA reuses the same paths to
    avoid re-uploading on save. To keep /preview side-effect light, OCR
    errors never bubble; missing fields stay null.
    """
    try:
        parsed = ManualInputPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    saved_paths: list[str] = []
    for upload in files or []:
        if not upload or not upload.filename:
            continue
        body = await upload.read()
        if not body:
            # Empty upload is a no-op for preview (don't 400 — user is mid-edit).
            continue
        saved_paths.append(processor.save_attachment(body, upload.filename))

    if saved_paths:
        parsed.attachment_paths = saved_paths
        parsed.attachment_path = saved_paths[0]

    response = processor.preview(parsed, image_paths=saved_paths)
    # Echo the saved paths so the client can attach them to the eventual
    # /ingest call without re-uploading the same bytes.
    if saved_paths:
        if response.image_suggestions is None:
            response.image_suggestions = {}
        response.image_suggestions["saved_paths"] = saved_paths
    return response


# ── Ingest (optional file + JSON payload) ────────────────────────────────────


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    payload: str = Form(..., description="JSON-serialized ManualInputPayload"),
    files: Optional[list[UploadFile]] = File(None),
    # Back-compat: clients still using the single-file form keep working.
    file: Optional[UploadFile] = File(None),
    analyze: bool = Form(default=False, description="Run Claude vision inline before responding."),
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

    response = processor.ingest(parsed)

    # Optional inline drain — caller passes analyze=true to wait for Claude
    # vision. Adds ~20s/image latency. The endpoint stays the same; just
    # blocks until the extracted_features_json is written.
    if analyze and response.pending_vision:
        try:
            from macro_positioning.manual.vision_drainer import drain
            drain(document_id=response.document_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("inline drain failed")

    return response


# ── Listings ─────────────────────────────────────────────────────────────────


@router.get("/inputs")
def recent_inputs(limit: int = 50) -> list[dict]:
    limit = max(1, min(200, int(limit)))
    return processor.list_recent_inputs(limit=limit)


@router.get("/authors")
def authors(limit: int = 200) -> list[dict]:
    limit = max(1, min(500, int(limit)))
    return list_authors(limit=limit)


# ── Author management (explicit create) ──────────────────────────────────────


@router.post("/vision/drain")
def drain_pending_vision(limit: int = 25, document_id: Optional[str] = None) -> dict:
    """Process pending_vision documents — calls Claude on each attachment,
    writes the extracted TradeRecord into extracted_features_json, clears
    the flag. Idempotent: hash-cached results return instantly. Safe to
    poll from the SPA or run on a cron."""
    from macro_positioning.manual.vision_drainer import drain
    summary = drain(limit=max(1, min(200, limit)), document_id=document_id)
    return summary.to_dict()


@router.post("/authors")
def create_author(ref: AuthorRef) -> dict:
    """Create (or touch) a known-source author without needing a full drop.

    Lets the SPA pre-create a new author from the picklist UI so it shows
    up as a pill for future drops. Idempotent — re-posting the same
    name+channel returns the existing author_id and refreshes last_seen_at.
    """
    from macro_positioning.manual.authors import upsert_author
    if not (ref.display_name or "").strip():
        raise HTTPException(status_code=400, detail="display_name is required")
    author_id = upsert_author(ref)
    return {"author_id": author_id, "display_name": ref.display_name,
            "channel": ref.channel, "channel_type": ref.channel_type}
