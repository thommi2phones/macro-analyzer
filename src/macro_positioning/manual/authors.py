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


# ── Seed authors ────────────────────────────────────────────────────────────
# The user's recurring set of trade-idea sources. Pre-seeded into the
# input_authors table on app boot so author_ids are stable across DBs and
# the /inbox dropdown is always populated even before the first submission.
# `channel` is the primary venue we expect to see them in; `channel_type`
# matches the SPA's pill set (self|telegram|discord|twitter|tradingview|other).
# Both can be overridden per-drop via the ManualMetadata form.
# Hierarchy: person → channel they post in → parent community.
# Example: Big_Nuts posts in the Market Traders chat, which sits inside the
# broader Feather Hands community. SPA shows this as a breadcrumb so
# attribution reads "Big_Nuts · Market Traders · Feather Hands".
SEED_AUTHORS: list[dict] = [
    # Feather Hands family — user's top source for direct trades AND
    # macro sentiment. trust_weight=1.5 means the scoring layer treats
    # mentions / signals from these authors with 1.5x weight vs an
    # unknown source. Categories drive theme-extraction grouping.
    # Big_Nuts, joejoe55, MadDog31 all RUN Feather Hands — they're the
    # parent-community operators, not Market-Traders-subgroup members.
    # Market Traders is a separate sub-group whose entity-level posts
    # (when OCR can't tag a specific person) are attributed below.
    {"display_name": "Big_Nuts",            "channel": "Feather Hands",       "channel_type": "telegram", "trust_weight": 1.5, "category": "direct_trades"},
    {"display_name": "MadDog31",            "channel": "Feather Hands",       "channel_type": "telegram", "trust_weight": 1.5, "category": "direct_trades"},
    {"display_name": "joejoe55",            "channel": "Feather Hands",       "channel_type": "telegram", "trust_weight": 1.5, "category": "both"},
    {"display_name": "Market Traders",      "channel": "Market Traders",     "channel_type": "telegram", "parent_channel": "Feather Hands", "trust_weight": 1.4, "category": "direct_trades"},
    # Stock Unlocked — high-trust direct trades source per user.
    {"display_name": "Artur Unlocked",      "channel": "Stock Unlocked",      "channel_type": "telegram",                                    "trust_weight": 1.5, "category": "direct_trades"},
    {"display_name": "Stock Unlocked",      "channel": "Stock Unlocked",      "channel_type": "telegram",                                    "trust_weight": 1.5, "category": "direct_trades"},
    # Self drops — by definition you trust them, but they're not an
    # external signal so weight stays at 1.0 (no extra amplification).
    # Highest trust — these are the user's own setups. Per user direction:
    # tw=2.0 so a self-drop weighs 2x any external signal in scoring.
    {"display_name": "Me",                  "channel": "self",                "channel_type": "self",                                        "trust_weight": 2.0, "category": "both"},
    # Macro sentiment sources — Forward Guidance (podcast) + WOAS (Wolf of
    # All Streets). Per user: Forward Guidance equals Feather Hands as a
    # top macro source. WOAS more variable.
    {"display_name": "Forward Guidance",    "channel": "Forward Guidance",    "channel_type": "other",                                       "trust_weight": 1.5, "category": "macro_sentiment"},
    {"display_name": "WOAS",                "channel": "Wolf of All Streets", "channel_type": "twitter",                                     "trust_weight": 1.1, "category": "macro_sentiment"},
    # Telegram channel-as-author entries. These are broadcast channels
    # (single author = the channel itself) fed by the telegram_poller
    # module. display_name == channel so the picker pill reads cleanly.
    # Ari Gold is a DM (1-on-1 private), not a channel — same poller
    # path, just filters to messages from the other side of the DM.
    {"display_name": "Feather Hands Trading", "channel": "Feather Hands Trading", "channel_type": "telegram", "trust_weight": 1.5, "category": "direct_trades"},
    {"display_name": "Gem Hunters 💎",         "channel": "Gem Hunters",          "channel_type": "telegram", "trust_weight": 1.5, "category": "direct_trades"},
    {"display_name": "🐳 OG Whales 🐳",        "channel": "OG Whales",            "channel_type": "telegram", "trust_weight": 1.3, "category": "direct_trades"},
    {"display_name": "The Wolf Pack",          "channel": "The Wolf Pack",        "channel_type": "telegram", "trust_weight": 1.3, "category": "direct_trades"},
    {"display_name": "Ari Gold",               "channel": "Ari Gold",             "channel_type": "telegram", "trust_weight": 1.4, "category": "direct_trades"},
    # New 2026-07-31 — active trade-call channel (charts + tickers + levels),
    # but some promotional/"portfolio" messaging, so it enters UNPROVEN at
    # tw=1.1 (barely above an unknown source). Raise once its call accuracy
    # is backtested and holds up. See [[project_conviction_author_allowlist]].
    {"display_name": "Trading Operation Desk", "channel": "Trading Operation Desk", "channel_type": "telegram", "trust_weight": 1.1, "category": "direct_trades"},
]


