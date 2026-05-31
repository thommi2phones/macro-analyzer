"""Pending-vision drainer — turns pending_vision=true documents into
extracted_features_json by calling analyze_manual_chart() on each
attachment, then clearing the flag.

Designed to be cheap to re-run (each pass picks up new pending rows) and
safe to interrupt — partial work is committed per-document. Intended to
run on a cron, on demand from the SPA, or as a background task on save.

Usage:
    from macro_positioning.manual.vision_drainer import drain
    summary = drain()                # process all pending
    summary = drain(limit=10)        # batch
    summary = drain(document_id="x") # single doc
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Optional

from macro_positioning.core.settings import settings
from macro_positioning.manual.vision import analyze_manual_chart


logger = logging.getLogger(__name__)


@dataclass
class DrainerSummary:
    candidates: int = 0      # rows seen (pending_vision=true)
    processed: int = 0       # successfully analyzed
    skipped_no_image: int = 0
    failed: int = 0          # analyze returned {"error": ...}

    def to_dict(self) -> dict:
        return asdict(self)


def _pending_query(document_id: Optional[str], limit: int) -> tuple[str, tuple]:
    """Build the SELECT for pending docs.

    `pending_vision` is stored inside `tags_json` (JSON1 extract).
    `attachment_paths_json` is the source of truth for image paths;
    `attachment_path` is the back-compat single-image fallback.
    """
    base = (
        "SELECT document_id, attachment_path, attachment_paths_json, tags_json "
        "FROM documents "
        "WHERE json_extract(tags_json, '$.pending_vision') = 1 "
    )
    if document_id:
        return (base + " AND document_id = ?", (document_id,))
    return (base + " ORDER BY ingested_at ASC LIMIT ?", (limit,))


def _resolve_paths(attachment_path: Optional[str], paths_json: Optional[str]) -> list[str]:
    if paths_json:
        try:
            paths = json.loads(paths_json)
            if isinstance(paths, list) and paths:
                return [str(p) for p in paths]
        except json.JSONDecodeError:
            pass
    return [attachment_path] if attachment_path else []


def _merge_results(per_image: list[dict]) -> dict:
    """Merge multiple per-image TradeRecord results from one document.

    Strategy: take the first non-error result as the base, then carry over
    any non-null fields from subsequent results that the base left null.
    Fields like `key_levels` (list) are unioned. Always include the full
    per-image breakdown under `_images` for auditability.
    """
    cleans = [r for r in per_image if "error" not in r]
    if not cleans:
        return {"error": "all images failed", "_images": per_image}

    base = dict(cleans[0])
    for extra in cleans[1:]:
        for k, v in extra.items():
            if v is None:
                continue
            cur = base.get(k)
            if cur is None:
                base[k] = v
            elif isinstance(cur, list) and isinstance(v, list):
                # Stable de-dup, preserve order
                merged = list(cur)
                for x in v:
                    if x not in merged:
                        merged.append(x)
                base[k] = merged
    base["_images"] = per_image
    base["_merged_at"] = datetime.now(UTC).isoformat()
    return base


def drain(
    *,
    document_id: Optional[str] = None,
    limit: int = 25,
) -> DrainerSummary:
    """Process pending_vision documents. Returns counts."""
    summary = DrainerSummary()
    sql, params = _pending_query(document_id, limit)
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    summary.candidates = len(rows)
    if not rows:
        return summary

    for row in rows:
        doc_id = row["document_id"]
        paths = _resolve_paths(row["attachment_path"], row["attachment_paths_json"])
        if not paths:
            summary.skipped_no_image += 1
            _clear_pending(doc_id, error="no_attachment")
            continue

        per_image = [analyze_manual_chart(p) for p in paths]
        merged = _merge_results(per_image)

        if "error" in merged:
            summary.failed += 1
            _store_result(doc_id, merged, clear_pending=False)
            continue

        _store_result(doc_id, merged, clear_pending=True)
        summary.processed += 1

    return summary


def _store_result(document_id: str, result: dict, *, clear_pending: bool) -> None:
    """Write extracted_features_json + (optionally) flip pending_vision off."""
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        if clear_pending:
            # Patch tags_json with json_set so we don't blow away other keys.
            conn.execute(
                """
                UPDATE documents SET
                  extracted_features_json = ?,
                  tags_json = json_set(tags_json, '$.pending_vision', json('false'))
                WHERE document_id = ?
                """,
                (json.dumps(result), document_id),
            )
        else:
            conn.execute(
                "UPDATE documents SET extracted_features_json = ? WHERE document_id = ?",
                (json.dumps(result), document_id),
            )
        conn.commit()


def _clear_pending(document_id: str, *, error: str) -> None:
    """Mark a doc done with an explanatory note (no image to analyze)."""
    payload = {"error": error, "skipped_at": datetime.now(UTC).isoformat()}
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            UPDATE documents SET
              extracted_features_json = ?,
              tags_json = json_set(tags_json, '$.pending_vision', json('false'))
            WHERE document_id = ?
            """,
            (json.dumps(payload), document_id),
        )
        conn.commit()
