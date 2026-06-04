"""Tests for dashboard/streams_builders.py — S1/S2/S3 builders."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.dashboard.streams_builders import (
    build_asset_map,
    build_concepts,
    build_source_graph,
    build_streams_section,
    build_theme_map,
    _derive_market_focus,
    _is_real_theme,
    _trust_to_tier,
    _title_label,
)


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "streams.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_document(conn, doc_id: str, source_id: str = "src_a", body: str = "Body text about something."):
    conn.execute(
        """INSERT INTO documents
           (document_id, source_id, title, published_at, content_type,
            raw_text, cleaned_text, tags_json, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_id, source_id, "t", NOW.isoformat(), "manual",
         body, body, "[]", NOW.isoformat()),
    )


def _insert_signal(
    conn,
    *,
    side: str = "LONG",
    extracted_at: datetime | None = None,
    thesis_tags: list[str] | None = None,
    macro_tags: list[str] | None = None,
    source_slug: str = "doomberg",
    author_id: str = "doomberg",
    trust: float = 1.0,
    conviction: float = 3.0,
    ticker: str = "URA",
    asset_class: str = "equity",
    thesis_summary: str = "",
):
    sid = f"sig-{uuid.uuid4().hex[:8]}"
    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    # The signals table has a FK to documents, but sqlite doesn't enforce
    # FKs without a PRAGMA. Still, insert a doc for realism so the synopsis
    # fallback can read cleaned_text.
    _insert_document(conn, doc_id, source_id=source_slug, body=thesis_summary or "body")
    conn.execute(
        """INSERT INTO signals
           (signal_id, document_id, extracted_at, asset_ticker, asset_class,
            side, conviction, thesis_tags_json, macro_regime_tags_json,
            thesis_summary, source_slug, author_id, author_trust_weight,
            extractor_name, extractor_version, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sid,
            doc_id,
            (extracted_at or NOW).isoformat(),
            ticker,
            asset_class,
            side,
            conviction,
            json.dumps(thesis_tags or []),
            json.dumps(macro_tags or []),
            thesis_summary,
            source_slug,
            author_id,
            trust,
            "test",
            "v0",
            "active",
        ),
    )


def _insert_author(conn, author_id: str, display_name: str = None, trust: float = 1.0,
                   last_seen: datetime | None = None):
    conn.execute(
        """INSERT INTO input_authors (author_id, display_name, channel, last_seen_at, trust_weight)
           VALUES (?, ?, ?, ?, ?)""",
        (author_id, display_name or author_id, "manual", (last_seen or NOW).isoformat(), trust),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_trust_to_tier_thresholds():
    assert _trust_to_tier(1.5) == 0
    assert _trust_to_tier(1.4) == 0
    assert _trust_to_tier(1.2) == 1
    assert _trust_to_tier(1.0) == 2
    assert _trust_to_tier(0.6) == 3
    assert _trust_to_tier(0.2) == 4
    assert _trust_to_tier(None) == 2


def test_derive_market_focus_tokens_win_over_asset_class():
    assert _derive_market_focus(["equity"], ["uranium", "energy"]) == "energy"
    assert _derive_market_focus(["equity"], []) == "equities"
    assert _derive_market_focus([], []) == "macro"
    assert _derive_market_focus(["crypto"], []) == "crypto"


def test_title_label():
    assert _title_label("uranium_energy") == "Uranium / energy"


def test_is_real_theme_filters_technical_patterns_and_sentiment():
    # Composite tokens whose components are ALL noise → dropped
    assert _is_real_theme("technical_breakout") is False
    assert _is_real_theme("wedge_pattern") is False
    assert _is_real_theme("social_media_sentiment") is False
    assert _is_real_theme("trending") is False
    assert _is_real_theme("bearish_pattern") is False
    assert _is_real_theme("retail_flow") is False
    # Real macro/sector themes survive
    assert _is_real_theme("uranium_energy") is True
    assert _is_real_theme("ai_capex") is True
    assert _is_real_theme("gold") is True
    # Single-token noise dropped
    assert _is_real_theme("momentum") is False
    # Empty / None
    assert _is_real_theme("") is False
    assert _is_real_theme(None) is False  # type: ignore[arg-type]


def test_theme_map_excludes_technical_pattern_tags(tmp_path: Path):
    conn = _conn(tmp_path)
    for _ in range(4):
        _insert_signal(conn, thesis_tags=["technical_breakout"],
                       extracted_at=NOW - timedelta(days=1))
    for _ in range(4):
        _insert_signal(conn, thesis_tags=["uranium"],
                       extracted_at=NOW - timedelta(days=1))
    conn.commit()
    themes = build_theme_map(conn, now=NOW)
    ids = {t["id"] for t in themes}
    assert "uranium" in ids
    assert "technical_breakout" not in ids


# ---------------------------------------------------------------------------
# Empty DB
# ---------------------------------------------------------------------------

def test_empty_db_returns_empty_payload(tmp_path: Path):
    conn = _conn(tmp_path)
    # initialize_database seeds the known-authors picklist (Feather Hands,
    # Stock Unlocked, etc.) with last_seen_at = wall-clock now. Wipe it so
    # "no signals, no authors" returns the truly empty payload.
    conn.execute("DELETE FROM input_authors")
    conn.commit()
    out = build_streams_section(conn, now=NOW)
    assert out == {"themeMap": [], "assetMap": [], "concepts": [], "sourceGraph": {"nodes": [], "links": []}}


# ---------------------------------------------------------------------------
# S1 — themeMap
# ---------------------------------------------------------------------------

def test_theme_map_filters_low_mention_themes(tmp_path: Path):
    conn = _conn(tmp_path)
    # Only 2 mentions of "rare_theme" — below the 3-mention floor.
    for _ in range(2):
        _insert_signal(conn, thesis_tags=["rare_theme"], extracted_at=NOW - timedelta(days=1))
    conn.commit()
    assert build_theme_map(conn, now=NOW) == []


def test_theme_map_direction_bullish_when_sides_aligned(tmp_path: Path):
    conn = _conn(tmp_path)
    for _ in range(4):
        _insert_signal(
            conn,
            side="LONG",
            thesis_tags=["uranium_energy"],
            extracted_at=NOW - timedelta(days=2),
            trust=1.2,
            conviction=3.0,
        )
    conn.commit()
    themes = build_theme_map(conn, now=NOW)
    assert len(themes) == 1
    t = themes[0]
    assert t["id"] == "uranium_energy"
    assert t["label"] == "Uranium / energy"
    assert t["direction"] == "bullish"
    assert t["age_days"] >= 0
    assert sum(t["mentions_by_week"]) == 4
    assert "doomberg" in t["sources"]


def test_theme_map_direction_mixed_when_split(tmp_path: Path):
    conn = _conn(tmp_path)
    for _ in range(3):
        _insert_signal(conn, side="LONG", thesis_tags=["foo"], extracted_at=NOW - timedelta(days=1))
    for _ in range(3):
        _insert_signal(conn, side="SHORT", thesis_tags=["foo"], extracted_at=NOW - timedelta(days=1))
    conn.commit()
    themes = build_theme_map(conn, now=NOW)
    assert len(themes) == 1
    assert themes[0]["direction"] == "mixed"


def test_theme_map_normalizes_tag_tokens(tmp_path: Path):
    conn = _conn(tmp_path)
    # Mixed-case + spaces → snake_case
    for _ in range(3):
        _insert_signal(conn, thesis_tags=["Uranium Energy"], extracted_at=NOW - timedelta(days=1))
    conn.commit()
    themes = build_theme_map(conn, now=NOW)
    assert themes[0]["id"] == "uranium_energy"


# ---------------------------------------------------------------------------
# S2 — concepts
# ---------------------------------------------------------------------------

def test_concepts_filtered_by_novelty_and_velocity(tmp_path: Path):
    conn = _conn(tmp_path)
    # Fresh, high-velocity theme: many recent mentions, none earlier
    for _ in range(8):
        _insert_signal(
            conn,
            thesis_tags=["power_grid"],
            extracted_at=NOW - timedelta(days=1),
            thesis_summary="Power grid bottlenecks; transformer lead times stretching to 220 weeks.",
        )
    conn.commit()
    cs = build_concepts(conn, now=NOW)
    assert len(cs) == 1
    c = cs[0]
    assert c["id"] == "power_grid"
    assert c["novelty"] > 0.7
    assert c["velocity"] > 0.4
    assert c["items_count"] == 8
    assert c["synopsis"].startswith("Power grid")


def test_concepts_excludes_stale_themes(tmp_path: Path):
    conn = _conn(tmp_path)
    # All mentions are old enough that novelty drops below 0.7
    for _ in range(5):
        _insert_signal(conn, thesis_tags=["old_theme"], extracted_at=NOW - timedelta(days=20))
    conn.commit()
    assert build_concepts(conn, now=NOW) == []


# ---------------------------------------------------------------------------
# S3 — sourceGraph
# ---------------------------------------------------------------------------

def test_source_graph_nodes_match_recent_authors(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_author(conn, "doomberg", "Doomberg", trust=1.5, last_seen=NOW - timedelta(days=1))
    _insert_author(conn, "stale_author", "Stale", trust=1.0, last_seen=NOW - timedelta(days=180))
    _insert_author(conn, "newbie", "Newbie", trust=None, last_seen=NOW - timedelta(days=2))
    _insert_signal(conn, author_id="doomberg", thesis_tags=["uranium"],
                   extracted_at=NOW - timedelta(days=2))
    conn.commit()

    graph = build_source_graph(conn, now=NOW)
    ids = {n["id"] for n in graph["nodes"]}
    assert "doomberg" in ids
    assert "newbie" in ids
    assert "stale_author" not in ids  # outside 90d window

    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["doomberg"]["tier"] == 0  # trust >= 1.4
    assert by_id["doomberg"]["market_focus"] == "energy"  # uranium token
    assert by_id["newbie"]["tier"] == 2  # NULL trust → tier 2 baseline
    # weight is normalized into [0, 1]
    assert 0.0 <= by_id["doomberg"]["weight"] <= 1.0


def test_source_graph_links_only_between_known_nodes(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_author(conn, "a", trust=1.0, last_seen=NOW)
    _insert_author(conn, "b", trust=1.0, last_seen=NOW)
    # Echo ties via trade_reviews.sources_credited_json
    for cid, sids in [("r1", ["a", "b"]), ("r2", ["a", "b"]),
                      ("r3", ["a", "unknown_node"])]:
        conn.execute(
            """INSERT INTO trade_reviews
               (review_id, trade_id, completed_at, sources_credited_json)
               VALUES (?, ?, ?, ?)""",
            (cid, f"trade-{cid}", NOW.isoformat(), json.dumps(sids)),
        )
    conn.commit()

    graph = build_source_graph(conn, now=NOW)
    pairs = [(l["source"], l["target"]) for l in graph["links"]]
    assert ("a", "b") in pairs or ("b", "a") in pairs
    flat = [n for p in pairs for n in p]
    assert "unknown_node" not in flat


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def test_build_streams_section_returns_all_keys(tmp_path: Path):
    conn = _conn(tmp_path)
    out = build_streams_section(conn, now=NOW)
    assert set(out.keys()) == {"themeMap", "assetMap", "concepts", "sourceGraph"}


# ---------------------------------------------------------------------------
# Asset map
# ---------------------------------------------------------------------------

def test_asset_map_aggregates_per_ticker(tmp_path: Path):
    conn = _conn(tmp_path)
    for _ in range(4):
        _insert_signal(conn, ticker="URA", side="LONG",
                       extracted_at=NOW - timedelta(days=1),
                       trust=1.2, conviction=3.0)
    for _ in range(3):
        _insert_signal(conn, ticker="GLD", side="SHORT",
                       extracted_at=NOW - timedelta(days=1),
                       trust=1.0, conviction=3.0)
    # Below 3-mention floor — should be dropped
    _insert_signal(conn, ticker="TSLA", extracted_at=NOW - timedelta(days=1))
    conn.commit()

    assets = build_asset_map(conn, now=NOW)
    ids = {a["id"] for a in assets}
    assert "URA" in ids
    assert "GLD" in ids
    assert "TSLA" not in ids
    by_id = {a["id"]: a for a in assets}
    assert by_id["URA"]["direction"] == "bullish"
    assert by_id["URA"]["label"] == "URA"
    assert by_id["GLD"]["direction"] == "bearish"


def test_asset_map_empty_when_no_signals(tmp_path: Path):
    conn = _conn(tmp_path)
    assert build_asset_map(conn, now=NOW) == []
