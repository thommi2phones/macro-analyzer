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


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.commit()
