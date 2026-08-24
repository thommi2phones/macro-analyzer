"""Manual input processor — preview and ingest orchestration.

Preview:  run pre-tagger + mention_extractor + chat_parser heuristics
          on a payload and return suggestions. No persistence.
Ingest:   persist the attachment (if any), upsert the author, insert a
          documents row with manual metadata, return the document_id.

Manual documents follow the same shape as automated ingestion so they
flow through `resolve_watchlist()` and the scoring runner unchanged.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from macro_positioning.core.settings import settings
from macro_positioning.ingestion.pre_tagger import detect_tags, route_to_agents
from macro_positioning.manual.authors import find_author_id, upsert_author
from macro_positioning.manual.chat_parser import (
    detect_side,
    detect_timeframe,
    extract_first_line,
)
from macro_positioning.manual.models import (
    IngestResponse,
    ManualInputPayload,
    ManualMetadata,
    PreviewResponse,
)
from macro_positioning.scoring.mention_extractor import extract_tickers_from_text


# ── Helpers ──────────────────────────────────────────────────────────────────


def _combined_text(payload: ManualInputPayload) -> str:
    """Concatenate everything that should feed tag/ticker detection."""
    parts: list[str] = []
    if payload.metadata.note:
        parts.append(payload.metadata.note)
    if payload.metadata.ticker:
        # Putting it on its own line lets the mention extractor find it
        # even if the user didn't mention the ticker in the body text.
        parts.append(f"${payload.metadata.ticker}")
    if payload.text:
        parts.append(payload.text)
    return "\n\n".join(parts)


def _ensure_manual_tag(tags: set[str]) -> set[str]:
    """Manual drops always get the `manual` tag so source_routing can fan
    them out specifically (vs. only matching whatever keywords appear)."""
    tags.add("manual")
    return tags


# ── Preview (no persistence) ─────────────────────────────────────────────────


def preview(
    payload: ManualInputPayload,
    image_paths: Optional[list[str]] = None,
) -> PreviewResponse:
    text = _combined_text(payload)
    tickers = sorted(extract_tickers_from_text(text))
    tags = _ensure_manual_tag(detect_tags(text))
    agents = route_to_agents(tags)

    suggested_author_id: Optional[str] = None
    if payload.author and payload.author.display_name:
        suggested_author_id = find_author_id(
            payload.author.display_name, payload.author.channel
        )

    # Image-derived auto-fill: heuristic OCR over each attached chart.
    # Imported lazily so /preview keeps working even if pytesseract/Pillow
    # aren't installed (degrades to text-only suggestions).
    image_suggestions = None
    paths = list(image_paths or [])
    if not paths and payload.attachment_paths:
        paths = list(payload.attachment_paths)
    if not paths and payload.attachment_path:
        paths = [payload.attachment_path]
    if paths:
        try:
            from macro_positioning.manual.heuristic_ocr import analyze_images
            sug = analyze_images(paths)
            image_suggestions = sug.to_dict()
            # Promote OCR-detected ticker into detected_tickers if missing.
            if sug.ticker and sug.ticker not in tickers:
                tickers = sorted({*tickers, sug.ticker})
        except Exception:
            # Never let OCR errors break preview — log & continue with text-only.
            import logging
            logging.getLogger(__name__).exception("Heuristic OCR failed")

    return PreviewResponse(
        detected_tickers=tickers,
        suggested_tags=sorted(tags),
        suggested_agents=sorted(agents),
        suggested_author_id=suggested_author_id,
        image_suggestions=image_suggestions,
    )


# ── Auto-fill metadata (used by ingest if user left fields blank) ────────────


def _autofill_metadata(meta: ManualMetadata, text: str, tickers: list[str]) -> ManualMetadata:
    """Fill in blanks the user didn't fill. Never overrides set values."""
    return ManualMetadata(
        ticker=meta.ticker or (tickers[0] if tickers else None),
        side=meta.side or detect_side(text),
        conviction=meta.conviction,
        timeframe=meta.timeframe or detect_timeframe(text),
        note=meta.note or extract_first_line(text),
    )


# ── Ingest (persistence) ─────────────────────────────────────────────────────


