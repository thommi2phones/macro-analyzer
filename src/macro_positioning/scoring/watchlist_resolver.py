"""Watchlist resolver — composes the active scoring set from three streams.

Streams (in order of precedence; first wins for the `origins` provenance):
1. ANCHORS         — config/watchlist.json `anchors[]` always included
2. THEME-ALIGNED   — config/asset_themes.json themes whose
                     `preferred_regimes` includes the current framework regime
3. MENTIONS        — top tickers by doc-mention count across rolling
                     windows (7d / 30d / 90d). De-duped against streams 1+2.

Each ticker in the result carries `origins: [str]` so the dashboard can
show *why* a ticker is being scored ("anchor", "theme:uranium",
"mentions:7d:12 docs", etc).

This is the heart of the "watchlist as a living object" design — it
listens to what your sources are talking about and promotes those
tickers into scoring without manual curation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings
from macro_positioning.scoring.mention_extractor import (
    MentionCount,
    WindowMentions,
    count_mentions,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WatchlistEntry(BaseModel):
    ticker: str
    name: str = ""
    asset_class: str = ""
    origins: list[str] = Field(default_factory=list)
    rationale: str = ""


class ResolvedWatchlist(BaseModel):
    resolved_at: str
    framework_regime: str
    entries: list[WatchlistEntry]
    mention_summary: dict = Field(default_factory=dict)
    total_count: int = 0


# ---------------------------------------------------------------------------
# Source loaders
# ---------------------------------------------------------------------------

def _load_anchors() -> list[dict]:
    path = settings.base_dir / "config" / "watchlist.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("anchors", [])
    except Exception:
        return []


def _load_themes() -> dict:
    path = settings.base_dir / "config" / "asset_themes.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("themes", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _add(entries: dict[str, WatchlistEntry], ticker: str, *, origin: str, name: str = "", asset_class: str = "", rationale: str = "") -> None:
    """Idempotent add — if ticker already present, append the new origin."""
    sym = ticker.upper().strip()
    if not sym:
        return
    if sym in entries:
        if origin not in entries[sym].origins:
            entries[sym].origins.append(origin)
        # Don't overwrite name/asset_class once set by an earlier (higher-precedence) source
        if not entries[sym].name and name:
            entries[sym].name = name
        if not entries[sym].asset_class and asset_class:
            entries[sym].asset_class = asset_class
        if not entries[sym].rationale and rationale:
            entries[sym].rationale = rationale
    else:
        entries[sym] = WatchlistEntry(
            ticker=sym,
            name=name,
            asset_class=asset_class,
            origins=[origin],
            rationale=rationale,
        )


def resolve_watchlist(
    *,
    framework_regime: str,
    documents: Iterable[dict] | None = None,
    mention_windows: Iterable[int] = (7, 30, 90),
    mention_top_n: int = 10,
    mention_min_count: int = 3,
    now: datetime | None = None,
) -> ResolvedWatchlist:
    """Compose the active watchlist.

    Args:
      framework_regime: current framework regime slug (e.g.
        'commodity_led_inflation') — used to pick theme tickers
      documents: iterable of {source_id, title, cleaned_text,
        published_at} dicts. Pass None to skip mention extraction
        (anchors + themes only).
      mention_windows: rolling windows in days for mention extraction
      mention_top_n: take at most this many tickers per window
      mention_min_count: require at least this many docs mentioning a
        ticker in a window before it qualifies
    """
    entries: dict[str, WatchlistEntry] = {}

    # Stream 1: anchors
    for a in _load_anchors():
        _add(
            entries,
            a.get("ticker", ""),
            origin="anchor",
            name=a.get("name", ""),
            asset_class=a.get("asset_class", ""),
            rationale=a.get("rationale", ""),
        )

    # Stream 2: regime-aligned themes
    themes = _load_themes()
    for theme_id, theme in themes.items():
        preferred = set(theme.get("preferred_regimes", []) or [])
        if framework_regime in preferred:
            for t in theme.get("watchlist_tickers", []) or []:
                _add(
                    entries,
                    t,
                    origin=f"theme:{theme_id}",
                    asset_class=theme.get("asset_class", ""),
                    rationale=f"Theme '{theme_id}' aligned with regime '{framework_regime}'",
                )

    # Stream 3: mention extraction (only if documents provided)
    mention_summary: dict[int, dict] = {}
    if documents is not None:
        # Materialize once so we can re-iterate per window
        docs_list = list(documents)
        for window in mention_windows:
            wm: WindowMentions = count_mentions(docs_list, window_days=window, now=now)
            top = [c for c in wm.counts if c.docs_with_mention >= mention_min_count][:mention_top_n]
            for c in top:
                _add(
                    entries,
                    c.ticker,
                    origin=f"mentions:{window}d:{c.docs_with_mention}",
                )
            mention_summary[window] = {
                "total_docs_scanned": wm.total_docs_scanned,
                "tickers_above_threshold": len(top),
                "top_5": [
                    {"ticker": c.ticker, "docs": c.docs_with_mention}
                    for c in top[:5]
                ],
            }

    out_entries = sorted(entries.values(), key=lambda e: (-len(e.origins), e.ticker))
    return ResolvedWatchlist(
        resolved_at=(now or datetime.now(UTC)).isoformat(),
        framework_regime=framework_regime,
        entries=out_entries,
        mention_summary=mention_summary,
        total_count=len(out_entries),
    )
