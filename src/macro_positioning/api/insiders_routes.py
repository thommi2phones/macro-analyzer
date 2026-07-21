"""Insiders API routes.

Endpoints:
  - GET /api/insiders/lobbying-graph        — force-directed graph data
  - GET /api/insiders/lobbying-graph/side-panel
  - GET /api/insiders/theme-breakdown       — per-theme drivers (NEW)
  - GET /api/insiders/timeline              — reverse-chrono event stream (NEW)
  - GET /api/insiders/author-themes         — per-author theme concentrations (NEW)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from fastapi import APIRouter, Query

from macro_positioning.core.settings import settings


router = APIRouter(prefix="/api/insiders", tags=["insiders"])


@router.get("/lobbying-graph")
def lobbying_graph(
    period: Optional[str] = Query(None, description="e.g. 2026-Q1 — omit for all-time"),
    min_amount: float = Query(0, description="$ floor on client_paid_registrant edges"),
    focus: Optional[str] = Query(None, description="optional focus node (ego-net)"),
    edge_kinds: Optional[str] = Query(
        None,
        description=("comma-separated edge kinds to include "
                     "(default: client_paid_registrant)"),
    ),
    limit: int = Query(200, ge=1, le=2000),
):
    kinds = [k.strip() for k in (edge_kinds or "client_paid_registrant").split(",") if k.strip()]

    where = ["edge_kind IN (" + ",".join("?" * len(kinds)) + ")"]
    params: list = list(kinds)
    if period:
        where.append("period = ?")
        params.append(period)
    if min_amount > 0:
        where.append("(amount_usd IS NULL OR amount_usd >= ?)")
        params.append(min_amount)
    if focus:
        where.append("(from_node = ? OR to_node = ?)")
        params.extend([focus, focus])

    sql = (
        "SELECT from_node, to_node, edge_kind, amount_usd "
        "FROM lobbying_edges WHERE " + " AND ".join(where)
        + " ORDER BY COALESCE(amount_usd, 0) DESC "
        + f"LIMIT {int(limit)}"
    )

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    node_meta: dict[str, dict] = {}
    links: list[dict] = []
    for r in rows:
        f, t, kind, amt = r["from_node"], r["to_node"], r["edge_kind"], r["amount_usd"]
        for n in (f, t):
            if n not in node_meta:
                ns, name = n.split(":", 1) if ":" in n else ("other", n)
                node_meta[n] = {"id": n, "kind": ns, "label": name, "value": 0}
        if amt:
            node_meta[t]["value"] = (node_meta[t]["value"] or 0) + float(amt)
            node_meta[f]["value"] = (node_meta[f]["value"] or 0) + float(amt)
        links.append({
            "source": f,
            "target": t,
            "kind": kind,
            "amount_usd": amt,
        })

    if focus and focus in node_meta:
        # Pull all edges touching the focus node's neighbors in a second
        # pass so the user gets a true ego-net rather than just the
        # focus-incident edges (which a UI client would otherwise have
        # to fetch in N round-trips).
        neighbors = {l["source"] for l in links} | {l["target"] for l in links}
        if neighbors:
            extra_sql = (
                "SELECT from_node, to_node, edge_kind, amount_usd "
                "FROM lobbying_edges WHERE edge_kind IN ("
                + ",".join("?" * len(kinds)) + ")"
                + (" AND period = ?" if period else "")
                + " AND (from_node IN (" + ",".join("?" * len(neighbors)) + ")"
                + "      OR to_node IN (" + ",".join("?" * len(neighbors)) + "))"
                + f" LIMIT {int(limit)}"
            )
            extra_params: list = list(kinds)
            if period:
                extra_params.append(period)
            extra_params.extend(neighbors)
            extra_params.extend(neighbors)
            with sqlite3.connect(settings.sqlite_path) as conn:
                conn.row_factory = sqlite3.Row
                extra = conn.execute(extra_sql, extra_params).fetchall()
            seen_links = {(l["source"], l["target"], l["kind"]) for l in links}
            for r in extra:
                key = (r["from_node"], r["to_node"], r["edge_kind"])
                if key in seen_links:
                    continue
                for n in (r["from_node"], r["to_node"]):
                    if n not in node_meta:
                        ns, name = n.split(":", 1) if ":" in n else ("other", n)
                        node_meta[n] = {"id": n, "kind": ns, "label": name, "value": 0}
                links.append({
                    "source": r["from_node"],
                    "target": r["to_node"],
                    "kind": r["edge_kind"],
                    "amount_usd": r["amount_usd"],
                })

    return {
        "nodes": list(node_meta.values()),
        "links": links,
        "period": period,
        "focus": focus,
        "edge_kinds": kinds,
        "min_amount": min_amount,
    }


@router.get("/lobbying-graph/side-panel")
def lobbying_side_panel(
    focus: str,
    period: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
):
    """Top issues + top targeted agencies for a focus node within a period."""
    params: list = [focus, focus]
    where_period = ""
    if period:
        where_period = " AND period = ?"
        params.append(period)

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row

        issues_sql = (
            "SELECT to_node AS node, COUNT(*) AS n "
            "FROM lobbying_edges "
            "WHERE edge_kind='filing_covers_issue' "
            "AND (from_node = ? OR to_node = ?)"
            + where_period
            + " GROUP BY to_node ORDER BY n DESC LIMIT ?"
        )
        issues = [dict(r) for r in conn.execute(issues_sql, [*params, limit]).fetchall()]

        agencies_sql = (
            "SELECT to_node AS node, COUNT(*) AS n "
            "FROM lobbying_edges "
            "WHERE edge_kind='filing_targets_agency' "
            "AND (from_node = ? OR to_node = ?)"
            + where_period
            + " GROUP BY to_node ORDER BY n DESC LIMIT ?"
        )
        agencies = [dict(r) for r in conn.execute(agencies_sql, [*params, limit]).fetchall()]

        lobbyists_sql = (
            "SELECT to_node AS node, COUNT(*) AS n "
            "FROM lobbying_edges "
            "WHERE edge_kind='registrant_employs_lobbyist' "
            "AND (from_node = ?)"
            + where_period
            + " GROUP BY to_node ORDER BY n DESC LIMIT ?"
        )
        lobbyists = [dict(r) for r in conn.execute(lobbyists_sql, [focus, *(params[2:] if period else []), limit]).fetchall()]

    return {
        "focus": focus,
        "period": period,
        "top_issues": issues,
        "top_agencies": agencies,
        "lobbyists": lobbyists,
    }


# ── Theme breakdown ─────────────────────────────────────────────────────────


# Channel slug -> readable label rendered in the SPA.
_CHANNEL_LABELS = {
    "gov-insider": "Congress",
    "corp-insider": "Corp insiders",
    "large-holder": "13D/13F",
    "fed-spend": "Federal spend",
    "lobbying": "Lobbying",
    "social": "Social",
}


def _ticker_to_themes() -> tuple[dict, dict]:
    """Return (asset_themes_cfg, ticker -> [theme_keys])."""
    path = settings.base_dir / "config" / "asset_themes.json"
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, {}
    out: dict[str, list[str]] = {}
    for theme_key, theme_def in (cfg.get("themes") or {}).items():
        for ticker in theme_def.get("watchlist_tickers") or []:
            out.setdefault(ticker.upper(), []).append(theme_key)
    return cfg, out


@router.get("/theme-breakdown")
def theme_breakdown(
    window_days: int = Query(30, ge=1, le=365),
    top_n_per_theme: int = Query(5, ge=1, le=20),
):
    """Per-theme breakdown of who's driving it.

    For each theme: ticker mentions from insider docs (grouped by channel
    + author), plus the LDA lobbying contribution if any. The SPA renders
    one card per theme with the top author drivers.
    """
    cfg, t2t = _ticker_to_themes()
    if not t2t:
        return {"themes": [], "window_days": window_days}

    # Pull recent insider docs (manual:*). Stream them through the same
    # ticker extractor used elsewhere so theme attribution stays aligned
    # with how scoring sees them.
    from macro_positioning.scoring.mention_extractor import (
        extract_tickers_from_text, insider_source_weight,
    )
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT d.document_id, d.source_id, d.author_id, d.author,
                   d.cleaned_text, d.raw_text, d.published_at, d.ingested_at,
                   d.user_metadata_json
            FROM documents d
            WHERE d.source_id LIKE 'manual:%'
              AND COALESCE(d.published_at, d.ingested_at) >= ?
            ORDER BY COALESCE(d.published_at, d.ingested_at) DESC
            """,
            (cutoff,),
        ).fetchall()

    # theme -> { 'mentions': float, 'by_channel': {channel: float},
    #            'by_author': {(author_id, author, channel): {n, last_at}} }
    per_theme: dict[str, dict] = {}
    for r in rows:
        text = (r["cleaned_text"] or r["raw_text"] or "")
        tickers = extract_tickers_from_text(text)
        if not tickers:
            continue
        source_id = r["source_id"] or ""
        weight = insider_source_weight(source_id)
        # Channel slug: between 'manual:' and the next ':'.
        body = source_id[len("manual:"):] if source_id.startswith("manual:") else ""
        channel = body.split(":", 1)[0] if ":" in body else body
        author = r["author"] or "Unknown"
        author_id = r["author_id"] or "anon"
        last_at = r["published_at"] or r["ingested_at"]
        for ticker in tickers:
            for theme in t2t.get(ticker.upper(), []):
                bucket = per_theme.setdefault(theme, {
                    "mentions": 0.0, "by_channel": {}, "by_author": {},
                })
                bucket["mentions"] += weight
                bucket["by_channel"][channel] = bucket["by_channel"].get(channel, 0.0) + weight
                key = (author_id, author, channel)
                a = bucket["by_author"].setdefault(key, {"n": 0, "last_at": last_at})
                a["n"] += 1
                if last_at and (a["last_at"] is None or last_at > a["last_at"]):
                    a["last_at"] = last_at

    # LDA contribution per theme (one query, reuses the same logic the
    # scorer applies in `_lda_issue_theme_signal`).
    from macro_positioning.scoring.runner import (
        _load_lda_issue_themes_cfg, _lda_issue_theme_signal,
    )
    lda_per_theme = _lda_issue_theme_signal(cfg, _load_lda_issue_themes_cfg())

    out_themes = []
    for theme_key, theme_def in (cfg.get("themes") or {}).items():
        bucket = per_theme.get(theme_key, {})
        authors = sorted(
            [
                {"author_id": k[0], "author": k[1], "channel": k[2],
                 "channel_label": _CHANNEL_LABELS.get(k[2], k[2]),
                 "n_mentions": v["n"], "last_at": v["last_at"]}
                for k, v in (bucket.get("by_author") or {}).items()
            ],
            key=lambda x: (-x["n_mentions"], x["author"]),
        )[:top_n_per_theme]

        by_channel = [
            {"channel": ch, "channel_label": _CHANNEL_LABELS.get(ch, ch),
             "weight": round(w, 2)}
            for ch, w in sorted(
                (bucket.get("by_channel") or {}).items(),
                key=lambda x: -x[1],
            )
        ]
        out_themes.append({
            "theme": theme_key,
            "label": (theme_def.get("core_thesis") or theme_key)[:80],
            "insider_score": round(bucket.get("mentions", 0.0), 2),
            "lda_score": round(lda_per_theme.get(theme_key, 0.0), 2),
            "total": round(
                bucket.get("mentions", 0.0) + lda_per_theme.get(theme_key, 0.0),
                2,
            ),
            "by_channel": by_channel,
            "top_authors": authors,
        })
    out_themes.sort(key=lambda x: -x["total"])
    return {"themes": out_themes, "window_days": window_days}


