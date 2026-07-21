"""Scraper protocol + shared dataclasses for the insiders package.

Every source-specific module (house_ptr, sec_form4, lda, ...) implements
the `Scraper` protocol and yields `ScrapedEvent` objects. The shared
`ingest.funnel()` does the rest — author upsert, payload build,
`processor.ingest()` call, cursor update — so individual scrapers contain
only source-specific parsing logic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Optional, Protocol

from macro_positioning.core.settings import settings


# ── Event shape ─────────────────────────────────────────────────────────────


@dataclass
class ScrapedEvent:
    """One disclosure row, source-agnostic.

    `actor_name` is whoever directly held/transacted the position (could
    be a spouse, trust, etc.). `principal_name` is the disclosing principal
    — the Congress member or Section-16 filer the row attributes to. For
    self-trades they're equal.

    `edges` is empty for most sources; the LDA scraper populates it with
    `(from_node, to_node, edge_kind, amount_usd)` tuples that feed the
    lobbying graph table.
    """

    source_slug: str             # "house", "senate", "form4", "lda", ...
    channel: str                 # "gov_insider", "corp_insider", "fed_spend",
                                 # "lobbying", "large_holder", "social"
    external_id: str             # source-unique id, used for incremental cursors
    filed_at: str                # ISO date string
    actor_name: str
    principal_name: str
    actor_relationship: str      # self|spouse|dependent|trust|llc|family_other|
                                 # director|officer|10pct_owner|registrant|client
    tickers: list[str] = field(default_factory=list)
    amount_range: Optional[str] = None    # "$1,001 - $15,000" verbatim from PTRs
    transaction_type: Optional[str] = None  # purchase|sale|exchange|new|grown|exited
    raw_text: str = ""
    source_url: Optional[str] = None
    attachment_url: Optional[str] = None
    edges: list[tuple[str, str, str, Optional[float]]] = field(default_factory=list)

    def infer_side(self) -> Optional[str]:
        """Map transaction_type to the ManualMetadata side enum."""
        if not self.transaction_type:
            return None
        t = self.transaction_type.lower()
        if any(k in t for k in ("purchase", "buy", "new", "grown")):
            return "LONG"
        if any(k in t for k in ("sale", "sell", "exited")):
            # Sells are noisy (taxes, 10b5-1) → WATCH not SHORT.
            return "WATCH"
        return "WATCH"


# ── Scraper protocol ────────────────────────────────────────────────────────


class Scraper(Protocol):
    source_slug: str
    channel: str

    def fetch_since(self, cursor: Optional[str]) -> Iterable[ScrapedEvent]:
        """Yield events newer than `cursor` (last_external_id)."""
        ...


# ── Cursor table I/O ────────────────────────────────────────────────────────


def get_cursor(source_slug: str, *, db_path: Optional[Path] = None) -> Optional[str]:
    db_path = db_path or settings.sqlite_path
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute(
            "SELECT last_external_id FROM insiders_cursor WHERE source_slug=?",
            (source_slug,),
        ).fetchone()
    return row[0] if row else None


def set_cursor(
    source_slug: str,
    last_external_id: Optional[str],
    status: str = "ok",
    *,
    db_path: Optional[Path] = None,
) -> None:
    db_path = db_path or settings.sqlite_path
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            INSERT INTO insiders_cursor
                (source_slug, last_external_id, last_run_at, last_run_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_slug) DO UPDATE SET
                last_external_id = COALESCE(excluded.last_external_id, insiders_cursor.last_external_id),
                last_run_at      = excluded.last_run_at,
                last_run_status  = excluded.last_run_status
            """,
            (source_slug, last_external_id, now, status),
        )
        conn.commit()


def list_cursors(*, db_path: Optional[Path] = None) -> list[dict]:
    db_path = db_path or settings.sqlite_path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source_slug, last_external_id, last_run_at, last_run_status "
            "FROM insiders_cursor ORDER BY source_slug"
        ).fetchall()
    return [dict(r) for r in rows]
