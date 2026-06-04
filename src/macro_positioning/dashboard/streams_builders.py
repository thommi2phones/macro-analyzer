"""Builders for the /streams SPA tab (S1 theme map, S2 concepts, S3 source graph).

Pure functions over a sqlite3.Connection so the SPA layer can call them
without owning DB lifecycle. Each builder returns JSON-serializable
dicts/lists matching the shapes the JSX already consumes (see
web/streams.jsx and web/data.mock.js streams: {...}).

Theme membership for a signal is the UNION of three sources, so the map
encompasses everything we process — not just whatever the extractors
happened to tag:
  1. Curated sector theme by ticker — config/asset_themes.json maps
     tickers → themes (uranium, technology_ai, energy, defense, ...).
     A signal on NVDA rolls up to technology_ai even if its free-text
     tags are noise.
  2. Real macro/regime tags from thesis_tags_json + macro_regime_tags_json,
     after filtering chart-pattern / sentiment / direction noise.
  3. Asset-class catch-all bucket (equities_broad, crypto_broad, ...) for
     any signal that matched neither of the above — so the long tail of
     undifferentiated retail mentions still appears as a bubble instead of
     silently vanishing.

No schema changes: tier and market_focus are derived in-builder.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_WINDOW_THEME_DAYS = 28
_WINDOW_CONCEPT_DAYS = 14
_WINDOW_NODE_DAYS = 90

_BULL_SIDES = {"LONG", "ADD"}
_BEAR_SIDES = {"SHORT", "AVOID"}

# Cluster keys mirror web/streams.jsx _CLUSTERS focuses (must match exactly).
_CLUSTER_TOKENS: dict[str, set[str]] = {
    "macro":      {"macro", "rates", "fed"},
    "equities":   {"equities", "equity", "factor", "factors", "sector", "sectors"},
    "tech":       {"tech", "ai", "semis", "semiconductor", "semiconductors", "software"},
    "energy":     {"energy", "commodities", "oil", "uranium", "metals", "nat_gas", "gas"},
    "realassets": {"gold", "assets", "real_estate", "reit", "reits", "silver"},
    "crypto":     {"crypto", "btc", "eth", "digital", "onchain"},
    "credit":     {"credit", "fi", "income", "spreads", "bond", "bonds", "ig", "hy"},
    "fx":         {"fx", "geopolitics", "currency", "em", "dxy", "yen", "euro"},
    "social":     {"social", "news", "media", "twitter", "rss"},
}

# Asset-class → cluster fallback when no thesis tags match a token bucket.
_ASSET_CLASS_TO_CLUSTER: dict[str, str] = {
    "equity": "equities",
    "equities": "equities",
    "etf": "equities",
    "future": "macro",
    "rates": "macro",
    "macro": "macro",
    "fx": "fx",
    "currency": "fx",
    "commodity": "energy",
    "commodities": "energy",
    "energy": "energy",
    "crypto": "crypto",
    "credit": "credit",
    "bond": "credit",
    "gold": "realassets",
}

_TOKEN_SPLIT = re.compile(r"[\s,/_\-]+")

# Tag tokens that are NOT themes. The insider/social extractors leak chart
# patterns, sentiment/microstructure terms, and direction labels into the
# tag stream — a theme map should surface SECTORS / MACRO NARRATIVES, not
# "wedge_pattern" or "social_media_sentiment". We filter at consumption so
# the raw tags stay available for other surfaces (per-signal drill-downs,
# tag co-occurrence, etc.).
#
# Logic: split a candidate theme id on `_`; if EVERY part is in this set,
# drop the theme. So "social_media_sentiment" → ["social","media","sentiment"]
# (all denied → drop). "ai_capex" → ["ai","capex"] (ai keeps it → keep).
_NON_THEME_TOKENS: set[str] = {
    # chart patterns / technical structures / analysis verbs
    "technical", "analysis", "analyses", "analytic", "analytics",
    "resistance", "support", "breakout", "breakdown", "break",
    "wedge", "pattern", "patterns", "channel", "triangle", "pennant",
    "flag", "head", "shoulders", "cup", "handle", "setup", "setups",
    "play", "plays", "idea", "ideas", "potential", "theme",
    "fib", "fibonacci", "level", "levels", "zone", "zones",
    "ema", "sma", "macd", "rsi", "stoch", "stochastic",
    "bollinger", "ttm", "vwap", "atr", "adx",
    # market microstructure / order flow / strategy
    "momentum", "flow", "flows", "retail", "options", "option",
    "spike", "average", "moving", "ranking", "rank", "strategy",
    "meme", "signal", "signals", "spread", "premium", "skew",
    "positive", "negative",
    # sentiment / social platforms
    "social", "media", "sentiment", "trending", "trend", "buzz",
    "interest", "attention", "mention", "mentions", "chatter", "hype",
    "wallstreetbets", "wsb", "stocktwits", "twitter",
    "reddit", "ape", "apewisdom", "rss", "news", "headline",
    # generic direction / lifecycle words
    "stock", "stocks", "trade", "trading", "trades",
    "long", "short", "bullish", "bearish", "mixed", "neutral",
    "bull", "bear", "buy", "sell", "hold", "watch", "exit",
    "trim", "add", "event",
    # generic OHLC / numeric noise
    "high", "low", "open", "close", "volume",
}


def _is_real_theme(theme_id: str) -> bool:
    """True iff theme_id has at least one component that isn't generic
    noise. See _NON_THEME_TOKENS docstring."""
    if not theme_id:
        return False
    parts = [p for p in theme_id.split("_") if p]
    if not parts:
        return False
    return any(p not in _NON_THEME_TOKENS for p in parts)


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d
    except (TypeError, ValueError):
        return None


def _normalize_tag(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or None


# Friendly labels for curated themes + generic buckets. Anything not here
# gets word-wise title case with known acronyms upper-cased.
_EXPLICIT_LABELS: dict[str, str] = {
    "technology_ai":     "Technology / AI",
    "precious_metals":   "Precious Metals",
    "equities_broad":    "Equities · broad",
    "crypto_broad":      "Crypto · broad",
    "commodities_broad": "Commodities · broad",
    "rates_broad":       "Rates · broad",
    "fx_broad":          "FX · broad",
    "options_broad":     "Options · broad",
    "cash":              "Cash",
}
_ACRONYMS = {"ai", "fx", "etf", "us", "em", "btc", "eth", "ev", "reit", "ipo"}


def _title_label(theme_id: str) -> str:
    """Render a theme id as a clean display label.

    technology_ai → Technology / AI · risk_on_expansion → Risk On Expansion
    """
    if theme_id in _EXPLICIT_LABELS:
        return _EXPLICIT_LABELS[theme_id]
    parts = [p for p in str(theme_id).split("_") if p]
    if not parts:
        return str(theme_id)
    return " ".join(p.upper() if p in _ACRONYMS else p.capitalize() for p in parts)


# Asset-class → generic catch-all bucket id (the long-tail fallback).
_ASSET_CLASS_BUCKET: dict[str, str] = {
    "equity":      "equities_broad",
    "equities":    "equities_broad",
    "etf":         "equities_broad",
    "crypto":      "crypto_broad",
    "commodity":   "commodities_broad",
    "commodities": "commodities_broad",
    "rates":       "rates_broad",
    "bond":        "rates_broad",
    "credit":      "rates_broad",
    "fx":          "fx_broad",
    "currency":    "fx_broad",
    "option":      "options_broad",
    "cash":        "cash",
}

# Cached ticker → curated-theme index, loaded from config/asset_themes.json.
_TICKER_THEME_CACHE: dict[str, str] | None = None


def _ticker_theme_index() -> dict[str, str]:
    """Map TICKER (upper) → curated theme key from config/asset_themes.json.

    Cached per-process; the config is static at runtime. Returns {} if the
    file is missing or malformed so the builder degrades to tag + asset-class
    coverage only.
    """
    global _TICKER_THEME_CACHE
    if _TICKER_THEME_CACHE is not None:
        return _TICKER_THEME_CACHE
    idx: dict[str, str] = {}
    try:
        from macro_positioning.core.settings import settings as _settings
        path = _settings.base_dir / "config" / "asset_themes.json"
        data = json.loads(path.read_text())
        for key, spec in (data.get("themes") or {}).items():
            for tk in (spec.get("watchlist_tickers") or []):
                t = str(tk).strip().upper()
                if t:
                    idx.setdefault(t, key)
    except Exception:
        idx = {}
    _TICKER_THEME_CACHE = idx
    return idx


def _load_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        n = _normalize_tag(it)
        if n:
            out.append(n)
    return out


def _safe_table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return cur.fetchone() is not None
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Signal loader (shared by S1 + S2)
# ---------------------------------------------------------------------------

def _load_signals(conn: sqlite3.Connection, window_days: int, now: datetime) -> list[dict]:
    if not _safe_table_exists(conn, "signals"):
        return []
    cutoff = (now - timedelta(days=window_days)).isoformat()
    try:
        cur = conn.execute(
            """
            SELECT signal_id, extracted_at, side, conviction,
                   author_trust_weight, source_slug, author_id,
                   asset_class, thesis_tags_json, macro_regime_tags_json,
                   thesis_summary, asset_ticker
              FROM signals
             WHERE COALESCE(status, 'active') = 'active'
               AND extracted_at >= ?
            """,
            (cutoff,),
        )
    except sqlite3.Error:
        return []
    out: list[dict] = []
    for r in cur.fetchall():
        out.append({
            "signal_id":    r[0],
            "extracted_at": _parse_iso(r[1]),
            "side":         (r[2] or "").upper(),
            "conviction":   float(r[3] or 0.0),
            "trust":        float(r[4] or 1.0),
            "source_slug":  r[5] or "",
            "author_id":    r[6] or "",
            "asset_class":  (r[7] or "").lower(),
            "thesis_tags":  _load_json_list(r[8]),
            "regime_tags":  _load_json_list(r[9]),
            "thesis_summary": r[10] or "",
            "asset_ticker": r[11] or "",
        })
    return out


def _signal_themes(s: dict, ticker_idx: dict[str, str] | None = None) -> set[str]:
    """All themes this signal belongs to: curated sector (by ticker) ∪ real
    macro/regime tags ∪ asset-class catch-all. See module docstring.

    ticker_idx is the result of _ticker_theme_index(); passed in by callers
    so it's computed once per build rather than per signal.
    """
    if ticker_idx is None:
        ticker_idx = _ticker_theme_index()
    out: set[str] = set()
    # 1. real macro/regime tags (noise-filtered)
    for t in (set(s["thesis_tags"]) | set(s["regime_tags"])):
        if _is_real_theme(t):
            out.add(t)
    # 2. curated sector theme by ticker
    tk = (s.get("asset_ticker") or "").strip().upper()
    if tk and tk in ticker_idx:
        out.add(ticker_idx[tk])
    # 3. asset-class catch-all so the long tail still shows up
    if not out:
        bucket = _ASSET_CLASS_BUCKET.get(s.get("asset_class", ""))
        if bucket:
            out.add(bucket)
    return out


# ---------------------------------------------------------------------------
# S1 — themeMap
# ---------------------------------------------------------------------------

def build_theme_map(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[dict]:
    """Per-theme card for the S1 scatter map. See web/streams.jsx ThemeMap."""
    now = _now(now)
    signals = _load_signals(conn, _WINDOW_THEME_DAYS, now)
    if not signals:
        return []

    ticker_idx = _ticker_theme_index()
    by_theme: dict[str, list[dict]] = defaultdict(list)
    for s in signals:
        if s["extracted_at"] is None:
            continue
        for theme in _signal_themes(s, ticker_idx):
            by_theme[theme].append(s)

    out: list[dict] = []
    for theme_id, sigs in by_theme.items():
        if len(sigs) < 3:
            continue  # noise filter per brief

        # 4 weekly buckets: w-3, w-2, w-1, now (rightmost = current week)
        buckets = [0, 0, 0, 0]
        first_seen: datetime | None = None
        sources: set[str] = set()
        for s in sigs:
            dt = s["extracted_at"]
            if dt is None:
                continue
            age_days = (now - dt).total_seconds() / 86400.0
            week_idx_from_now = int(age_days // 7)  # 0 = current week
            if 0 <= week_idx_from_now <= 3:
                buckets[3 - week_idx_from_now] += 1
            if first_seen is None or dt < first_seen:
                first_seen = dt
            slug = s["source_slug"] or s["author_id"]
            if slug:
                sources.add(slug)

        mentions_last_7d = buckets[3]
        mentions_prev_7d = buckets[2]
        max_window = max(buckets) or 1
        age_days = int((now - first_seen).total_seconds() / 86400.0) if first_seen else 0

        # Direction: trust*conviction-weighted vote of sides
        score = 0.0
        total_w = 0.0
        for s in sigs:
            w = max(0.01, s["trust"]) * max(0.0, s["conviction"])
            if w <= 0:
                w = max(0.01, s["trust"])  # conviction may be 0 — keep a floor
            total_w += w
            if s["side"] in _BULL_SIDES:
                score += w
            elif s["side"] in _BEAR_SIDES:
                score -= w
        if total_w > 0 and abs(score) / total_w > 0.4:
            direction = "bullish" if score > 0 else "bearish"
        else:
            direction = "mixed"

        # Lifecycle: 1 - recent/max_window (0=emerging, 1=fading)
        lifecycle = max(0.0, min(1.0, 1.0 - (mentions_last_7d / max_window)))
        # Novelty
        novelty = max(0.0, min(1.0, 1.0 - (age_days / _WINDOW_THEME_DAYS)))
        # Velocity: tanh-squashed week-over-week growth
        raw_velocity = (mentions_last_7d - mentions_prev_7d) / max(mentions_prev_7d, 1)
        velocity = max(0.0, min(1.0, (math.tanh(raw_velocity) + 1.0) / 2.0))

        out.append({
            "id":               theme_id,
            "label":            _title_label(theme_id),
            "direction":        direction,
            "lifecycle":        round(lifecycle, 3),
            "novelty":          round(novelty, 3),
            "velocity":         round(velocity, 3),
            "age_days":         age_days,
            "mentions_by_week": buckets,
            "sources":          sorted(sources),
        })

    out.sort(key=lambda t: sum(t["mentions_by_week"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Asset map — parallel to S1 themeMap but keyed on signals.asset_ticker.
# Same dict shape so the SPA can reuse the ThemeMap component.
# ---------------------------------------------------------------------------

def build_asset_map(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[dict]:
    """Per-asset card mirroring build_theme_map's shape but grouped by
    `signals.asset_ticker` instead of theme tag. Lets the UI surface
    'what tickers are being talked about' alongside 'what narratives'."""
    now = _now(now)
    signals = _load_signals(conn, _WINDOW_THEME_DAYS, now)
    if not signals:
        return []

    # Junk sentinel values some extractors emit when they can't resolve a
    # ticker — drop them rather than render an "N/A" bubble.
    _JUNK_TICKERS = {"", "N/A", "NA", "NONE", "NULL", "?", "TBD", "UNKNOWN"}
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for s in signals:
        ticker = (s.get("asset_ticker") or "").strip().upper()
        if ticker in _JUNK_TICKERS:
            continue
        if s["extracted_at"] is None:
            continue
        by_ticker[ticker].append(s)

    out: list[dict] = []
    for ticker, sigs in by_ticker.items():
        if len(sigs) < 3:
            continue

        buckets = [0, 0, 0, 0]
        first_seen: datetime | None = None
        sources: set[str] = set()
        for s in sigs:
            dt = s["extracted_at"]
            if dt is None:
                continue
            age_days_f = (now - dt).total_seconds() / 86400.0
            wk = int(age_days_f // 7)
            if 0 <= wk <= 3:
                buckets[3 - wk] += 1
            if first_seen is None or dt < first_seen:
                first_seen = dt
            slug = s["source_slug"] or s["author_id"]
            if slug:
                sources.add(slug)

        mentions_last_7d = buckets[3]
        mentions_prev_7d = buckets[2]
        max_window = max(buckets) or 1
        age_days = int((now - first_seen).total_seconds() / 86400.0) if first_seen else 0

        score = 0.0
        total_w = 0.0
        for s in sigs:
            w = max(0.01, s["trust"]) * max(0.0, s["conviction"])
            if w <= 0:
                w = max(0.01, s["trust"])
            total_w += w
            if s["side"] in _BULL_SIDES:
                score += w
            elif s["side"] in _BEAR_SIDES:
                score -= w
        if total_w > 0 and abs(score) / total_w > 0.4:
            direction = "bullish" if score > 0 else "bearish"
        else:
            direction = "mixed"

        lifecycle = max(0.0, min(1.0, 1.0 - (mentions_last_7d / max_window)))
        novelty = max(0.0, min(1.0, 1.0 - (age_days / _WINDOW_THEME_DAYS)))
        raw_velocity = (mentions_last_7d - mentions_prev_7d) / max(mentions_prev_7d, 1)
        velocity = max(0.0, min(1.0, (math.tanh(raw_velocity) + 1.0) / 2.0))

        out.append({
            "id":               ticker,
            "label":            ticker,
            "direction":        direction,
            "lifecycle":        round(lifecycle, 3),
            "novelty":          round(novelty, 3),
            "velocity":         round(velocity, 3),
            "age_days":         age_days,
            "mentions_by_week": buckets,
            "sources":          sorted(sources),
        })

    out.sort(key=lambda t: sum(t["mentions_by_week"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# S2 — concepts
# ---------------------------------------------------------------------------

def _truncate_synopsis(text: str, limit: int = 180) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Prefer last sentence boundary
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > 40:
            return cut[: idx + 1].strip()
    # Else trim at last space
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 40 else cut).strip()


def build_concepts(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[dict]:
    """Pre-filter to novelty>0.7 AND velocity>0.4 (UI re-filters too)."""
    now = _now(now)
    themes = build_theme_map(conn, now=now)
    if not themes:
        return []

    # Reload signals at the concept window (14d) for items/sources counts
    sigs_14d = _load_signals(conn, _WINDOW_CONCEPT_DAYS, now)
    by_theme_14d: dict[str, list[dict]] = defaultdict(list)
    for s in sigs_14d:
        for tag in _signal_themes(s):
            by_theme_14d[tag].append(s)

    # Author display-name lookup
    display_by_slug = _author_display_map(conn)

    out: list[dict] = []
    for t in themes:
        if t["novelty"] <= 0.7 or t["velocity"] <= 0.4:
            continue
        tid = t["id"]
        recent = by_theme_14d.get(tid, [])
        items_count = len({s["signal_id"] for s in recent})
        slugs = [s["source_slug"] or s["author_id"] for s in recent]
        slug_counts = Counter([s for s in slugs if s])
        sources_count = len(slug_counts)
        source_names = [display_by_slug.get(slug, slug) for slug, _ in slug_counts.most_common(3)]

        # Synopsis from latest signal w/ thesis_summary
        recent_sorted = sorted(
            [s for s in recent if s.get("thesis_summary")],
            key=lambda s: s["extracted_at"] or now,
            reverse=True,
        )
        if recent_sorted:
            synopsis = _truncate_synopsis(recent_sorted[0]["thesis_summary"])
        else:
            synopsis = _fallback_synopsis(conn, tid)

        out.append({
            "id":            tid,
            "title":         _title_label(tid),
            "synopsis":      synopsis,
            "novelty":       t["novelty"],
            "velocity":      t["velocity"],
            "items_count":   items_count,
            "sources_count": sources_count,
            "source_names":  source_names,
            "age_days":      t["age_days"],
        })

    return out


def _fallback_synopsis(conn: sqlite3.Connection, theme_id: str) -> str:
    """First 180 chars of most recent document body that mentions the theme.

    Theme id may not appear verbatim in body text, so we just grab the
    most recent signal's parent doc cleaned_text. Keep cheap.
    """
    if not _safe_table_exists(conn, "documents"):
        return ""
    try:
        cur = conn.execute(
            """
            SELECT d.cleaned_text
              FROM signals s
              JOIN documents d ON d.document_id = s.document_id
             WHERE (s.thesis_tags_json LIKE ? OR s.macro_regime_tags_json LIKE ?)
               AND d.cleaned_text IS NOT NULL AND d.cleaned_text != ''
             ORDER BY s.extracted_at DESC
             LIMIT 1
            """,
            (f"%{theme_id}%", f"%{theme_id}%"),
        )
        row = cur.fetchone()
    except sqlite3.Error:
        return ""
    if not row or not row[0]:
        return ""
    return _truncate_synopsis(row[0])


# ---------------------------------------------------------------------------
# S3 — sourceGraph
# ---------------------------------------------------------------------------

def _trust_to_tier(trust: float | None) -> int:
    if trust is None:
        return 2  # baseline assumption
    if trust >= 1.4:
        return 0
    if trust >= 1.15:
        return 1
    if trust >= 0.85:
        return 2
    if trust >= 0.5:
        return 3
    return 4


def _author_display_map(conn: sqlite3.Connection) -> dict[str, str]:
    """Map author_id → display_name. Also include source_slug fallback."""
    out: dict[str, str] = {}
    if not _safe_table_exists(conn, "input_authors"):
        return out
    try:
        cur = conn.execute("SELECT author_id, display_name FROM input_authors")
        for aid, name in cur.fetchall():
            if aid:
                out[aid] = name or aid
    except sqlite3.Error:
        return out
    return out


def _derive_market_focus(
    asset_classes: Iterable[str],
    theme_tokens: Iterable[str],
) -> str:
    """Pick a cluster key for the SPA grid. Tokens take precedence; asset
    class is fallback. Returns one of the _CLUSTERS keys in streams.jsx."""
    counts: Counter[str] = Counter()
    for tok in theme_tokens:
        if not tok:
            continue
        for part in _TOKEN_SPLIT.split(tok):
            if not part:
                continue
            for cluster, vocab in _CLUSTER_TOKENS.items():
                if part in vocab:
                    counts[cluster] += 1
    if counts:
        return counts.most_common(1)[0][0]
    for ac in asset_classes:
        if ac in _ASSET_CLASS_TO_CLUSTER:
            return _ASSET_CLASS_TO_CLUSTER[ac]
    return "macro"


def build_source_graph(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    now = _now(now)

    if not _safe_table_exists(conn, "input_authors"):
        return {"nodes": [], "links": []}

    cutoff = (now - timedelta(days=_WINDOW_NODE_DAYS)).isoformat()
    try:
        # Require a real last_seen_at — seeded-but-never-dropped authors
        # (NULL last_seen_at) are not active sources for the graph.
        cur = conn.execute(
            """
            SELECT author_id, display_name, trust_weight
              FROM input_authors
             WHERE last_seen_at IS NOT NULL
               AND last_seen_at >= ?
            """,
            (cutoff,),
        )
        author_rows = cur.fetchall()
    except sqlite3.Error:
        author_rows = []

    # Per-author signals in 90d (for market_focus)
    sigs_90d = _load_signals(conn, _WINDOW_NODE_DAYS, now)
    by_author: dict[str, list[dict]] = defaultdict(list)
    for s in sigs_90d:
        if s["author_id"]:
            by_author[s["author_id"]].append(s)

    nodes: list[dict] = []
    node_ids: set[str] = set()
    for aid, name, trust_raw in author_rows:
        if not aid:
            continue
        trust = float(trust_raw) if trust_raw is not None else None
        tier = _trust_to_tier(trust)
        weight = max(0.0, min(1.5, trust if trust is not None else 1.0)) / 1.5

        sigs = by_author.get(aid, [])
        asset_classes = [s["asset_class"] for s in sigs if s["asset_class"]]
        theme_tokens: list[str] = []
        for s in sigs:
            theme_tokens.extend(s["thesis_tags"])
            theme_tokens.extend(s["regime_tags"])
        focus = _derive_market_focus(asset_classes, theme_tokens) if sigs else "macro"

        nodes.append({
            "id":           aid,
            "name":         name or aid,
            "tier":         tier,
            "weight":       round(weight, 3),
            "market_focus": focus,
        })
        node_ids.add(aid)

    # Links via echo_ties — filter to pairs whose endpoints exist as nodes.
    links: list[dict] = []
    try:
        from macro_positioning.learning.source_attribution import echo_ties
        for pair in echo_ties(conn):
            a = pair.get("source_a")
            b = pair.get("source_b")
            if a in node_ids and b in node_ids:
                links.append({
                    "source":   a,
                    "target":   b,
                    "strength": float(pair.get("strength", 0.0)),
                })
    except Exception:
        links = []

    return {"nodes": nodes, "links": links}


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def build_streams_section(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    """Returns {themeMap, assetMap, concepts, sourceGraph}. Each child is empty-safe."""
    now = _now(now)
    try:
        theme_map = build_theme_map(conn, now=now)
    except Exception:
        theme_map = []
    try:
        asset_map = build_asset_map(conn, now=now)
    except Exception:
        asset_map = []
    try:
        concepts = build_concepts(conn, now=now)
    except Exception:
        concepts = []
    try:
        source_graph = build_source_graph(conn, now=now)
    except Exception:
        source_graph = {"nodes": [], "links": []}
    return {
        "themeMap":    theme_map,
        "assetMap":    asset_map,
        "concepts":    concepts,
        "sourceGraph": source_graph,
    }
