"""Persistence for Signal rows + extraction attempts.

All DB access for the signals layer lives here so extractors stay
storage-agnostic and tests can swap in a temp DB path.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Optional

from macro_positioning.core.settings import settings
from macro_positioning.signals.base import (
    ExtractionResult,
    Signal,
    SignalSide,
    SignalStatus,
)


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = db_path or settings.sqlite_path
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ── Writes ──────────────────────────────────────────────────────────────────


def insert_signal(signal: Signal, *, db_path: Optional[Path] = None) -> str:
    """Insert one Signal. Returns signal_id. Idempotent on PK conflict."""
    if signal.weighted_score is None:
        signal.weighted_score = signal.compute_weighted_score()

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO signals (
                signal_id, document_id, extracted_at, extraction_run_id,
                asset_ticker, asset_class, secondary_tickers_json, instrument_detail_json,
                side, conviction, conviction_raw,
                position_size_hint, position_size_unit, horizon, horizon_days,
                entry_zone_low, entry_zone_high, stop_loss, target_1, target_2, invalidation,
                thesis_summary, thesis_tags_json, macro_regime_tags_json,
                catalyst_type, catalyst_date, catalyst_summary,
                source_slug, source_channel, author_id,
                author_trust_weight, source_trust_weight,
                extractor_name, extractor_version, extractor_confidence,
                model_provider, model_name, raw_excerpt, extraction_call_id,
                status, expires_at, superseded_by, weighted_score,
                latency_ms, input_tokens, output_tokens, cost_usd, error_message
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                signal.signal_id, signal.document_id, signal.extracted_at,
                signal.extraction_run_id,
                signal.asset_ticker, signal.asset_class,
                json.dumps(signal.secondary_tickers) if signal.secondary_tickers else None,
                json.dumps(signal.instrument_detail) if signal.instrument_detail else None,
                signal.side.value, signal.conviction, signal.conviction_raw,
                signal.position_size_hint, signal.position_size_unit,
                signal.horizon.value if signal.horizon else None,
                signal.horizon_days,
                signal.entry_zone_low, signal.entry_zone_high,
                signal.stop_loss, signal.target_1, signal.target_2,
                signal.invalidation,
                signal.thesis_summary,
                json.dumps(signal.thesis_tags) if signal.thesis_tags else None,
                json.dumps(signal.macro_regime_tags) if signal.macro_regime_tags else None,
                signal.catalyst_type.value if signal.catalyst_type else None,
                signal.catalyst_date, signal.catalyst_summary,
                signal.source_slug, signal.source_channel, signal.author_id,
                signal.author_trust_weight, signal.source_trust_weight,
                signal.extractor_name, signal.extractor_version,
                signal.extractor_confidence,
                signal.model_provider, signal.model_name,
                signal.raw_excerpt, signal.extraction_call_id,
                signal.status.value, signal.expires_at, signal.superseded_by,
                signal.weighted_score,
                signal.latency_ms, signal.input_tokens, signal.output_tokens,
                signal.cost_usd, signal.error_message,
            ),
        )
        conn.commit()
    return signal.signal_id


def insert_signals(signals: Iterable[Signal], *, db_path: Optional[Path] = None) -> int:
    count = 0
    for s in signals:
        insert_signal(s, db_path=db_path)
        count += 1
    return count


def record_attempt(
    result: ExtractionResult,
    *,
    db_path: Optional[Path] = None,
) -> str:
    """Log an extraction attempt regardless of outcome."""
    attempt_id = uuid.uuid4().hex
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO signal_extraction_attempts (
                attempt_id, document_id, attempted_at,
                extractor_name, extractor_version,
                status, error_message, signals_produced, latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                result.document_id,
                datetime.now(UTC).isoformat(),
                result.extractor_name,
                result.extractor_version,
                result.status,
                result.error_message,
                len(result.signals),
                result.latency_ms,
            ),
        )
        conn.commit()
    return attempt_id


# ── Reads ───────────────────────────────────────────────────────────────────


def pending_documents(
    *,
    limit: int = 200,
    since_days: int = 30,
    extractor_name: Optional[str] = None,
    current_extractor_versions: Optional[dict[str, str]] = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Documents that have not yet been successfully extracted.

    A document is pending if EITHER:
      - There is no `signal_extraction_attempts` row for it with status
        in (success, no_signal) — never extracted OR every attempt errored.
      - The latest successful attempt was at an extractor_version older
        than the currently-registered version (re-extraction policy).

    Args:
      extractor_name: if set, scope the check to one extractor (so the
        LLM extractor doesn't skip docs that only had an insider attempt).
      current_extractor_versions: map of {extractor_name: latest_version}.
        Used for re-extraction. When None, the version check is skipped
        and only "never attempted" docs are considered pending.
    """
    where_extractor = "AND a.extractor_name = ?" if extractor_name else ""
    params: list = []
    if extractor_name:
        params.append(extractor_name)
    params.extend([since_days, limit])

    sql = f"""
        SELECT d.document_id, d.source_id, d.title, d.published_at,
               d.author, d.author_id, d.content_type, d.raw_text, d.cleaned_text,
               d.tags_json, d.user_metadata_json, d.attachment_paths_json,
               d.url
        FROM documents d
        WHERE NOT EXISTS (
            SELECT 1 FROM signal_extraction_attempts a
            WHERE a.document_id = d.document_id
              AND a.status IN ('success', 'no_signal')
              {where_extractor}
        )
        AND d.ingested_at >= datetime('now', '-' || ? || ' days')
        ORDER BY d.ingested_at DESC
        LIMIT ?
    """
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        pending = [dict(r) for r in rows]

        # Re-extraction surface: docs whose latest attempt for the named
        # extractor used an older version than the currently-registered one.
        if current_extractor_versions:
            seen_ids = {r["document_id"] for r in pending}
            for ex_name, current_ver in current_extractor_versions.items():
                if extractor_name and ex_name != extractor_name:
                    continue
                version_rows = conn.execute(
                    """
                    SELECT d.document_id, d.source_id, d.title, d.published_at,
                           d.author, d.author_id, d.content_type, d.raw_text,
                           d.cleaned_text, d.tags_json, d.user_metadata_json,
                           d.attachment_paths_json, d.url
                    FROM documents d
                    JOIN (
                        SELECT document_id, MAX(attempted_at) AS last_at
                        FROM signal_extraction_attempts
                        WHERE extractor_name = ?
                          AND status IN ('success', 'no_signal')
                        GROUP BY document_id
                    ) latest ON latest.document_id = d.document_id
                    JOIN signal_extraction_attempts a
                      ON a.document_id = latest.document_id
                     AND a.attempted_at = latest.last_at
                     AND a.extractor_name = ?
                    WHERE a.extractor_version != ?
                      AND d.ingested_at >= datetime('now', '-' || ? || ' days')
                    ORDER BY d.ingested_at DESC
                    LIMIT ?
                    """,
                    (ex_name, ex_name, current_ver, since_days, limit),
                ).fetchall()
                for r in version_rows:
                    d = dict(r)
                    if d["document_id"] not in seen_ids:
                        d["_reextract_for"] = ex_name
                        d["_old_version"] = None  # filled below if needed
                        pending.append(d)
                        seen_ids.add(d["document_id"])

        return pending[:limit]


