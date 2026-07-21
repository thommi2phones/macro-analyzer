"""Insiders ingest package.

Automated scrapers for free public disclosures (House Clerk + Senate eFD
STOCK Act PTRs, SEC Form 4/13F/13D-G, USAspending, LDA, plus social-trending
tickers from ApeWisdom and StockTwits). Each scraper emits `ScrapedEvent`
objects which the shared `ingest.funnel()` rewrites into `ManualInputPayload`
and pushes through `manual.processor.ingest()` — same pipeline manual chat
drops already use.

Piece 1 ships House PTR only. The package skeleton is designed so adding
each subsequent source is one new module + one line in `cli.SOURCES`.
"""

from macro_positioning.insiders.base import ScrapedEvent, Scraper  # noqa: F401