def seed_known_authors(*, db_path: Optional[Path] = None) -> int:
    """Idempotently insert the SEED_AUTHORS list into input_authors.

    Returns the number of rows actually inserted (0 on subsequent boots).
    Existing rows are NEVER updated — once a row exists we trust whatever
    the user has corrected in place. Called from initialize_database() so
    fresh DBs always have the full picklist.
    """
    db_path = db_path or settings.sqlite_path
    inserted = 0
    now_iso = datetime.now(UTC).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA busy_timeout=5000")
        for seed in SEED_AUTHORS:
            ref = AuthorRef(**seed)
            author_id = slugify_author(ref)
            existing = connection.execute(
                "SELECT 1 FROM input_authors WHERE author_id=?",
                (author_id,),
            ).fetchone()
            if existing:
                continue
            connection.execute(
                "INSERT INTO input_authors "
                "(author_id, display_name, channel, channel_type, "
                " parent_channel, trust_weight, category, "
                " notes, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    author_id,
                    seed["display_name"],
                    seed.get("channel"),
                    seed.get("channel_type"),
                    seed.get("parent_channel"),
                    seed.get("trust_weight"),
                    seed.get("category"),
                    "seeded on first boot",
                    now_iso,
                    now_iso,
                ),
            )
            inserted += 1
        connection.commit()
    return inserted


# ── Allowlist: "authors the user has explicitly stated" ─────────────────────
# Single source of truth for which authors count toward conviction /
# positioning. An input_authors row qualifies only if it was seeded (the
# SEED_AUTHORS list above) or lives under one of the seeded sub-author
# namespaces. Everything auto-ingested by the other pipelines — gov-insider,
# lobbying, social, fed-spend, large-holder, and any future additions — has a
# 'manual:'-prefixed namespace that matches NONE of these clauses and is
# therefore excluded. Per user direction: do not take any author except the
# ones we have explicitly stated into account.
#
# Referenced columns (notes, author_id) are unambiguous in any single-table
# FROM input_authors query; callers that alias the table should use the bare
# column names (only input_authors is in WHERE scope).
SEEDED_AUTHOR_WHERE = """
    notes = 'seeded on first boot'
    OR author_id LIKE 'market-traders:%'
    OR author_id LIKE 'feather-hands:%'
    OR author_id LIKE 'stock-unlocked:%'
    OR author_id LIKE 'wolf-of-all-streets:%'
    OR author_id LIKE 'forward-guidance:%'
    OR author_id = 'self:me'
"""


def seeded_author_ids(conn: sqlite3.Connection) -> set[str]:
    """The set of author_ids the user has explicitly stated as trusted voices.

    Conviction/positioning aggregation filters to this set so that
    auto-ingested authors (gov-insider, lobbying, social, fed-spend, unknown)
    never contribute to a conviction score or directional vote. Returns an
    empty set on any error so callers degrade to "nothing counts" rather than
    silently letting everything through.
    """
    try:
        rows = conn.execute(
            f"SELECT author_id FROM input_authors WHERE {SEEDED_AUTHOR_WHERE}"
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {r[0] for r in rows}


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
    """Recent authors with submission counts. Feeds the SPA autocomplete.

    Also returns `parent_channel` so the SPA can render the full
    person → channel → community breadcrumb when present.
    """
    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.row_factory = sqlite3.Row
        # ALLOWLIST: only return seeded authors (SEEDED_AUTHOR_WHERE — the
        # single source of truth). Every other ingestion pipeline
        # (gov-insider, lobbying, fed-spend, large-holder, social, plus any
        # future additions) is filtered out by NOT matching a seeded
        # namespace. The WHERE references bare column names because only
        # input_authors is in scope there (the documents subquery is in
        # SELECT, not WHERE).
        rows = connection.execute(
            f"""
            SELECT a.author_id, a.display_name, a.channel, a.channel_type,
                   a.parent_channel,
                   a.first_seen_at, a.last_seen_at,
                   COALESCE(a.trust_weight, 1.0) AS trust_weight,
                   a.category,
                   (SELECT COUNT(*) FROM documents d
                    WHERE d.author_id=a.author_id
                      AND d.content_type IN ('manual_chart','manual_note')
                   ) AS submission_count
            FROM input_authors a
            WHERE {SEEDED_AUTHOR_WHERE}
            ORDER BY
              COALESCE(a.trust_weight, 1.0) DESC,
              a.last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
