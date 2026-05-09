"""Ticker mention extraction from document text.

Pure regex + allow-list. NO LLM. Goal: surface tickers that recent
newsletters / podcasts / RSS feeds are actually talking about, so the
watchlist resolver can promote them into scoring even if they're not
on the manual anchor list.

Design constraints:
- False positives are the biggest risk. "AI", "EV", "FOMC" all look
  like tickers. Strict allow-list approach: only count mentions of
  tickers we already KNOW are real (anchor list + asset_themes
  watchlists). The system can't discover entirely new tickers from
  prose alone, but it CAN flag when a known ticker is being talked
  about a lot more than usual.
- Match patterns: `$URA`, `URA`, `(URA)`, "ticker URA", "of URA"
  Not match: "URA" inside a longer word, lowercase 'ura', commas/periods
  glued mid-word.
- Counts dedupe within a document — three mentions of URA in one
  Doomberg post = 1 doc-mention, not 3. Mention "weight" is documents
  containing the ticker, not raw frequency.

Future:
- Promote frequency-weighted within doc once we have noise/signal data
- Add an LLM-backed verification pass for ambiguous cases (low-priority)
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings


# ---------------------------------------------------------------------------
# Allow-list: built from canonical configs at first call, cached for process.
# ---------------------------------------------------------------------------

_ALLOWLIST_CACHE: set[str] | None = None


def _build_allowlist() -> set[str]:
    """Compose the universe of tickers we consider 'real':
    - anchors from config/watchlist.json
    - per-theme watchlist_tickers from config/asset_themes.json
    - hard-coded global commons (broad indices, popular crypto, mega-caps)

    Returns uppercase symbols.
    """
    out: set[str] = set()
    base = settings.base_dir

    # config/watchlist.json
    wl = base / "config" / "watchlist.json"
    if wl.exists():
        try:
            data = json.loads(wl.read_text())
            for entry in data.get("anchors", []):
                t = entry.get("ticker", "").upper().strip()
                if t:
                    out.add(t)
        except Exception:
            pass

    # config/asset_themes.json
    at = base / "config" / "asset_themes.json"
    if at.exists():
        try:
            data = json.loads(at.read_text())
            for theme in data.get("themes", {}).values():
                for t in theme.get("watchlist_tickers", []) or []:
                    if t:
                        out.add(t.upper().strip())
        except Exception:
            pass

    # Common universe additions — extend as you discover new tickers worth tracking
    out.update({
        "SPY", "QQQ", "DIA", "IWM", "VIX", "DXY", "TLT", "TBT",
        "GLD", "SLV", "GDX", "GDXJ", "URA", "URNM", "USO", "UCO",
        "BTC", "ETH", "SOL", "MSTR", "COIN",
        "NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "TSLA", "AVGO", "AMD", "TSM", "SMH",
        "JPM", "BAC", "GS", "WFC",
        "XLE", "XOP", "XLF", "XLK", "XLU", "XLV", "XLY", "XLP", "XLI", "XLB",
        "ITA", "LMT", "RTX", "GD", "NOC", "HII", "PLTR",
        "CCJ", "DNN", "UEC", "NXE",
        "DBA", "MOO", "WEAT", "CORN", "SOYB",
    })
    return out


def get_allowlist() -> set[str]:
    """Return the cached allow-list. Bust cache via reset_allowlist()
    after editing configs at runtime (rare)."""
    global _ALLOWLIST_CACHE
    if _ALLOWLIST_CACHE is None:
        _ALLOWLIST_CACHE = _build_allowlist()
    return _ALLOWLIST_CACHE


def reset_allowlist() -> None:
    global _ALLOWLIST_CACHE
    _ALLOWLIST_CACHE = None


# ---------------------------------------------------------------------------
# Regex patterns — match candidate tickers in prose
# ---------------------------------------------------------------------------

# Words that look like tickers but never are. Filtered out before allow-list
# check (defense in depth). Keep tight; allow-list is the primary filter.
_NEVER_TICKERS = {
    "I", "A", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US",
    "WE", "ALL", "AND", "ARE", "BUT", "FOR", "HAS", "HAD", "HER", "HIM",
    "HIS", "HOW", "ITS", "NOT", "NOW", "OUR", "OUT", "SHE", "SO", "THE",
    "WAS", "WHO", "WHY", "YES", "YET", "YOU",
    # Common acronyms that look like tickers but aren't
    "AI", "ML", "GPU", "CPU", "API", "URL", "HTML", "CSS", "JSON", "PDF",
    "USA", "UK", "EU", "UN", "NATO", "OPEC", "GDP", "CPI", "PPI", "PCE",
    "FOMC", "FED", "ECB", "BOJ", "PBOC", "BOE",
    "CEO", "CFO", "CTO", "COO", "VP", "PM", "AM",
    "QE", "QT", "RRP", "TGA", "OFR", "TIPS",
    "ETF", "REIT", "IPO", "M&A", "ESG",
}

# $TICKER form is unambiguous — always match (still allow-list-checked)
_DOLLAR_TICKER = re.compile(r"\$([A-Z][A-Z0-9.\-]{0,5})\b")

# Plain TICKER form — uppercase 2-5 chars, word-bounded, not part of a
# camelCase/Mixed word. Will catch things like "AI", "EV" etc; relies on
# allow-list to filter.
_BARE_TICKER = re.compile(r"\b([A-Z]{1,5})\b")


def extract_tickers_from_text(text: str) -> set[str]:
    """Return the set of allow-listed tickers mentioned in `text`.

    De-duped within the document — each ticker is reported once
    regardless of mention count. Caller aggregates across docs.
    """
    if not text:
        return set()
    allow = get_allowlist()
    found: set[str] = set()

    # First pass: $TICKER form (high-confidence)
    for m in _DOLLAR_TICKER.finditer(text):
        sym = m.group(1).upper()
        if sym in allow and sym not in _NEVER_TICKERS:
            found.add(sym)

    # Second pass: bare uppercase tokens
    for m in _BARE_TICKER.finditer(text):
        sym = m.group(1).upper()
        if len(sym) < 2:
            continue  # skip single letters — too noisy
        if sym in _NEVER_TICKERS:
            continue
        if sym in allow:
            found.add(sym)

    return found


# ---------------------------------------------------------------------------
# Aggregation across the documents corpus
# ---------------------------------------------------------------------------

class MentionCount(BaseModel):
    ticker: str
    docs_with_mention: int
    sources: list[str] = Field(default_factory=list, description="Distinct source_ids that mentioned this ticker in window")
    most_recent_at: str | None = None


class WindowMentions(BaseModel):
    window_days: int
    total_docs_scanned: int
    counts: list[MentionCount] = Field(default_factory=list)


def count_mentions(
    docs: Iterable[dict],
    *,
    window_days: int,
    now: datetime | None = None,
) -> WindowMentions:
    """Count distinct tickers across a doc set, filtered to docs published
    within the last `window_days`.

    Each doc is `{source_id, title, cleaned_text, published_at}` — match
    the `Document` model from core/models.py. Caller does the DB query.
    """
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=window_days)

    # ticker -> { docs: int, sources: set, most_recent_at: datetime }
    agg: dict[str, dict] = defaultdict(lambda: {"docs": 0, "sources": set(), "most_recent_at": None})
    scanned = 0

    for doc in docs:
        published = doc.get("published_at")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception:
                continue
        if not published or published.tzinfo is None:
            published = (published or current).replace(tzinfo=UTC)
        if published < cutoff:
            continue
        scanned += 1

        text = (doc.get("title") or "") + "\n\n" + (doc.get("cleaned_text") or doc.get("raw_text") or "")
        tickers = extract_tickers_from_text(text)
        if not tickers:
            continue

        source_id = doc.get("source_id", "unknown")
        for t in tickers:
            entry = agg[t]
            entry["docs"] += 1
            entry["sources"].add(source_id)
            prev = entry["most_recent_at"]
            if prev is None or published > prev:
                entry["most_recent_at"] = published

    counts = [
        MentionCount(
            ticker=ticker,
            docs_with_mention=info["docs"],
            sources=sorted(info["sources"]),
            most_recent_at=info["most_recent_at"].isoformat() if info["most_recent_at"] else None,
        )
        for ticker, info in agg.items()
    ]
    counts.sort(key=lambda c: (-c.docs_with_mention, c.ticker))

    return WindowMentions(
        window_days=window_days,
        total_docs_scanned=scanned,
        counts=counts,
    )
