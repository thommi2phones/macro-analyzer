"""Per-ticker signal aggregation tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.signals import repository
from macro_positioning.signals.aggregation import (
    _SCALE_DEFAULT,
    _SCALE_FLOOR,
    _alignment_score,
    _recency_weight,
    aggregate_for_ticker,
    aggregate_for_tickers,
    directional_scale,
)
from macro_positioning.signals.base import Signal, SignalSide


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agg.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///agg.db")
    return db_path


def _insert_doc(db_path: Path, doc_id: str = "doc-1") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO documents
               (document_id, source_id, title, published_at, content_type,
                raw_text, cleaned_text, tags_json, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (doc_id, "manual:x", "t", "2026-06-01", "manual_note",
             "raw", "clean", "{}", "2026-06-01"),
        )
        conn.commit()


def _seed(db_path: Path, **fields) -> str:
    """Persist a Signal with sensible defaults; returns signal_id."""
    _insert_doc(db_path, fields.get("document_id", "doc-1"))
    defaults = dict(
        document_id="doc-1",
        asset_ticker="AAPL",
        source_slug="manual",
        # A stated author (seeded by initialize_database). Aggregation only
        # counts authors on the allowlist — see authors.SEEDED_AUTHOR_WHERE.
        author_id="self:me",
        extractor_name="t",
        side=SignalSide.LONG,
        conviction=3.0,
        source_trust_weight=1.0,
        author_trust_weight=1.0,
    )
    defaults.update(fields)
    s = Signal(**defaults)
    return repository.insert_signal(s, db_path=db_path)


# ── Pure functions ──────────────────────────────────────────────────────────


def test_recency_weight_halves_at_half_life():
    assert _recency_weight(0, half_life_days=14) == pytest.approx(1.0)
    assert _recency_weight(14, half_life_days=14) == pytest.approx(0.5, rel=1e-3)
    assert _recency_weight(28, half_life_days=14) == pytest.approx(0.25, rel=1e-3)


def test_alignment_score_bands():
    assert _alignment_score(0.0) == 0
    assert _alignment_score(-5.0) == 0
    assert _alignment_score(12.0, scale=12.0) == 10
    assert _alignment_score(6.0, scale=12.0) == 5
    assert _alignment_score(100.0, scale=12.0) == 10  # clamp


# ── Empty / no-signals ──────────────────────────────────────────────────────


def test_no_signals(db):
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["n_signals"] == 0
    assert agg["bias_direction"] == "neutral"
    assert agg["alignment_score"] == 0


# ── Long-only ───────────────────────────────────────────────────────────────


def test_two_strong_longs_score_higher_than_one(db):
    _seed(db, side=SignalSide.LONG, conviction=3.0,
          source_trust_weight=1.2, author_trust_weight=1.2)
    agg1 = aggregate_for_ticker("AAPL", db_path=db)
    _seed(db, side=SignalSide.LONG, conviction=3.0,
          source_trust_weight=1.2, author_trust_weight=1.2,
          document_id="doc-2")
    agg2 = aggregate_for_ticker("AAPL", db_path=db)

    assert agg1["bias_direction"] == "long"
    assert agg1["bias_confidence"] == 1.0
    assert agg2["alignment_score"] > agg1["alignment_score"]
    assert agg2["n_signals"] == 2


def test_long_short_mix_picks_dominant(db):
    _seed(db, side=SignalSide.LONG, conviction=4.0,
          source_trust_weight=1.0, author_trust_weight=1.0)
    _seed(db, side=SignalSide.SHORT, conviction=2.0,
          source_trust_weight=1.0, author_trust_weight=1.0,
          document_id="doc-2")
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["bias_direction"] == "long"
    assert agg["long_weight"] > agg["short_weight"]
    assert 0.5 < agg["bias_confidence"] < 1.0
    assert agg["net_bias"] > 0


def test_short_dominant(db):
    _seed(db, side=SignalSide.SHORT, conviction=4.0)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["bias_direction"] == "short"
    assert agg["alignment_score"] == 0  # alignment is positive-only


def test_watch_only(db):
    _seed(db, side=SignalSide.WATCH, conviction=2.0)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["bias_direction"] == "watch_only"
    assert agg["watch_count"] == 1


def test_exit_bias(db):
    _seed(db, side=SignalSide.EXIT, conviction=3.0)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["bias_direction"] == "exit_bias"
    assert agg["exit_weight"] > 0


# ── Top-n + provenance ──────────────────────────────────────────────────────


def test_top_signals_ranked_by_weight(db):
    # high-weight signal
    _seed(db, side=SignalSide.LONG, conviction=4.0,
          source_trust_weight=1.5, author_trust_weight=1.5,
          thesis_summary="big bet", document_id="doc-big")
    # low-weight signal
    _seed(db, side=SignalSide.LONG, conviction=1.0,
          source_trust_weight=0.6, author_trust_weight=0.8,
          thesis_summary="cheap mention", document_id="doc-small")
    agg = aggregate_for_ticker("AAPL", db_path=db, top_n=2)
    top = agg["top_signals"]
    assert len(top) == 2
    assert top[0]["thesis_summary"] == "big bet"
    assert top[0]["weighted_effective"] > top[1]["weighted_effective"]


def test_dominant_catalyst_horizon(db):
    from macro_positioning.signals.base import SignalCatalystType, SignalHorizon
    _seed(db, catalyst_type=SignalCatalystType.EARNINGS,
          horizon=SignalHorizon.SWING, document_id="doc-a")
    _seed(db, catalyst_type=SignalCatalystType.EARNINGS,
          horizon=SignalHorizon.SWING, document_id="doc-b")
    _seed(db, catalyst_type=SignalCatalystType.MACRO_PRINT,
          horizon=SignalHorizon.POSITION, document_id="doc-c")
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["dominant_catalyst"] == "earnings"
    assert agg["dominant_horizon"] == "swing"


def test_batch_aggregate(db):
    _seed(db, asset_ticker="AAPL", side=SignalSide.LONG, document_id="doc-aapl")
    _seed(db, asset_ticker="MSFT", side=SignalSide.SHORT, document_id="doc-msft")
    out = aggregate_for_tickers(["AAPL", "MSFT", "NVDA"], db_path=db)
    assert out["AAPL"]["bias_direction"] == "long"
    assert out["MSFT"]["bias_direction"] == "short"
    assert out["NVDA"]["bias_direction"] == "neutral"


# --- directional_scale (per-pass dynamic conviction scale) -----------------

def test_directional_scale_no_signals_returns_default():
    aggs = {"AAA": {"n_signals": 0, "net_bias": 0.0}}
    assert directional_scale(aggs) == _SCALE_DEFAULT


def test_directional_scale_floors_quiet_pass():
    # All net_bias magnitudes tiny → floor prevents saturating on noise.
    aggs = {t: {"n_signals": 2, "net_bias": b} for t, b in
            {"A": 0.1, "B": -0.2, "C": 0.15}.items()}
    assert directional_scale(aggs) == _SCALE_FLOOR


def test_directional_scale_tracks_high_percentile_when_convicted():
    # A wide spread with strong outliers lifts the scale above the floor.
    aggs = {f"T{i}": {"n_signals": 3, "net_bias": float(v)}
            for i, v in enumerate([1, 2, 3, 4, 20])}
    scale = directional_scale(aggs)
    assert scale > _SCALE_FLOOR
    # 90th percentile of [1,2,3,4,20] → index round(0.9*4)=4 → 20
    assert scale == 20.0


def test_directional_scale_ignores_zero_and_signalless():
    aggs = {
        "A": {"n_signals": 0, "net_bias": 99.0},   # no signals → ignored
        "B": {"n_signals": 2, "net_bias": 0.0},     # zero bias → ignored
        "C": {"n_signals": 2, "net_bias": 5.0},
    }
    # only C counts → single value 5.0 (above floor)
    assert directional_scale(aggs) == 5.0
