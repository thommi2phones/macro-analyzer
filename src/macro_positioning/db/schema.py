from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        published_at TEXT NOT NULL,
        author TEXT,
        content_type TEXT NOT NULL,
        raw_text TEXT NOT NULL,
        cleaned_text TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        ingested_at TEXT NOT NULL
    )
    """,
    # Dedup: two documents from the same source with the same URL are the
    # same story. NULL urls don't collide under SQLite's unique semantics,
    # so untitled/url-less sources still dedupe via their document_id PK.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_url
        ON documents (source_id, url)
        WHERE url IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS theses (
        thesis_id TEXT PRIMARY KEY,
        thesis TEXT NOT NULL,
        theme TEXT NOT NULL,
        horizon TEXT NOT NULL,
        direction TEXT NOT NULL,
        assets_json TEXT NOT NULL,
        catalysts_json TEXT NOT NULL,
        risks_json TEXT NOT NULL,
        implied_positioning_json TEXT NOT NULL,
        confidence REAL NOT NULL,
        freshness_score REAL NOT NULL,
        status TEXT NOT NULL,
        source_ids_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        extracted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memos (
        memo_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        summary TEXT NOT NULL,
        consensus_views_json TEXT NOT NULL,
        divergent_views_json TEXT NOT NULL,
        suggested_positioning_json TEXT NOT NULL,
        risks_to_watch_json TEXT NOT NULL,
        thesis_ids_json TEXT NOT NULL
    )
    """,
]


def _dedupe_existing_documents(connection: sqlite3.Connection) -> int:
    """Remove duplicate (source_id, url) rows keeping the earliest ingested_at.

    Called before creating the unique index so upgrades on databases that
    accumulated duplicates under the old INSERT OR REPLACE path don't fail.
    """
    # Only runs if the documents table already exists.
    table_exists = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    if not table_exists:
        return 0

    cursor = connection.execute(
        """
        DELETE FROM documents
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM documents
            WHERE url IS NOT NULL
            GROUP BY source_id, url
        )
        AND url IS NOT NULL
        """
    )
    return cursor.rowcount or 0


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        # Create base tables first (documents must exist before dedupe).
        connection.execute(SCHEMA_STATEMENTS[0])
        # Dedupe any pre-existing duplicates before the unique index lands.
        _dedupe_existing_documents(connection)
        for statement in SCHEMA_STATEMENTS[1:]:
            connection.execute(statement)
        connection.commit()