def ingest(payload: ManualInputPayload) -> IngestResponse:
    """Persist a manual drop end-to-end.

    Steps:
      1. Upsert input_authors → get author_id.
      2. Compute combined text, detected tickers, tags.
      3. Auto-fill missing metadata fields.
      4. Insert documents row (source_id="manual:{author_id}",
         content_type, tags_json with `pending_vision` when image present).
    Returns the document_id and the resolved tags/tickers for the SPA to display.
    """
    author_id = upsert_author(payload.author)
    text = _combined_text(payload)
    tickers = sorted(extract_tickers_from_text(text))
    tags = _ensure_manual_tag(detect_tags(text))
    meta = _autofill_metadata(payload.metadata, text, tickers)

    # Normalize: treat the singular path as the first of the list when
    # only the single-file API surface was used.
    attachment_paths = list(payload.attachment_paths)
    if not attachment_paths and payload.attachment_path:
        attachment_paths = [payload.attachment_path]
    primary_path = attachment_paths[0] if attachment_paths else None
    pending_vision = bool(attachment_paths)
    if pending_vision:
        tags.add("chart")
        tags.add("vision")

    document_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    has_image = pending_vision
    content_type = "manual_chart" if has_image else "manual_note"

    # tags_json carries the routing decision plus piece-2 hints.
    tags_payload = {
        "tags": sorted(tags),
        "agents": sorted(route_to_agents(tags)),
        "pending_vision": pending_vision,
        "tickers": tickers,
    }

    title_bits = [meta.ticker, meta.side, payload.author.display_name]
    title = " · ".join([b for b in title_bits if b]) or "Manual input"

    # Build user_metadata_json — what the SPA captured + auto-fills the
    # processor inferred. Keep both sides explicit so the dashboard can
    # show "auto" badges later.
    user_meta_payload = {
        "user": payload.metadata.model_dump(),
        "resolved": meta.model_dump(),
        "channel": payload.author.channel,
        "channel_type": payload.author.channel_type,
    }

    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            INSERT INTO documents (
                document_id, source_id, title, url, published_at, author,
                content_type, raw_text, cleaned_text, tags_json, ingested_at,
                author_id, user_metadata_json, attachment_path,
                extracted_features_json, attachment_paths_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                f"manual:{author_id}",
                title,
                None,                       # url — manual drops have none
                now,                        # published_at
                payload.author.display_name,
                content_type,
                payload.text or "",
                text,                       # cleaned_text — drives mention extraction
                json.dumps(tags_payload),
                now,                        # ingested_at
                author_id,
                json.dumps(user_meta_payload),
                primary_path,
                None,                       # extracted_features_json — Piece 2 fills
                json.dumps(attachment_paths) if attachment_paths else None,
            ),
        )
        connection.commit()

    # Inline signal extraction for self-authored drops. Other drops go
    # through the batched morning_run extraction stage. The extraction
    # itself is wrapped in try/except: if anything fails the document
    # still persists and falls through to the deferred batch path.
    inline_signals: list[dict] = []
    inline_err: str | None = None
    if payload.is_self_authored:
        try:
            from macro_positioning.signals.runner import extract_for_document

            # Rehydrate the doc shape the extractors expect — same field
            # set the batch path reads from `pending_documents`.
            doc_for_extract = {
                "document_id": document_id,
                "source_id": f"manual:{author_id}",
                "title": title,
                "url": None,
                "published_at": now,
                "author": payload.author.display_name,
                "author_id": author_id,
                "content_type": content_type,
                "raw_text": payload.text or "",
                "cleaned_text": text,
                "tags_json": json.dumps(tags_payload),
                "user_metadata_json": json.dumps(user_meta_payload),
                "attachment_path": primary_path,
                "attachment_paths_json": (
                    json.dumps(attachment_paths) if attachment_paths else None
                ),
            }
            outcome = extract_for_document(doc_for_extract)
            inline_signals = outcome.get("signals") or []
            inline_err = outcome.get("error_message")
        except Exception as exc:  # noqa: BLE001 — ingest must never fail
            inline_err = f"{type(exc).__name__}: {exc}"

    return IngestResponse(
        document_id=document_id,
        author_id=author_id,
        detected_tickers=tickers,
        tags=sorted(tags),
        pending_vision=pending_vision,
        signals=inline_signals,
        inline_extraction_error=inline_err,
    )