def load_active_signals_for_ticker(
    ticker: str,
    *,
    since_days: int = 90,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """All active signals for a ticker within the lookback window.

    Composer consumes this to build per-asset positioning bias.
    """
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE asset_ticker = ?
              AND status = 'active'
              AND extracted_at >= datetime('now', '-' || ? || ' days')
            ORDER BY extracted_at DESC
            """,
            (ticker.upper(), since_days),
        ).fetchall()
    return [dict(r) for r in rows]


def load_recent_signals(
    *,
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> list[dict]:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT signal_id, document_id, extracted_at, asset_ticker,
                   side, conviction, source_slug, extractor_name,
                   thesis_summary, weighted_score, status
            FROM signals
            ORDER BY extracted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def signal_counts_by_extractor(
    *, db_path: Optional[Path] = None
) -> list[dict]:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT extractor_name, COUNT(*) AS n,
                   AVG(conviction) AS avg_conviction,
                   MAX(extracted_at) AS latest
            FROM signals
            GROUP BY extractor_name
            ORDER BY n DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def expire_stale_signals(
    *, db_path: Optional[Path] = None
) -> int:
    """Mark expired signals where expires_at < now."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE signals
            SET status = 'expired'
            WHERE status = 'active'
              AND expires_at IS NOT NULL
              AND expires_at < ?
            """,
            (datetime.now(UTC).isoformat(),),
        )
        conn.commit()
    return cur.rowcount or 0
