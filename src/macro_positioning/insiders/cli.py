"""CLI wrapper for the insiders package.

Surfaces:
  - `insiders pull --source {house|all} [--since YYYY-MM-DD] [--year YYYY]`
  - `insiders status` — print the insiders_cursor table.

The scheduler's morning_run() calls `pull_all(catch_errors=True)`
programmatically; CLI subcommands just delegate to the same helpers.

Piece 1 only registers the `house` source. Adding senate/form4/13f/etc. is
one entry in `SOURCES` per scraper.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable, Optional

from macro_positioning.insiders import (
    base,
    house_ptr,
    ingest,
    lda,
    sec_13d_13g,
    sec_13f,
    sec_form4,
    senate_ptr,
    social_apewisdom,
    social_stocktwits,
    social_uw,
    usaspending,
)
from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


# Source registry: slug -> fetch_since callable.
# Each callable takes (cursor, since=, **kwargs) and returns an iterable
# of ScrapedEvent objects.
SOURCES: dict[str, Callable[..., Iterable[ScrapedEvent]]] = {
    "house": house_ptr.fetch_since,
    "senate": senate_ptr.fetch_since,
    "form4": sec_form4.fetch_since,
    "13dg": sec_13d_13g.fetch_since,
    "13f": sec_13f.fetch_since,
    "usaspending": usaspending.fetch_since,
    "lda": lda.fetch_since,
    "apewisdom": social_apewisdom.fetch_since,
    "stocktwits": social_stocktwits.fetch_since,
    "uw": social_uw.fetch_since,
}


def pull_one(
    source_slug: str,
    *,
    since: Optional[str] = None,
    year: Optional[int] = None,
) -> dict:
    """Pull one source and funnel events into the ingest pipeline.

    Returns the summary dict from `ingest.funnel()`.
    """
    if source_slug not in SOURCES:
        raise KeyError(f"Unknown insiders source: {source_slug}")
    cursor = base.get_cursor(source_slug)
    log.info("insiders[%s] starting; cursor=%s since=%s", source_slug, cursor, since)
    kwargs = {"since": since}
    if year is not None:
        kwargs["year"] = year
    events = SOURCES[source_slug](cursor, **kwargs)
    summary = ingest.funnel(events, source_slug=source_slug)
    log.info("insiders[%s] done: %s", source_slug, summary)
    return summary


def pull_all(*, since: Optional[str] = None, catch_errors: bool = False) -> dict:
    """Pull every registered source.

    `catch_errors=True` (used by morning_run) records per-source errors in
    the summary rather than raising — one bad source must not abort the
    whole morning pipeline.
    """
    out: dict[str, dict] = {}
    for slug in SOURCES:
        try:
            out[slug] = pull_one(slug, since=since)
        except Exception as exc:  # noqa: BLE001
            log.exception("insiders[%s] aborted: %s", slug, exc)
            base.set_cursor(slug, None, status=f"error: {exc}")
            if catch_errors:
                out[slug] = {"ingested": 0, "skipped": 0, "errors": [str(exc)]}
            else:
                raise
    return out


def status() -> list[dict]:
    """Return rows from insiders_cursor for CLI display."""
    return base.list_cursors()
