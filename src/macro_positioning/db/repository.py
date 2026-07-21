from __future__ import annotations

import functools
import json
import sqlite3
from pathlib import Path

from macro_positioning.core.models import NormalizedDocument, PositioningMemo, Thesis


@functools.lru_cache(maxsize=1)
def _gmail_newsletter_slugs() -> frozenset[str]:
    """Bare source_ids that arrive via the Gmail newsletter path.

    Lazily imported + cached so repository has no hard dependency on the
    Gmail optional-deps stack. Used to detect Substack publications that can
    arrive through BOTH Gmail (bare slug) and the Substack RSS connector
    (`substack:{slug}`), so the same post isn't ingested twice.
    """
    try:
        from macro_positioning.ingestion.gmail_connector import NEWSLETTER_SOURCES
        return frozenset(s.source_id for s in NEWSLETTER_SOURCES)
    except Exception:
        return frozenset()


def _cross_path_duplicate(
    connection: sqlite3.Connection, document: NormalizedDocument
) -> bool:
    """True if this newsletter post already exists under the *other* path.

    Substack publications can land via Gmail (`doomberg`) and the Substack
    RSS connector (`substack:doomberg`). Both carry the same title +
    published_at, so we dedupe on (canonical publication, title,
    published_at) — scoped to the two known source_id variants so distinct
    publications (and same-title-different-date episodes) never collide.
    """
    source_id = document.source_id
    canonical = source_id[len("substack:"):] if source_id.startswith("substack:") else source_id
    # Only newsletter-class sources are at risk; skip manual/news/insiders/etc.
    if not (source_id.startswith("substack:") or canonical in _gmail_newsletter_slugs()):
        return False
    variants = (canonical, f"substack:{canonical}")
    row = connection.execute(
        """
        SELECT 1 FROM documents
        WHERE title = ? AND published_at = ?
          AND source_id IN (?, ?)
          AND document_id != ?
        LIMIT 1
        """,
        (document.title, document.published_at.isoformat(),
         variants[0], variants[1], document.document_id),
    ).fetchone()
    return row is not None


class SQLiteRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def save_document(self, document: NormalizedDocument) -> bool:
        """Persist a document. Returns True if inserted, False if deduped.

        Uses INSERT OR IGNORE so re-ingesting the same (source_id, url) is
        a no-op rather than clobbering existing rows (including their
        original ingested_at timestamp).
        """
        with self._connect() as connection:
            # Cross-path dedupe: the same Substack post can arrive via Gmail
            # AND the Substack RSS connector under different source_ids. Drop
            # the second copy so signals don't double-count.
            if _cross_path_duplicate(connection, document):
                return False
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO documents (
                    document_id, source_id, title, url, published_at, author, author_id,
                    content_type, raw_text, cleaned_text, tags_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.source_id,
                    document.title,
                    document.url,
                    document.published_at.isoformat(),
                    document.author,
                    document.author_id,
                    document.content_type,
                    document.raw_text,
                    document.cleaned_text,
                    json.dumps(document.tags),
                    document.ingested_at.isoformat(),
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def save_thesis(self, thesis: Thesis) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO theses (
                    thesis_id, thesis, theme, horizon, direction, assets_json, catalysts_json,
                    risks_json, implied_positioning_json, confidence, freshness_score, status,
                    source_ids_json, evidence_json, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thesis.thesis_id,
                    thesis.thesis,
                    thesis.theme,
                    thesis.horizon,
                    thesis.direction.value,
                    json.dumps(thesis.assets),
                    json.dumps(thesis.catalysts),
                    json.dumps(thesis.risks),
                    json.dumps(thesis.implied_positioning),
                    thesis.confidence,
                    thesis.freshness_score,
                    thesis.status.value,
                    json.dumps(thesis.source_ids),
                    thesis.model_dump_json(indent=None, include={"evidence"}),
                    thesis.extracted_at.isoformat(),
                ),
            )
            connection.commit()

    def save_memo(self, memo: PositioningMemo) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO memos (
                    memo_id, title, generated_at, summary, consensus_views_json, divergent_views_json,
                    suggested_positioning_json, risks_to_watch_json, thesis_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memo.memo_id,
                    memo.title,
                    memo.generated_at.isoformat(),
                    memo.summary,
                    json.dumps(memo.consensus_views),
                    json.dumps(memo.divergent_views),
                    json.dumps(memo.suggested_positioning),
                    json.dumps(memo.risks_to_watch),
                    json.dumps(memo.thesis_ids),
                ),
            )
            connection.commit()

    def list_theses(self) -> list[Thesis]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM theses ORDER BY extracted_at DESC").fetchall()
        return [self._row_to_thesis(row) for row in rows]

    def latest_memo(self) -> PositioningMemo | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memos ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._row_to_memo(row)

    @staticmethod
    def _row_to_thesis(row: sqlite3.Row) -> Thesis:
        evidence_payload = json.loads(row["evidence_json"]).get("evidence", [])
        return Thesis.model_validate(
            {
                "thesis_id": row["thesis_id"],
                "thesis": row["thesis"],
                "theme": row["theme"],
                "horizon": row["horizon"],
                "direction": row["direction"],
                "assets": json.loads(row["assets_json"]),
                "catalysts": json.loads(row["catalysts_json"]),
                "risks": json.loads(row["risks_json"]),
                "implied_positioning": json.loads(row["implied_positioning_json"]),
                "confidence": row["confidence"],
                "freshness_score": row["freshness_score"],
                "status": row["status"],
                "source_ids": json.loads(row["source_ids_json"]),
                "evidence": evidence_payload,
                "extracted_at": row["extracted_at"],
            }
        )

    @staticmethod
    def _row_to_memo(row: sqlite3.Row) -> PositioningMemo:
        return PositioningMemo.model_validate(
            {
                "memo_id": row["memo_id"],
                "title": row["title"],
                "generated_at": row["generated_at"],
                "summary": row["summary"],
                "consensus_views": json.loads(row["consensus_views_json"]),
                "divergent_views": json.loads(row["divergent_views_json"]),
                "suggested_positioning": json.loads(row["suggested_positioning_json"]),
                "risks_to_watch": json.loads(row["risks_to_watch_json"]),
                "thesis_ids": json.loads(row["thesis_ids_json"]),
            }
        )
