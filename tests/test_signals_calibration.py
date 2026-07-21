"""Trust-weight calibration loop tests."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.signal_calibration import (
    _is_hit,
    _outcome_direction,
    load_channel_trust_weight,
    recompute_trust_weights,
    update_weight,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "calib.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///calib.db")
    return db_path


# ── Pure functions ─────────────────────────────────────────────────────────


def test_outcome_direction_thresholds():
    assert _outcome_direction(2.5, neutral_band=0.5) == "bullish_outcome"
    assert _outcome_direction(-2.5, neutral_band=0.5) == "bearish_outcome"
    assert _outcome_direction(0.3, neutral_band=0.5) == "neutral_outcome"
    assert _outcome_direction(None, neutral_band=0.5) == "neutral_outcome"


def test_is_hit_long_signal():
    assert _is_hit("LONG", "bullish_outcome") is True
    assert _is_hit("ADD", "bullish_outcome") is True
    assert _is_hit("LONG", "bearish_outcome") is False
    assert _is_hit("LONG", "neutral_outcome") is None


def test_is_hit_short_signal():
    assert _is_hit("SHORT", "bearish_outcome") is True
    assert _is_hit("HEDGE", "bearish_outcome") is True
    assert _is_hit("SHORT", "bullish_outcome") is False


def test_is_hit_exit_signal():
    # EXIT "wins" when the trade was a loser
    assert _is_hit("EXIT", "bearish_outcome") is True
    assert _is_hit("EXIT", "bullish_outcome") is False


def test_is_hit_ignored_sides():
    assert _is_hit("WATCH", "bullish_outcome") is None
    assert _is_hit("AVOID", "bearish_outcome") is None


def test_update_weight_linear():
    # precision=0.5 → no change
    assert update_weight(1.0, 0.5) == pytest.approx(1.0)
    # precision=1.0 with alpha=0.5 → +0.5
    assert update_weight(1.0, 1.0, alpha=0.5) == pytest.approx(1.5)
    # precision=0.0 with alpha=0.5 → -0.5
    assert update_weight(1.0, 0.0, alpha=0.5) == pytest.approx(0.5)
    # Clamp to ceiling
    assert update_weight(2.4, 1.0, alpha=1.0) == 2.5
    # Clamp to floor
    assert update_weight(0.5, 0.0, alpha=1.0) == 0.4
    # None precision → no change
    assert update_weight(1.3, None) == 1.3


# ── End-to-end calibration over a tiny DB ──────────────────────────────────


def _insert_asset(db_path: Path, ticker: str = "AAPL") -> str:
    asset_id = f"asset-{ticker.lower()}"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class) "
            "VALUES (?, ?, ?, 'equity')",
            (asset_id, ticker, ticker),
        )
        conn.commit()
    return asset_id


def _insert_author(db_path: Path, author_id: str, trust: float = 1.0) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO input_authors
               (author_id, display_name, channel, trust_weight, first_seen_at, last_seen_at)
               VALUES (?, ?, 'test', ?, ?, ?)""",
            (author_id, author_id, trust, "2026-01-01", "2026-06-01"),
        )
        conn.commit()


def _insert_doc(db_path: Path, doc_id: str = "doc-1") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO documents
               (document_id, source_id, title, published_at, content_type,
                raw_text, cleaned_text, tags_json, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (doc_id, "manual:x", "t", "2026-01-01", "manual_note",
             "raw", "clean", "{}", "2026-01-01"),
        )
        conn.commit()


def _insert_signal(
    db_path: Path,
    *,
    asset_ticker: str,
    side: str,
    author_id: str,
    channel: str,
    extracted_at: datetime,
    document_id: Optional[str] = None,
) -> str:
    doc_id = document_id or f"doc-{uuid.uuid4().hex[:8]}"
    _insert_doc(db_path, doc_id)
    sig_id = uuid.uuid4().hex
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO signals (
                signal_id, document_id, extracted_at, asset_ticker,
                side, conviction, source_slug, source_channel, author_id,
                extractor_name, extractor_version, status, weighted_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (sig_id, doc_id, extracted_at.isoformat(), asset_ticker,
             side, 3.0, "manual", channel, author_id,
             "insider_extractor", "v1", 3.0),
        )
        conn.commit()
    return sig_id


