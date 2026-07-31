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

from macro_positioning.manual.authors import seeded_author_ids


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_WINDOW_THEME_DAYS = 28
_WINDOW_CONCEPT_DAYS = 14
_WINDOW_NODE_DAYS = 90

# Max tickers returned by build_asset_map. The lifecycle scatter is for the
# most-discussed names; the long tail is noise and bloats the SPA. The
# front-end minor-cluster rollup folds the lower portion of this further.
_ASSET_MAP_CAP = 60

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
    # Only signals from authors the user has explicitly stated count toward
    # conviction. Auto-ingested authors (gov-insider, lobbying, social, …)
    # are excluded — see authors.seeded_author_ids.
    allowed = seeded_author_ids(conn)
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
        if (r[6] or "") not in allowed:
            continue
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
            "mention_only": False,
        })
    return out


# Common non-curated tickers → bucket, so document-mention tickers that
# aren't in any asset_themes entry still land in a theme.
_COMMON_TICKER_THEME: dict[str, str] = {
    "SPY": "equities_broad", "QQQ": "equities_broad", "DIA": "equities_broad",
    "IWM": "equities_broad", "VIX": "equities_broad",
    "XLF": "equities_broad", "XLK": "equities_broad", "XLY": "equities_broad",
    "XLP": "equities_broad", "XLI": "equities_broad", "XLB": "equities_broad",
    "XLV": "equities_broad", "XLU": "equities_broad",
    "JPM": "equities_broad", "BAC": "equities_broad", "GS": "equities_broad",
    "WFC": "equities_broad",
    "TLT": "rates_broad", "TBT": "rates_broad",
    "DXY": "fx_broad",
}


