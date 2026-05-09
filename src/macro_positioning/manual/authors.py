"""Author/channel attribution helpers for the manual input layer.

A manual drop carries an `AuthorRef` (display_name + channel). We slug it
into a stable `author_id` and upsert into `input_authors`. Future per-author
hit-rate tracking joins on `author_id`.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from macro_positioning.core.settings import settings
from macro_positioning.manual.models import AuthorRef


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    cleaned = _SLUG_NON_ALNUM.sub("-", (text or "").strip().lower()).strip("-")
    return cleaned or "anon"


def slugify_author(ref: AuthorRef) -> str:
    """Stable id from channel + display_name.

    Same author posting in the same channel always lands on the same slug.
    Format: ``{channel-slug}:{display-slug}`` (e.g. ``bwatch-chat:capo``).
    """
    return f"{slugify(ref.channel or 'self')}:{slugify(ref.display_name)}"


def upsert_author(ref: AuthorRef, *, db_path: Optional[Path] = None) -> str:
    """Insert or touch an author row. Returns the author_id slug.

    Updates `last_seen_at` on every call. Sets `first_seen_at` on initial
    insert. Display-name and channel-type updates flow through if the
    caller passes them, but a missing field never overwrites an existing one.
    """
    db_path = db_path or settings.sqlite_path
    author_id = slugify_author(ref)
    now_iso = datetime.now(UTC).isoformat()

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA busy_timeout=5000")
        existing = connection.execute(
            "SELECT author_id, display_name, channel, channel_type, notes "
            "FROM input_authors WHERE author_id=?",
            (author_id,),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO input_authors "
                "(author_id, display_name, channel, channel_type, notes, "
                " first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    author_id,
                    ref.display_name,
                    ref.channel,
                    ref.channel_type,
                    ref.notes,
                    now_iso,
                    now_iso,
                ),
            )
        else:
            display = ref.display_name or existing[1]
            channel = ref.channel or existing[2]
            channel_type = ref.channel_type or existing[3]
            notes = ref.notes or existing[4]
            connection.execute(
                "UPDATE input_authors "
                "SET display_name=?, channel=?, channel_type=?, notes=?, last_seen_at=? "
                "WHERE author_id=?",
                (display, channel, channel_type, notes, now_iso, author_id),
            )
        connection.commit()
    return author_id


def find_author_id(display_name: str, channel: Optional[str]) -> Optional[str]:
    """Look up an existing author_id by display_name + channel without
    creating a new row. Used by the /preview endpoint to suggest matches."""
    if not display_name:
        return None
    candidate = slugify_author(AuthorRef(display_name=display_name, channel=channel))
    with sqlite3.connect(settings.sqlite_path) as connection:
        row = connection.execute(
            "SELECT author_id FROM input_authors WHERE author_id=?",
            (candidate,),
        ).fetchone()
    return row[0] if row else None


def list_authors(limit: int = 200) -> list[dict]:
    """Recent authors with submission counts. Feeds the SPA autocomplete."""
    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT a.author_id, a.display_name, a.channel, a.channel_type,
                   a.first_seen_at, a.last_seen_at,
                   (SELECT COUNT(*) FROM documents d WHERE d.author_id=a.author_id) AS submission_count
            FROM input_authors a
            ORDER BY a.last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