# ── Activity timeline ──────────────────────────────────────────────────────


_CHANNEL_TO_PREFIX = {
    "gov_insider": "manual:gov-insider:",
    "corp_insider": "manual:corp-insider:",
    "large_holder": "manual:large-holder:",
    "fed_spend": "manual:fed-spend:",
    "lobbying": "manual:lobbying:",
    "social": "manual:social:",
}


@router.get("/timeline")
def timeline(
    channels: Optional[str] = Query(
        None,
        description=("comma-separated channel slugs from "
                     "gov_insider, corp_insider, large_holder, fed_spend, lobbying, social"),
    ),
    since: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=500),
):
    """Reverse-chrono stream of insider events.

    Returned shape: `{events: [...]}` where each event carries
    `{document_id, channel, channel_label, source_id, author, author_id,
       ticker, side, conviction, amount_range, transaction_type, note,
       source_url, raw_text, filed_at}`.
    """
    requested = []
    if channels:
        for c in channels.split(","):
            slug = c.strip()
            if slug in _CHANNEL_TO_PREFIX:
                requested.append(_CHANNEL_TO_PREFIX[slug])
    if not requested:
        requested = list(_CHANNEL_TO_PREFIX.values())

    like_clauses = " OR ".join(["d.source_id LIKE ?"] * len(requested))
    params: list = [p + "%" for p in requested]
    where = f"({like_clauses})"
    if since:
        where += " AND COALESCE(d.published_at, d.ingested_at) >= ?"
        params.append(since)

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT d.document_id, d.source_id, d.author_id, d.author,
                   d.raw_text, d.cleaned_text, d.user_metadata_json,
                   d.published_at, d.ingested_at,
                   a.channel AS author_channel, a.channel_type
            FROM documents d
            LEFT JOIN input_authors a ON a.author_id = d.author_id
            WHERE {where}
            ORDER BY COALESCE(d.published_at, d.ingested_at) DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

    events: list[dict] = []
    for r in rows:
        meta = {}
        try:
            meta = json.loads(r["user_metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            meta = {}
        resolved = meta.get("resolved", {}) or {}
        user_meta = meta.get("user", {}) or {}
        source_id = r["source_id"] or ""
        body = source_id[len("manual:"):] if source_id.startswith("manual:") else ""
        channel_slug = body.split(":", 1)[0] if ":" in body else body
        # Normalize back to the underscore convention.
        channel = channel_slug.replace("-", "_")

        # Best-effort source_url scan from the body (the funnel writes
        # "Source: <url>" lines for events that supply attachment_url).
        text = r["cleaned_text"] or r["raw_text"] or ""
        source_url = None
        for line in (text or "").splitlines():
            line = line.strip()
            if line.startswith("Source: "):
                source_url = line[len("Source: "):].strip()
                break

        events.append({
            "document_id": r["document_id"],
            "channel": channel,
            "channel_label": _CHANNEL_LABELS.get(channel_slug, channel),
            "source_id": source_id,
            "author": r["author"],
            "author_id": r["author_id"],
            "ticker": resolved.get("ticker") or user_meta.get("ticker"),
            "side": resolved.get("side") or user_meta.get("side"),
            "conviction": resolved.get("conviction") or user_meta.get("conviction"),
            "transaction_type": None,  # not stored separately; comes from note
            "note": resolved.get("note") or user_meta.get("note"),
            "raw_text": r["raw_text"],
            "source_url": source_url,
            "filed_at": r["published_at"] or r["ingested_at"],
        })
    return {"events": events}


# ── Per-author theme leaderboard ───────────────────────────────────────────


@router.get("/author-themes")
def author_themes_endpoint(
    min_trust: float = Query(1.0, ge=0.0, le=3.0),
    window_days: int = Query(90, ge=1, le=365),
    limit: int = Query(40, ge=1, le=200),
):
    """Surface `learning/source_themes.trusted_source_themes()`.

    Returns the per-author concentration that the per-author hit-rate
    machinery is heading toward — top tickers, bias distribution, recent
    high-conviction picks — sorted by trust_weight then activity.
    """
    try:
        from macro_positioning.learning import source_themes as st_mod
    except ImportError:
        return {"authors": [], "error": "learning.source_themes not available"}

    try:
        rows = st_mod.trusted_source_themes(
            min_trust=min_trust, window_days=window_days,
        )
    except Exception as exc:  # noqa: BLE001
        return {"authors": [], "error": str(exc)}

    out = []
    for r in (rows or [])[:limit]:
        out.append({
            "author_id": r.author_id,
            "display_name": r.display_name,
            "channel": r.channel,
            "trust_weight": r.trust_weight,
            "n_drops": r.n_drops,
            "n_with_vision": r.n_with_vision,
            "top_tickers": [{"ticker": t, "n": n} for t, n in (r.top_tickers or [])],
            "bias_distribution": r.bias_distribution,
            "top_setups": r.top_setups,
            "top_indicators": r.top_indicators,
            "high_conviction_tickers": r.high_conviction_tickers,
        })
    return {"authors": out, "window_days": window_days, "min_trust": min_trust}