# ── Listings for the /inbox history view ─────────────────────────────────────


def list_recent_inputs(limit: int = 50) -> list[dict]:
    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.row_factory = sqlite3.Row
        # ALLOWLIST: the "manual:" prefix has been hijacked by many
        # ingestion pipelines (gov-insider, lobbying, fed-spend, large-
        # holder SEC filings, social/StockTwits, etc). A blocklist can't
        # keep up — every new pipeline adds another bucket. Instead we
        # only return docs whose author_id matches one of the seeded
        # human namespaces (Feather Hands family, Stock Unlocked,
        # Forward Guidance, self, WOAS) or the archive baseline.
        # input_authors is the source of truth: seeded entries have
        # notes='seeded on first boot' or were upserted via the manual
        # ingest API.
        rows = connection.execute(
            """
            SELECT d.document_id, d.source_id, d.title, d.content_type,
                   d.ingested_at, d.published_at,
                   d.author, d.author_id, d.raw_text, d.cleaned_text,
                   d.attachment_path, d.attachment_paths_json,
                   d.user_metadata_json, d.tags_json, d.extracted_features_json
            FROM documents d
            INNER JOIN input_authors a ON a.author_id = d.author_id
            WHERE d.content_type IN ('manual_chart', 'manual_note')
              AND d.source_id LIKE 'manual:%'
              -- author must be a seeded human OR the archive baseline:
              AND (
                a.notes = 'seeded on first boot'
                OR a.channel = 'archive'
                OR a.author_id LIKE 'market-traders:%'
                OR a.author_id LIKE 'feather-hands:%'
                OR a.author_id LIKE 'stock-unlocked:%'
                OR a.author_id LIKE 'wolf-of-all-streets:%'
                OR a.author_id LIKE 'forward-guidance:%'
                -- The whole 'self:' namespace, not just the seeded
                -- 'self:me'. An author is only created there by someone
                -- posting through the manual ingest API with
                -- channel='self' — no scraper writes it (production has
                -- exactly one such author). Pinning to 'self:me' meant a
                -- note filed under any other display name vanished from
                -- history: ingest reported success, the row existed, and
                -- the list came back empty.
                OR a.author_id LIKE 'self:%'
                OR a.author_id LIKE 'archive:%'
              )
            ORDER BY COALESCE(d.published_at, d.ingested_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        d = dict(row)
        try:
            d["user_metadata"] = json.loads(d.pop("user_metadata_json") or "{}")
        except json.JSONDecodeError:
            d["user_metadata"] = {}
        try:
            d["tags"] = json.loads(d.pop("tags_json") or "{}")
        except json.JSONDecodeError:
            d["tags"] = {}
        # Hydrate the multi-image list. Older rows that predate
        # attachment_paths_json fall back to the singular attachment_path.
        try:
            paths = json.loads(d.pop("attachment_paths_json") or "[]")
        except json.JSONDecodeError:
            paths = []
        if not paths and d.get("attachment_path"):
            paths = [d["attachment_path"]]
        d["attachment_paths"] = paths
        # Surface extracted_features_json as a parsed dict for the SPA.
        try:
            d["extracted_features"] = json.loads(d.pop("extracted_features_json") or "null")
        except json.JSONDecodeError:
            d["extracted_features"] = None
        out.append(d)
    return out


# ── Attachment storage ───────────────────────────────────────────────────────


def save_attachment(file_bytes: bytes, original_filename: str) -> str:
    """Write an uploaded image under uploads/charts/YYYY-MM/{uuid}.{ext}.

    Returns the relative path (relative to settings.base_dir) to store in
    documents.attachment_path. The relative form survives base_dir moves
    between environments.
    """
    ext = Path(original_filename).suffix.lower() or ".bin"
    base = settings.chart_upload_dir
    today = datetime.now(UTC)
    sub = base / f"{today.year:04d}-{today.month:02d}"
    sub.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    abs_path = sub / name
    abs_path.write_bytes(file_bytes)
    rel = abs_path.relative_to(settings.base_dir)
    return str(rel)
