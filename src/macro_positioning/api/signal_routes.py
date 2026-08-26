"""Signal provenance API — "where did this signal come from?"

Endpoint:
  - GET /api/signals/{signal_id}/provenance

The Live-signals panel on /positioning renders one card per row of the
`signals` table. Those cards are the tip of a chain:

    source channel → author → document (caption + chart images)
      → extractor (+ model) → signal (levels, conviction, thesis)

This endpoint returns that whole chain for one signal so the SPA can open
a drill-down: the chart image the call was read off, the raw caption /
excerpt the extractor saw, the model's structured features, and every
other signal that came out of the same document.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from macro_positioning.core.settings import settings


router = APIRouter(prefix="/api/signals", tags=["signals"])


def _loads(raw: Any) -> Any:
    """Parse a JSON column, tolerating NULL and legacy garbage."""
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _media_url(path: Optional[str]) -> Optional[str]:
    """Map a stored attachment path to a URL the SPA can load.

    `uploads/` and `manual_entry/` are both mounted at the app root
    (see api/main.py); anything already absolute is passed through.
    """
    if not path:
        return None
    p = str(path).strip()
    if not p:
        return None
    if p.startswith(("http://", "https://", "/")):
        return p
    if p.startswith(("uploads/", "manual_entry/")):
        return "/" + p
    return "/" + p.lstrip("./")


def _telegram_link(tags: Any) -> Optional[str]:
    """Build a t.me deep link from the poller's message key.

    Keys look like "-1001309918571:173064" (chat_id:message_id). The
    /c/ form resolves for any channel the user is a member of, which is
    every channel we poll.
    """
    if not isinstance(tags, dict):
        return None
    keys = tags.get("telegram_message_keys") or []
    if not isinstance(keys, list) or not keys:
        return None
    try:
        chat_id, msg_id = str(keys[0]).split(":", 1)
    except ValueError:
        return None
    chat_id = chat_id.lstrip("-")
    if chat_id.startswith("100"):
        chat_id = chat_id[3:]
    if not (chat_id.isdigit() and msg_id.isdigit()):
        return None
    return f"https://t.me/c/{chat_id}/{msg_id}"


def _images(doc: sqlite3.Row, conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """All chart images attached to the document, de-duplicated, in order.

    Three historical storage shapes feed this: the newer
    `attachment_paths_json` list, the original single `attachment_path`
    column, and the `manual_chart_attachments` side table (which carries
    per-image timeframe/role metadata).
    """
    out: list[dict] = []
    seen: set[str] = set()

    def _add(path: Optional[str], **meta: Any) -> None:
        url = _media_url(path)
        if not url or url in seen:
            return
        seen.add(url)
        out.append({"url": url, **{k: v for k, v in meta.items() if v is not None}})

    for p in (_loads(doc["attachment_paths_json"]) or []):
        _add(p if isinstance(p, str) else None)
    _add(doc["attachment_path"])

    try:
        rows = conn.execute(
            """
            SELECT attachment_path, timeframe, role, note
            FROM manual_chart_attachments
            WHERE document_id = ?
            ORDER BY order_index
            """,
            (document_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        _add(r["attachment_path"], timeframe=r["timeframe"], role=r["role"], note=r["note"])
    return out


# Column list kept explicit so a schema addition can't silently change the
# payload shape the SPA renders.
_SIGNAL_COLS = """
    signal_id, document_id, extracted_at, extraction_run_id,
    asset_ticker, asset_class, secondary_tickers_json, instrument_detail_json,
    side, conviction, conviction_raw, position_size_hint, position_size_unit,
    horizon, horizon_days,
    entry_zone_low, entry_zone_high, stop_loss, target_1, target_2, invalidation,
    thesis_summary, thesis_tags_json, macro_regime_tags_json,
    catalyst_type, catalyst_date, catalyst_summary,
    source_slug, source_channel, author_id,
    author_trust_weight, source_trust_weight,
    extractor_name, extractor_version, extractor_confidence,
    model_provider, model_name, raw_excerpt, extraction_call_id,
    status, expires_at, superseded_by, weighted_score
