"""Tests for the insider→themes integration.

Covers:
  - insider_source_weight() returns the expected multipliers
  - count_mentions() applies the multiplier on top of recency × freshness
  - _lda_issue_theme_signal() rolls lobbying_edges into theme buckets
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.scoring.mention_extractor import (
    count_mentions,
    insider_source_weight,
)
from macro_positioning.scoring.runner import (
    _lda_issue_theme_signal,
    _load_lda_issue_themes_cfg,
)


# ── source weight ──────────────────────────────────────────────────────────


def test_insider_source_weight_buckets():
    # Non-insider sources unchanged at 1.0
    assert insider_source_weight("") == 1.0
    assert insider_source_weight("rss:bloomberg") == 1.0
    # Insider channels match docs
    assert insider_source_weight("manual:large-holder:scion") == 2.0
    assert insider_source_weight("manual:corp-insider:cook-cody") == 1.7
    assert insider_source_weight("manual:gov-insider:nancy-pelosi") == 1.5
    assert insider_source_weight("manual:fed-spend:lockheed-martin") == 0.8
    assert insider_source_weight("manual:lobbying:morrison") == 0.6
    assert insider_source_weight("manual:social:wsb") == 0.5
    # Unknown manual channel falls back to 1.0
    assert insider_source_weight("manual:unknown:thing") == 1.0


def test_count_mentions_applies_insider_multiplier():
    # Same content, same published_at, different source. The 13D source
    # (large-holder = 2.0x) should weight 2x the news source (1.0x).
    now = datetime.now(UTC)
    doc_news = {
        "source_id": "rss:bloomberg",
        "title": "headline",
        "cleaned_text": "Big move in $NVDA today",
        "published_at": now.isoformat(),
    }
    doc_insider = {
        "source_id": "manual:large-holder:scion",
        "title": "filing",
        "cleaned_text": "Scion files 13D on $NVDA",
        "published_at": now.isoformat(),
    }

    wm_news = count_mentions(
        [doc_news], window_days=7, now=now, apply_source_freshness=False,
    )
    wm_insider = count_mentions(
        [doc_insider], window_days=7, now=now, apply_source_freshness=False,
    )

    score_news = next(c.weighted_score for c in wm_news.counts if c.ticker == "NVDA")
    score_insider = next(c.weighted_score for c in wm_insider.counts if c.ticker == "NVDA")
    assert score_insider == pytest.approx(score_news * 2.0, rel=1e-6)


def test_count_mentions_custom_source_weight_fn():
    """Caller can override the default for offline tests / experiments."""
    now = datetime.now(UTC)
    doc = {
        "source_id": "manual:gov-insider:pelosi",
        "cleaned_text": "$NVDA",
        "published_at": now.isoformat(),
    }
    wm_default = count_mentions(
        [doc], window_days=7, now=now, apply_source_freshness=False,
    )
    wm_flat = count_mentions(
        [doc], window_days=7, now=now, apply_source_freshness=False,
        source_weight_fn=lambda s: 1.0,
    )
    s_default = next(c.weighted_score for c in wm_default.counts if c.ticker == "NVDA")
    s_flat = next(c.weighted_score for c in wm_flat.counts if c.ticker == "NVDA")
    # Default applies 1.5 (gov-insider); flat is 1.0.
    assert s_default == pytest.approx(s_flat * 1.5, rel=1e-6)


# ── LDA issue map ──────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "themes.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///themes.db")
    # Re-use the repo's config file by symlinking it into the tmp base_dir.
    (tmp_path / "config").mkdir(exist_ok=True)
    real = Path(__file__).resolve().parents[1] / "config" / "lda_issue_themes.json"
    (tmp_path / "config" / "lda_issue_themes.json").write_text(real.read_text())
    real_at = Path(__file__).resolve().parents[1] / "config" / "asset_themes.json"
    (tmp_path / "config" / "asset_themes.json").write_text(real_at.read_text())
    return db_path


def _insert_edge(db, filing_id, issue):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO lobbying_edges (filing_id, period, from_node, to_node, edge_kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (filing_id, "2026-Q1", "client:X", f"issue:{issue}", "filing_covers_issue"),
        )
        conn.commit()


def test_lda_issue_theme_signal_rolls_up_mapped_issues(db):
    import json
    # Two filings on Energy/Nuclear -> uranium + energy themes.
    _insert_edge(db, "f1", "Energy/Nuclear")
    _insert_edge(db, "f2", "Energy/Nuclear")
    # One Defense filing -> defense.
    _insert_edge(db, "f3", "Defense")
    # One unmapped issue -> contributes nothing.
    _insert_edge(db, "f4", "Tobacco")

    themes_cfg = json.loads((db.parent / "config" / "asset_themes.json").read_text())
    lda_cfg = _load_lda_issue_themes_cfg()
    out = _lda_issue_theme_signal(themes_cfg, lda_cfg)

    assert out.get("uranium") == 2.0
    assert out.get("energy") == 2.0
    assert out.get("defense") == 1.0
    assert "tobacco" not in out  # not a theme; never contributes


def test_lda_issue_theme_signal_safe_when_table_absent(tmp_path, monkeypatch):
    """First-boot DB without lobbying_edges: returns {} silently."""
    # Settings point at a fresh empty DB with no schema applied.
    db_path = tmp_path / "empty.db"
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///empty.db")
    sqlite3.connect(db_path).close()
    import json
    real = Path(__file__).resolve().parents[1] / "config" / "asset_themes.json"
    themes_cfg = json.loads(real.read_text())
    lda_cfg = _load_lda_issue_themes_cfg()
    out = _lda_issue_theme_signal(themes_cfg, lda_cfg)
    assert out == {}
