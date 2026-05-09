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
  Doomberg post = 1 doc-mention, not 3.

Time-weighting (Phase 6d):
- Mentions decay exponentially with age. half_life_days controls how
  fast: a mention `half_life_days` ago counts at 0.5 weight.
- DEFAULTS ARE MACRO-APPROPRIATE: a macro thesis lives over weeks to
  months, not days. Standalone default half_life_days=30 means a
  mention from 30d ago is still at 0.5 weight, 60d at 0.25, 14d at
  ~0.72. Tight horizons (7d) are tactical noise; we deliberately
  don't bias the system toward them.
- For windowed extraction, watchlist_resolver scales half-life with
  the window so the 90d window uses ~90d half-life — a 30d-old
  mention there counts at 0.79 (still strong signal).
- Source freshness multiplier: a mention from a source that's gone
  cold (low freshness score on its own SLA) counts less than from a
  fresh, recently-publishing source.
- Weighted score replaces raw doc count for ranking; raw count still
  exposed for transparency.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings
from macro_positioning.ingestion.freshness import freshness_score
from macro_positioning.ingestion.source_lifecycle import load_sources


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
    weighted_score: float = 0.0
    sources: list[str] = Field(default_factory=list, description="Distinct source_ids that mentioned this ticker in window")
    most_recent_at: str | None = None


class WindowMentions(BaseModel):
    window_days: int
    total_docs_scanned: int
    half_life_days: float
    counts: list[MentionCount] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Time-weighting helpers
# ---------------------------------------------------------------------------

def recency_weight(age_days: float, *, half_life_days: float = 30.0) -> float:
    """Exponential decay weight. age_days=0 → 1.0; age=half_life → 0.5; age=2×half_life → 0.25.

    Default half-life=30d is intentionally macro-appropriate: a thesis
    is meant to play out over weeks-to-months. Tighter half-lives
    (e.g. 7d) bias toward tactical noise and over-weight breaking news.
    Tunable per call when the caller has a specific horizon in mind
    (watchlist_resolver scales half-life with each extraction window).
    """
    if age_days < 0:
        age_days = 0.0
    if half_life_days <= 0:
        return 1.0
    return math.exp(-math.log(2) * age_days / half_life_days)


def _source_freshness_lookup() -> dict[str, float | None]:
    """Map source_id → that source's freshness_sla_hours. Used to dampen
    mentions from sources that publish rarely (their freshness window is
    longer, so a "fresh" mention from a daily source is more meaningful
    than a fresh mention from a weekly one — we want to amplify the
    signal-rich sources).

    Returns None for sources without an SLA (manual notes, charts).
    """
    out: dict[str, float | None] = {}
    try:
        for s in load_sources(include_archived=False):
            out[s.source_id] = s.freshness_sla_hours
    except Exception:
        pass
    return out


def count_mentions(
    docs: Iterable[dict],
    *,
    window_days: int,
    now: datetime | None = None,
    half_life_days: float = 30.0,
    apply_source_freshness: bool = True,
) -> WindowMentions:
    """Count distinct tickers across a doc set, filtered to docs published
    within the last `window_days`. Time-weighted.

    Args:
      docs: iterable of {source_id, title, cleaned_text, published_at}
      window_days: hard cutoff on document age before counting
      now: override "current time" for deterministic tests
      half_life_days: recency decay half-life. Default 30d (macro-appropriate):
        same-day mention → 1.0
        7d ago         → 0.85
        14d ago        → 0.72
        30d ago        → 0.50
        60d ago        → 0.25
        90d ago        → 0.13
      apply_source_freshness: if True, multiply each mention's weight by
        the source's freshness_score at the moment it published. A
        mention from a stale source counts proportionally less.

    Each ticker reports BOTH:
      - docs_with_mention: raw doc count (for transparency)
      - weighted_score: sum of recency × source-freshness weights (for
        ranking)

    `counts` is returned sorted by weighted_score DESC.
    """
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=window_days)
    src_slas = _source_freshness_lookup() if apply_source_freshness else {}

    # ticker -> { docs: int, weighted: float, sources: set, most_recent_at: datetime }
    agg: dict[str, dict] = defaultdict(lambda: {"docs": 0, "weighted": 0.0, "sources": set(), "most_recent_at": None})
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
        age_days = (current - published).total_seconds() / 86400.0
        recency = recency_weight(age_days, half_life_days=half_life_days)

        # Source freshness multiplier: 1.0 if not applying or source unknown
        src_weight = 1.0
        if apply_source_freshness:
            sla = src_slas.get(source_id)
            if sla:
                src_weight = freshness_score(published, sla, now=current)
        weight = recency * src_weight

        for t in tickers:
            entry = agg[t]
            entry["docs"] += 1
            entry["weighted"] += weight
            entry["sources"].add(source_id)
            prev = entry["most_recent_at"]
            if prev is None or published > prev:
                entry["most_recent_at"] = published

    counts = [
        MentionCount(
            ticker=ticker,
            docs_with_mention=info["docs"],
            weighted_score=round(info["weighted"], 4),
            sources=sorted(info["sources"]),
            most_recent_at=info["most_recent_at"].isoformat() if info["most_recent_at"] else None,
        )
        for ticker, info in agg.items()
    ]
    # Rank by weighted score; ties broken by raw doc count, then ticker
    counts.sort(key=lambda c: (-c.weighted_score, -c.docs_with_mention, c.ticker))

    return WindowMentions(
        window_days=window_days,
        total_docs_scanned=scanned,
        half_life_days=half_life_days,
        counts=counts,
    )