"""


@router.get("/{signal_id}/provenance")
def signal_provenance(signal_id: str) -> dict:
    """Full derivation chain behind one live signal."""
    if not settings.sqlite_path.exists():
        raise HTTPException(status_code=404, detail="database not available")

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            sig = conn.execute(
                f"SELECT {_SIGNAL_COLS} FROM signals WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            raise HTTPException(status_code=404, detail="signals table not present")
        if sig is None:
            raise HTTPException(status_code=404, detail="unknown signal")

        document_id = sig["document_id"]
        doc = conn.execute(
            """
            SELECT document_id, source_id, title, url, published_at, ingested_at,
                   author, author_id, content_type, cleaned_text, raw_text,
                   tags_json, user_metadata_json,
                   attachment_path, attachment_paths_json, extracted_features_json
            FROM documents WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()

        author = None
        if sig["author_id"]:
            author = conn.execute(
                """
                SELECT author_id, display_name, channel, channel_type,
                       parent_channel, trust_weight, category, notes,
                       first_seen_at, last_seen_at
                FROM input_authors WHERE author_id = ?
                """,
                (sig["author_id"],),
            ).fetchone()

        siblings = conn.execute(
            """
            SELECT signal_id, asset_ticker, side, conviction, weighted_score,
                   status, thesis_summary
            FROM signals
            WHERE document_id = ? AND signal_id != ?
            ORDER BY weighted_score DESC NULLS LAST, asset_ticker
            LIMIT 12
            """,
            (document_id, signal_id),
        ).fetchall()

        trust = None
        if sig["source_channel"]:
            try:
                trust = conn.execute(
                    """
                    SELECT source_channel, trust_weight, n_signals, n_trades_linked,
                           n_hits, precision, avg_pnl_pct, last_updated_at
                    FROM source_trust_weights WHERE source_channel = ?
                    """,
                    (sig["source_channel"],),
                ).fetchone()
            except sqlite3.OperationalError:
                trust = None

        images = _images(doc, conn, document_id) if doc is not None else []

    signal: dict[str, Any] = {k: sig[k] for k in sig.keys()}
    for col in ("secondary_tickers_json", "instrument_detail_json",
                "thesis_tags_json", "macro_regime_tags_json"):
        signal[col.removesuffix("_json")] = _loads(signal.pop(col))

    document: Optional[dict[str, Any]] = None
    features = None
    if doc is not None:
        tags = _loads(doc["tags_json"])
        user_meta = _loads(doc["user_metadata_json"])
        features = _loads(doc["extracted_features_json"])
        # Telegram chart forwards carry an empty body — the caption, when
        # there is one, is what the extractor actually read.
        text = (doc["cleaned_text"] or doc["raw_text"] or "").strip()
        document = {
            "document_id": doc["document_id"],
            "source_id": doc["source_id"],
            "title": doc["title"],
            "url": doc["url"],
            "published_at": doc["published_at"],
            "ingested_at": doc["ingested_at"],
            "author": doc["author"],
            "content_type": doc["content_type"],
            "text": text[:4000],
            "text_truncated": len(text) > 4000,
            "tags": tags,
            "channel": (user_meta or {}).get("channel") if isinstance(user_meta, dict) else None,
            "channel_type": (user_meta or {}).get("channel_type") if isinstance(user_meta, dict) else None,
            "telegram_link": _telegram_link(tags),
            "images": images,
        }

    return {
        "signal": signal,
        "document": document,
        "features": features,
        "author": {k: author[k] for k in author.keys()} if author is not None else None,
        "source_trust": {k: trust[k] for k in trust.keys()} if trust is not None else None,
        "siblings": [{k: r[k] for k in r.keys()} for r in siblings],
    }