def _theme_for_ticker(ticker: str, ticker_idx: dict[str, str]) -> str | None:
    """Map a bare ticker (from a document mention) to a theme id:
    curated sector → common-ticker bucket → equities_broad default."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return None
    return ticker_idx.get(tk) or _COMMON_TICKER_THEME.get(tk) or "equities_broad"


# ---------------------------------------------------------------------------
# Keyword-based theme extraction from prose.
#
# The ticker scan can't see thematic, ticker-less views ("we're constructive
# on agriculture", "the uranium thesis is intact"). This vocabulary maps
# theme keywords → theme id so prose coverage flows into the map even before
# the LLM signal extractor runs on a document. Matched case-insensitively
# with word boundaries; multi-word phrases used wherever the single word
# would be too ambiguous.
# ---------------------------------------------------------------------------
_THEME_KEYWORDS: dict[str, list[str]] = {
    "uranium":         [r"uranium", r"yellowcake", r"nuclear", r"enrichment",
                        r"reactor", r"small modular", r"\bSMR\b"],
    "precious_metals": [r"\bgold\b", r"\bsilver\b", r"bullion",
                        r"precious metal", r"debasement"],
    "crypto":          [r"\bcrypto", r"bitcoin", r"ethereum", r"altcoin",
                        r"digital asset", r"stablecoin", r"\bdefi\b",
                        r"on[- ]?chain"],
    "technology_ai":   [r"artificial intelligence", r"semiconductor",
                        r"data ?cent(?:er|re)", r"AI capex",
                        r"AI infrastructure", r"machine learning",
                        r"hyperscaler", r"\bGPU\b"],
    "energy":          [r"energy security", r"\bcrude\b", r"\boil\b",
                        r"natural gas", r"nat gas", r"\bOPEC\b",
                        r"power grid", r"electricity", r"power demand",
                        r"\bLNG\b"],
    "defense":         [r"\bdefen[cs]e\b", r"military", r"\bNATO\b",
                        r"weapons", r"missile"],
    "agriculture":     [r"agriculture", r"farmland", r"\bfarming\b",
                        r"\bcrop", r"\bgrain", r"\bwheat\b", r"\bcorn\b",
                        r"soybean", r"fertili[sz]er", r"food security"],
    "inflation":       [r"inflation", r"\bCPI\b", r"rising prices",
                        r"cost of living", r"disinflation", r"stagflation"],
    "fed_policy":      [r"\bthe fed\b", r"\bFOMC\b", r"rate cut", r"rate hike",
                        r"interest rate", r"yield curve", r"treasury yield",
                        r"monetary policy", r"\bpowell\b", r"quantitative"],
    "recession_risk":  [r"recession", r"economic slowdown", r"hard landing",
                        r"soft landing", r"labou?r market", r"unemployment",
                        r"layoffs?"],
    "geopolitics":     [r"geopolitic", r"\bwar\b", r"sanction", r"tariff",
                        r"trade war", r"\btaiwan\b", r"\bukraine\b",
                        r"middle east"],
}

# Bull/bear cue words for a conservative document-level lexical lean. Used
# ONLY to give keyword-derived theme contributions a low-conviction
# direction; real extracted signals always outweigh them.
_BULL_CUES = re.compile(
    r"\b(?:bullish|long|buy(?:ing)?|accumulat\w*|breakout|upside|rally\w*|"
    r"constructive|overweight|outperform\w*|tailwind|surg\w*)\b",
    re.IGNORECASE,
)
_BEAR_CUES = re.compile(
    r"\b(?:bearish|short(?:ing)?|sell(?:ing)?|dump\w*|breakdown|downside|"
    r"underweight|underperform\w*|headwind|crash\w*|weakness|avoid)\b",
    re.IGNORECASE,
)

_THEME_COMBINED_RE: "re.Pattern[str] | None" = None


def _theme_combined_pattern() -> "re.Pattern[str]":
    """One combined named-group regex over the whole theme vocabulary, so a
    document is scanned in a single pass instead of once per theme.

    Keywords are lower-cased and matched against lower-cased text WITHOUT the
    IGNORECASE flag — case-folding a large alternation per char is the slow
    path; pre-lowering both sides is ~3× faster over the 12k-doc corpus.
    """
    global _THEME_COMBINED_RE
    if _THEME_COMBINED_RE is not None:
        return _THEME_COMBINED_RE
    parts = [
        f"(?P<{theme}>" + "|".join(f"(?:{k.lower()})" for k in kws) + ")"
        for theme, kws in _THEME_KEYWORDS.items()
    ]
    _THEME_COMBINED_RE = re.compile("|".join(parts))
    return _THEME_COMBINED_RE


def _themes_in_text(text: str) -> set[str]:
    """Theme ids whose keyword vocabulary appears in the prose (single pass)."""
    if not text:
        return set()
    found: set[str] = set()
    for m in _theme_combined_pattern().finditer(text.lower()):
        if m.lastgroup:
            found.add(m.lastgroup)
    return found


def _doc_lean(text: str) -> str:
    """Conservative document-level direction from bull/bear cue counts.
    Returns 'LONG' / 'SHORT' / '' (neutral). Deliberately blunt — a
    low-conviction nudge, never authoritative."""
    if not text:
        return ""
    bull = len(_BULL_CUES.findall(text))
    bear = len(_BEAR_CUES.findall(text))
    if bull == 0 and bear == 0:
        return ""
    if bull >= bear * 2 and bull >= 1:
        return "LONG"
    if bear >= bull * 2 and bear >= 1:
        return "SHORT"
    return ""


def _doc_source_key(source_id: str) -> str:
    """Readable source family for a document, consistent-ish with signal
    source_slugs. `forward_guidance` → forward_guidance;
    `manual:gov-insider:perdue` → gov-insider; `manual:telegram-channel:x`
    → telegram-channel."""
    sid = source_id or ""
    if ":" not in sid:
        return sid
    parts = sid.split(":")
    if parts[0] == "manual" and len(parts) >= 2:
        return parts[1]
    return parts[0]


# Short-lived cache so the 3 calls within one build_streams_section (theme
# map, asset map, concepts→theme map) scan the corpus once. Keyed by a cheap
# fingerprint (window + doc count + latest timestamp) so it's safe across
# tests with different DBs and self-invalidates when documents change.
_DOC_MENTION_CACHE: dict[tuple, list[dict]] = {}
_DOC_MENTION_CACHE_ORDER: list[tuple] = []
_DOC_MENTION_CACHE_MAX = 4


def _db_path_of(conn: sqlite3.Connection) -> str:
    """Best-effort path of the main attached database (for cache keying).
    Empty string for in-memory DBs."""
    try:
        for _seq, name, file in conn.execute("PRAGMA database_list").fetchall():
            if name == "main":
                return file or ""
    except sqlite3.Error:
        pass
    return ""


def _doc_corpus_fingerprint(conn: sqlite3.Connection, cutoff: str) -> tuple | None:
    try:
        row = conn.execute(
            """
            SELECT COUNT(*), COALESCE(MAX(COALESCE(published_at, ingested_at)), '')
              FROM documents
             WHERE COALESCE(published_at, ingested_at) >= ?
               AND cleaned_text IS NOT NULL AND cleaned_text != ''
            """,
            (cutoff,),
        ).fetchone()
    except sqlite3.Error:
        return None
    # Include the DB path so distinct databases (e.g. per-test tmp dirs that
    # share a doc count + timestamp) never collide on the process-global cache.
    return (_db_path_of(conn), cutoff, row[0], row[1]) if row else None


def _load_document_mentions(
    conn: sqlite3.Connection, window_days: int, now: datetime
) -> list[dict]:
    """Scan the documents corpus and emit pseudo-signals for both ticker
    mentions and keyword-detected themes — what makes the theme/asset maps
    span ALL input sources, not just the handful that have been through LLM
    signal extraction.

    Ticker mentions are direction-neutral. Keyword themes carry a
    conservative low-conviction lexical lean. Pure regex; result cached per
    corpus fingerprint so repeated calls in one build don't re-scan.
    """
    from macro_positioning.scoring.mention_extractor import extract_tickers_from_text

    if not _safe_table_exists(conn, "documents"):
        return []
    cutoff = (now - timedelta(days=window_days)).isoformat()

    fp = _doc_corpus_fingerprint(conn, cutoff)
    if fp is not None and fp in _DOC_MENTION_CACHE:
        return _DOC_MENTION_CACHE[fp]

    # Same allowlist as _load_signals: a document mention only counts toward
    # the maps if its author is one the user explicitly stated.
    allowed = seeded_author_ids(conn)
    try:
        cur = conn.execute(
            """
            SELECT source_id, author_id, COALESCE(published_at, ingested_at) AS ts,
                   cleaned_text
              FROM documents
             WHERE COALESCE(published_at, ingested_at) >= ?
               AND cleaned_text IS NOT NULL AND cleaned_text != ''
            """,
            (cutoff,),
        )
    except sqlite3.Error:
        return []

    out: list[dict] = []
    for source_id, author_id, ts, text in cur.fetchall():
        if (author_id or "") not in allowed:
            continue
        text = text or ""
        tickers = extract_tickers_from_text(text)
        kw_themes = _themes_in_text(text)
        if not tickers and not kw_themes:
            continue
        dt = _parse_iso(ts)
        if dt is None:
            continue
        src = _doc_source_key(source_id or "")

        # (a) ticker mentions → per-ticker pseudo-signals (direction-neutral)
        for tk in tickers:
            out.append({
                "signal_id":    None,
                "extracted_at": dt,
                "side":         "",
                "conviction":   0.0,
                "trust":        1.0,
                "source_slug":  src,
                "author_id":    author_id or "",
                "asset_class":  "",
                "thesis_tags":  [],
                "regime_tags":  [],
                "thesis_summary": "",
                "asset_ticker": tk,
                "mention_only": True,
            })

        # (b) keyword themes → per-theme pseudo-signals. These carry a
        # CONSERVATIVE lexical direction (low conviction) so "constructive
        # on agriculture" reads bullish, but real extracted signals always
        # outweigh them. forced_theme routes them straight to the theme in
        # aggregation (no ticker needed).
        if kw_themes:
            lean = _doc_lean(text)
            for theme in kw_themes:
                out.append({
                    "signal_id":      None,
                    "extracted_at":   dt,
                    "side":           lean,          # "" | LONG | SHORT
                    "conviction":     0.5 if lean else 0.0,
                    "trust":          1.0,
                    "source_slug":    src,
                    "author_id":      author_id or "",
                    "asset_class":    "",
                    "thesis_tags":    [],
                    "regime_tags":    [],
                    "thesis_summary": "",
                    "asset_ticker":   "",
                    "forced_theme":   theme,
                    # Counts toward volume + (if lean) the direction vote,
                    # but at low weight. Not mention_only so the vote sees it.
                    "mention_only":   lean == "",
                })

    if fp is not None:
        _DOC_MENTION_CACHE[fp] = out
        _DOC_MENTION_CACHE_ORDER.append(fp)
        if len(_DOC_MENTION_CACHE_ORDER) > _DOC_MENTION_CACHE_MAX:
            old = _DOC_MENTION_CACHE_ORDER.pop(0)
            _DOC_MENTION_CACHE.pop(old, None)
    return out


def _signal_themes(s: dict, ticker_idx: dict[str, str] | None = None) -> set[str]:
    """All themes this signal belongs to: curated sector (by ticker) ∪ real
    macro/regime tags ∪ asset-class catch-all. See module docstring.

    ticker_idx is the result of _ticker_theme_index(); passed in by callers
    so it's computed once per build rather than per signal.
    """
    if ticker_idx is None:
        ticker_idx = _ticker_theme_index()
    # Keyword-derived prose contributions name their theme directly.
    forced = s.get("forced_theme")
    if forced:
        return {forced}
    # Document ticker-mentions carry only a ticker — map it straight to a
    # theme (curated → common bucket → equities_broad default).
    if s.get("mention_only"):
        t = _theme_for_ticker(s.get("asset_ticker", ""), ticker_idx)
        return {t} if t else set()
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
    """Per-theme card for the S1 scatter map. See web/streams.jsx ThemeMap.

    Corpus = signals (carry direction) + document ticker-mentions (carry
    coverage across ALL input sources). Direction is voted from signals
    only; mentions add volume/sources but stay direction-neutral.
    """
    now = _now(now)
    signals = _load_signals(conn, _WINDOW_THEME_DAYS, now)
    mentions = _load_document_mentions(conn, _WINDOW_THEME_DAYS, now)
    corpus = signals + mentions
    if not corpus:
        return []

    ticker_idx = _ticker_theme_index()
    by_theme: dict[str, list[dict]] = defaultdict(list)
    for s in corpus:
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

        # Direction: trust*conviction-weighted vote of sides. Document
        # mentions have no side — they're skipped so they don't wash a
        # real directional signal toward "mixed".
        score = 0.0
        total_w = 0.0
        for s in sigs:
            if s.get("mention_only"):
                continue
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
    mentions = _load_document_mentions(conn, _WINDOW_THEME_DAYS, now)
    corpus = signals + mentions
    if not corpus:
        return []

    # Junk sentinel values some extractors emit when they can't resolve a
    # ticker — drop them rather than render an "N/A" bubble.
    _JUNK_TICKERS = {"", "N/A", "NA", "NONE", "NULL", "?", "TBD", "UNKNOWN"}
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for s in corpus:
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
            if s.get("mention_only"):
                continue  # mentions carry no direction
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
    # Cap the payload: there's a long tail of hundreds of one-off tickers
    # that aren't useful as scatter bubbles and bloat the SPA (the lifecycle
    # map is for the most-discussed names, not the entire mention universe).
    # The SPA's own minor-cluster rollup then folds the lower part of this.
    return out[:_ASSET_MAP_CAP]


# ---------------------------------------------------------------------------
# Breakouts — the "CHECK THIS OUT" feed (velocity + acceleration ranked)
# ---------------------------------------------------------------------------

_WINDOW_MOMENTUM_DAYS = 42   # 6 weekly buckets for slope / acceleration
_MOMENTUM_WEEKS = 6
_BREAKOUTS_CAP = 30


def _weekly_buckets(sigs: list[dict], now: datetime, n_weeks: int) -> tuple[list[int], datetime | None, set[str]]:
    """Bucket a signal list into n_weeks weekly counts (oldest -> newest)."""
    buckets = [0] * n_weeks
    first_seen: datetime | None = None
    sources: set[str] = set()
    for s in sigs:
        dt = s.get("extracted_at")
        if dt is None:
            continue
        wk = int((now - dt).total_seconds() / 86400.0 // 7)  # 0 = current week
        if 0 <= wk < n_weeks:
            buckets[n_weeks - 1 - wk] += 1
        if first_seen is None or dt < first_seen:
            first_seen = dt
        slug = s.get("source_slug") or s.get("author_id")
        if slug:
            sources.add(slug)
    return buckets, first_seen, sources


def _vote_direction(sigs: list[dict]) -> str:
    """Trust*conviction-weighted bull/bear vote; mention-only rows abstain."""
    score = 0.0
    total_w = 0.0
    for s in sigs:
        if s.get("mention_only"):
            continue
        w = max(0.01, s.get("trust", 0.0)) * max(0.0, s.get("conviction", 0.0))
        if w <= 0:
            w = max(0.01, s.get("trust", 0.0))
        total_w += w
        if s.get("side") in _BULL_SIDES:
            score += w
        elif s.get("side") in _BEAR_SIDES:
            score -= w
    if total_w > 0 and abs(score) / total_w > 0.4:
        return "bullish" if score > 0 else "bearish"
    return "mixed"


def build_breakouts(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[dict]:
    """Ranked feed of tickers + themes whose mention-rate is accelerating.

    This is the culmination signal: it says "CHECK THIS OUT" so the operator
    can verify. Momentum math lives in learning.theme_momentum; here we bucket
    the corpus by ticker and by theme over 6 weeks, score each, attach the
    context needed to verify (direction, who's calling it, weekly shape), and
    rank by breakout_score.
    """
    from macro_positioning.learning.theme_momentum import compute_momentum

    now = _now(now)
    signals = _load_signals(conn, _WINDOW_MOMENTUM_DAYS, now)
    mentions = _load_document_mentions(conn, _WINDOW_MOMENTUM_DAYS, now)
    corpus = [s for s in (signals + mentions) if s.get("extracted_at") is not None]
    if not corpus:
        return []

    ticker_idx = _ticker_theme_index()
    _JUNK = {"", "N/A", "NA", "NONE", "NULL", "?", "TBD", "UNKNOWN"}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    by_theme: dict[str, list[dict]] = defaultdict(list)
    for s in corpus:
        tk = (s.get("asset_ticker") or "").strip().upper()
        if tk and tk not in _JUNK:
            by_ticker[tk].append(s)
        for theme in _signal_themes(s, ticker_idx):
            by_theme[theme].append(s)

    out: list[dict] = []

    def _emit(kind: str, key: str, label: str, sigs: list[dict]) -> None:
        buckets, first_seen, sources = _weekly_buckets(sigs, now, _MOMENTUM_WEEKS)
        if sum(buckets) < 3:
            return
        mom = compute_momentum(buckets)
        # Only surface things actually worth a look; quiet/fading fall away.
        if mom.status in ("quiet", "fading"):
            return
        # Breadth: single-source spikes are demoted (one loud voice != a trend).
        n_sources = len(sources)
        breadth = min(1.0, 0.5 + 0.25 * n_sources)  # 1 src ->0.75, >=2 ->1.0
        adj_score = mom.breakout_score * breadth
        out.append({
            "kind": kind,
            "id": key,
            "label": label,
            "direction": _vote_direction(sigs),
            "n_sources": n_sources,
            "sources": sorted(sources)[:8],
            "mentions_by_week": buckets,
            "age_days": int((now - first_seen).total_seconds() / 86400.0) if first_seen else 0,
            "score": round(adj_score, 1),
            **mom.to_dict(),
        })

    for tk, sigs in by_ticker.items():
        _emit("asset", tk, tk, sigs)
    for theme_id, sigs in by_theme.items():
        _emit("theme", theme_id, _title_label(theme_id), sigs)

    # Rank: breakouts first, then by adjusted score.
    _rank = {"breakout": 0, "building": 1, "peaking": 2}
    out.sort(key=lambda x: (_rank.get(x["status"], 9), -x["score"]))
    return out[:_BREAKOUTS_CAP]


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


def build_source_graph(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    explicit_tiers: dict[str, int] | None = None,
) -> dict:
    now = _now(now)

    if not _safe_table_exists(conn, "input_authors"):
        return {"nodes": [], "links": []}

    # Operator-assigned tiers from config/sources.json win over the
    # trust-weight heuristic. Keyed by source_id AND slugified display name.
    # Pass `explicit_tiers={}` to force the trust-weight fallback (tests).
    try:
        from macro_positioning.ingestion.source_lifecycle import _normalize_name
        if explicit_tiers is None:
            from macro_positioning.ingestion.source_lifecycle import explicit_tier_map
            explicit_tiers = explicit_tier_map()
    except Exception:
        explicit_tiers, _normalize_name = (explicit_tiers or {}), None

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
        # Explicit operator tier wins; fall back to trust-weight heuristic.
        tier = None
        if explicit_tiers and _normalize_name is not None:
            tier = explicit_tiers.get(aid)
            if tier is None:
                tier = explicit_tiers.get(_normalize_name(name or ""))
        if tier is None:
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
    try:
        breakouts = build_breakouts(conn, now=now)
    except Exception:
        breakouts = []
    return {
        "themeMap":    theme_map,
        "assetMap":    asset_map,
        "concepts":    concepts,
        "sourceGraph": source_graph,
        "breakouts":   breakouts,
    }
