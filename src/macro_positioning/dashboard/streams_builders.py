"""Builders for the /streams SPA tab (S1 theme map, S2 concepts, S3 source graph).

Pure functions over a sqlite3.Connection so the SPA layer can call them
without owning DB lifecycle. Each builder returns JSON-serializable
dicts/lists matching the shapes the JSX already consumes (see
web/streams.jsx and web/data.mock.js streams: {...}).

No schema changes: tier and market_focus are derived in-builder; theme
ids are derived from `signals.thesis_tags_json` + `macro_regime_tags_json`.
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


def _title_label(theme_id: str) -> str:
    """uranium_energy → Uranium / energy (per brief)."""
    return theme_id.replace("_", " / ").capitalize()


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
                   thesis_summary
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
        })
    return out


def _signal_themes(s: dict) -> set[str]:
    """All theme tokens this signal touches."""
    return set(s["thesis_tags"]) | set(s["regime_tags"])


# ---------------------------------------------------------------------------
# S1 — themeMap
# ---------------------------------------------------------------------------

def build_theme_map(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[dict]:
    """Per-theme card for the S1 scatter map. See web/streams.jsx ThemeMap."""
    now = _now(now)
    signals = _load_signals(conn, _WINDOW_THEME_DAYS, now)
    if not signals:
        return []

    by_theme: dict[str, list[dict]] = defaultdict(list)
    for s in signals:
        if s["extracted_at"] is None:
            continue
        for theme in _signal_themes(s):
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
    """Returns {themeMap, concepts, sourceGraph}. Each child is empty-safe."""
    now = _now(now)
    try:
        theme_map = build_theme_map(conn, now=now)
    except Exception:
        theme_map = []
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
        "concepts":    concepts,
        "sourceGraph": source_graph,
    }