def _insert_trade(
    db_path: Path,
    *,
    asset_id: str,
    entry_date: datetime,
    pnl_percent: float,
) -> str:
    trade_id = uuid.uuid4().hex
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO trades (
                trade_id, asset_id, entry_date, entry_price,
                position_size, stop_loss, status, pnl_percent
            ) VALUES (?, ?, ?, ?, ?, ?, 'closed', ?)""",
            (trade_id, asset_id, entry_date.isoformat(), 100.0, 1.0, 95.0,
             pnl_percent),
        )
        conn.commit()
    return trade_id


def test_calibration_promotes_accurate_author(db):
    asset_id = _insert_asset(db, "AAPL")
    _insert_author(db, "good_author", trust=1.0)
    _insert_author(db, "bad_author", trust=1.0)

    # Two well-separated time blocks so each author's signals only link
    # to its own trades (default link_window_days=30).
    good_block = datetime(2026, 3, 15, tzinfo=UTC)
    bad_block = datetime(2026, 6, 1, tzinfo=UTC)   # ~78d after good_block

    # good_author: 3 LONG signals on AAPL → 3 winning trades shortly after
    for i in range(3):
        _insert_signal(db, asset_ticker="AAPL", side="LONG",
                       author_id="good_author", channel="gov_insider",
                       extracted_at=good_block - timedelta(days=2 + i),
                       document_id=f"doc-good-{i}")
        _insert_trade(db, asset_id=asset_id,
                      entry_date=good_block + timedelta(days=i),
                      pnl_percent=5.0 + i)

    # bad_author: 3 LONG signals → 3 losing trades shortly after
    for i in range(3):
        _insert_signal(db, asset_ticker="AAPL", side="LONG",
                       author_id="bad_author", channel="social",
                       extracted_at=bad_block - timedelta(days=2 + i),
                       document_id=f"doc-bad-{i}")
        _insert_trade(db, asset_id=asset_id,
                      entry_date=bad_block + timedelta(days=i),
                      pnl_percent=-3.0 - i)

    run = recompute_trust_weights(db_path=db, min_signals_for_update=1)
    assert run.weight_updates_authors >= 2

    with sqlite3.connect(db) as conn:
        good = conn.execute(
            "SELECT trust_weight FROM input_authors WHERE author_id='good_author'"
        ).fetchone()[0]
        bad = conn.execute(
            "SELECT trust_weight FROM input_authors WHERE author_id='bad_author'"
        ).fetchone()[0]
    assert good > 1.0
    assert bad < 1.0


def test_calibration_history_recorded(db):
    asset_id = _insert_asset(db, "MSFT")
    _insert_author(db, "alice", trust=1.0)
    entry = datetime(2026, 5, 10, tzinfo=UTC)
    extracted = entry - timedelta(days=2)

    _insert_signal(db, asset_ticker="MSFT", side="LONG",
                   author_id="alice", channel="gov_insider",
                   extracted_at=extracted, document_id="d-1")
    _insert_signal(db, asset_ticker="MSFT", side="LONG",
                   author_id="alice", channel="gov_insider",
                   extracted_at=extracted, document_id="d-2")
    _insert_signal(db, asset_ticker="MSFT", side="LONG",
                   author_id="alice", channel="gov_insider",
                   extracted_at=extracted, document_id="d-3")
    _insert_trade(db, asset_id=asset_id, entry_date=entry, pnl_percent=4.0)

    recompute_trust_weights(db_path=db, min_signals_for_update=1)

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT scope_kind, scope_key, trust_weight_after FROM signal_calibration_history"
        ).fetchall()
    kinds = {r[0] for r in rows}
    assert "author" in kinds
    assert "channel" in kinds


def test_dry_run_does_not_persist(db):
    asset_id = _insert_asset(db, "TSLA")
    _insert_author(db, "drymouse", trust=1.0)
    entry = datetime(2026, 5, 20, tzinfo=UTC)
    extracted = entry - timedelta(days=1)
    for i in range(3):
        _insert_signal(db, asset_ticker="TSLA", side="LONG",
                       author_id="drymouse", channel="corp_insider",
                       extracted_at=extracted, document_id=f"dry-{i}")
    _insert_trade(db, asset_id=asset_id, entry_date=entry, pnl_percent=6.0)

    run = recompute_trust_weights(db_path=db, dry_run=True, min_signals_for_update=1)
    assert run.weight_updates_authors >= 1
    with sqlite3.connect(db) as conn:
        tw = conn.execute(
            "SELECT trust_weight FROM input_authors WHERE author_id='drymouse'"
        ).fetchone()[0]
        hist = conn.execute(
            "SELECT COUNT(*) FROM signal_calibration_history"
        ).fetchone()[0]
    assert tw == 1.0   # unchanged
    assert hist == 0


def test_load_channel_trust_weight(db):
    assert load_channel_trust_weight("gov_insider", db_path=db) is None
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO source_trust_weights
               (source_channel, trust_weight, last_updated_at, baseline_weight)
               VALUES ('gov_insider', 1.3, '2026-06-01', 1.0)"""
        )
        conn.commit()
    assert load_channel_trust_weight("gov_insider", db_path=db) == pytest.approx(1.3)
