"""Shared funnel: ScrapedEvent -> ManualInputPayload -> processor.ingest.

Every scraper hands events to `funnel()`, which:
  1. Builds an AuthorRef attributed to the disclosing principal.
  2. Builds ManualMetadata with the per-source conviction default.
  3. Calls manual.processor.ingest() — same pipeline manual chat drops use.
  4. Updates the insiders_cursor row to the last external_id seen.

Per-source conviction defaults live in CONVICTION_BY_KIND. The learning
loop's per-author calibration will eventually replace these with measured
weights; for v1 they're just placeholders that keep the watchlist scorer
from treating every PTR as max conviction.
"""

from __future__ import annotations

import logging
from typing import Iterable

from macro_positioning.manual import processor
from macro_positioning.manual.models import (
    AuthorRef,
    IngestResponse,
    ManualInputPayload,
    ManualMetadata,
)

from macro_positioning.insiders.base import ScrapedEvent, set_cursor


log = logging.getLogger(__name__)


# Per-source defaults. Keyed by (channel, transaction_type-bucket).
# transaction_type-bucket = "buy" | "sell" | "other".
# See plan §"Per-source conviction defaults" for rationale.
CONVICTION_DEFAULTS: dict[tuple[str, str], tuple[str, int, str]] = {
    # (channel, bucket) -> (side, conviction, timeframe)
    ("gov_insider", "buy"):   ("LONG",  3, "1W"),
    ("gov_insider", "sell"):  ("WATCH", 2, "1W"),
    ("gov_insider", "other"): ("WATCH", 2, "1W"),
    ("corp_insider", "buy"):  ("LONG",  4, "1W"),
    ("corp_insider", "sell"): ("WATCH", 1, "1W"),
    ("corp_insider", "other"):("WATCH", 2, "1W"),
    ("large_holder", "buy"):  ("LONG",  4, "1W"),
    ("large_holder", "sell"): ("WATCH", 2, "1W"),
    ("large_holder", "other"):("WATCH", 3, "1W"),
    ("fed_spend",    "other"):("WATCH", 2, "1W"),
    ("lobbying",     "other"):("WATCH", 1, "1W"),
    ("social",       "other"):("WATCH", 1, "1D"),
}


def _bucket(transaction_type: str | None) -> str:
    if not transaction_type:
        return "other"
    t = transaction_type.lower()
    if any(k in t for k in ("purchase", "buy", "new", "grown")):
        return "buy"
    if any(k in t for k in ("sale", "sell", "exited")):
        return "sell"
    return "other"


def _author_ref_for(event: ScrapedEvent) -> AuthorRef:
    """The author row is keyed to the disclosing principal, not the actor.

    A spouse-held Pelosi PTR and a self-held Pelosi PTR both attribute to
    the same `gov_insider:nancy-pelosi` row; the spouse/trust linkage rides
    along in user_metadata. This is what keeps the per-author leaderboard
    intact while still surfacing related-party context.
    """
    notes_bits: list[str] = []
    if event.actor_relationship and event.actor_relationship != "self":
        notes_bits.append(f"actor={event.actor_name} ({event.actor_relationship})")
    return AuthorRef(
        display_name=event.principal_name or event.actor_name,
        channel=event.channel,
        channel_type="other",
        notes="; ".join(notes_bits) or None,
    )


def _metadata_for(event: ScrapedEvent) -> ManualMetadata:
    bucket = _bucket(event.transaction_type)
    side, conviction, timeframe = CONVICTION_DEFAULTS.get(
        (event.channel, bucket),
        CONVICTION_DEFAULTS[(event.channel, "other")] if (event.channel, "other") in CONVICTION_DEFAULTS
        else ("WATCH", 1, "1W"),
    )
    ticker = event.tickers[0] if event.tickers else None
    # One-line summary as the note. Keep raw_text for the body.
    bits = [event.actor_name, event.transaction_type or "disclosure"]
    if ticker:
        bits.append(ticker)
    if event.amount_range:
        bits.append(event.amount_range)
    note = " · ".join(bits)
    return ManualMetadata(
        ticker=ticker,
        side=side,
        conviction=conviction,
        timeframe=timeframe,
        note=note,
    )


def _payload_for(event: ScrapedEvent) -> ManualInputPayload:
    return ManualInputPayload(
        text=_compose_body(event),
        metadata=_metadata_for(event),
        author=_author_ref_for(event),
    )


def _compose_body(event: ScrapedEvent) -> str:
    """The text the mention_extractor and pre_tagger will see.

    We dollar-sign the tickers so the extractor's `$TICKER` path picks
    them up regardless of how the source rendered them.
    """
    lines: list[str] = []
    if event.tickers:
        lines.append(" ".join(f"${t}" for t in event.tickers))
    if event.raw_text:
        lines.append(event.raw_text)
    if event.source_url:
        lines.append(f"Source: {event.source_url}")
    if event.actor_relationship and event.actor_relationship != "self":
        lines.append(
            f"(disclosed by {event.principal_name}; held by {event.actor_name} — "
            f"{event.actor_relationship})"
        )
    return "\n\n".join(lines)


# ── Public funnel ───────────────────────────────────────────────────────────


def funnel(events: Iterable[ScrapedEvent], source_slug: str) -> dict:
    """Push events through processor.ingest, advancing the cursor.

    Returns {ingested, skipped, errors, last_external_id} summary.
    Individual event errors are logged and counted; one bad row doesn't
    kill the run.
    """
    ingested = 0
    skipped = 0
    errors: list[str] = []
    last_external_id: str | None = None

    for event in events:
        try:
            resp: IngestResponse = processor.ingest(_payload_for(event))
            ingested += 1
            last_external_id = event.external_id
            log.debug(
                "insiders[%s] ingested doc=%s tickers=%s",
                source_slug, resp.document_id, resp.detected_tickers,
            )
        except Exception as exc:  # noqa: BLE001 — one bad row never kills the run
            errors.append(f"{event.external_id}: {exc}")
            skipped += 1
            log.exception("insiders[%s] failed on event %s", source_slug, event.external_id)

    status = "ok" if not errors else f"partial: {len(errors)} errors"
    set_cursor(source_slug, last_external_id, status=status)

    return {
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
        "last_external_id": last_external_id,
    }
