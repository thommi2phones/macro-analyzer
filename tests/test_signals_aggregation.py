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
    DEFAULT_BLEND_WEIGHTS,
    DEFAULT_WINDOWS,
    _HORIZON_MULT,
    _SCALE_DEFAULT,
    _SCALE_FLOOR,
    _alignment_score,
    _recency_weight,
    _timeframe_multiplier,
    aggregate_for_ticker,
    aggregate_for_tickers,
    directional_scale,
)
from macro_positioning.signals.base import Signal, SignalHorizon, SignalSide


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


# ── Timeframe multiplier ─────────────────────────────────────────────────────


def test_timeframe_multiplier_from_horizon_enum():
    """Every SignalHorizon maps to a known multiplier."""
    assert _timeframe_multiplier({"horizon": "intraday"}) == 0.3
    assert _timeframe_multiplier({"horizon": "swing"}) == 1.0
    assert _timeframe_multiplier({"horizon": "position"}) == 1.4
    assert _timeframe_multiplier({"horizon": "strategic"}) == 1.6
    # Case-insensitive tolerance (rows come from SQLite as-persisted).
    assert _timeframe_multiplier({"horizon": "SWING"}) == 1.0


def test_timeframe_multiplier_default_swing_when_unknown():
    """Missing horizon + missing chart_timeframe → default swing weight
    (1.0). We do NOT silently zero unclassifiable reads."""
    assert _timeframe_multiplier({}) == 1.0
    assert _timeframe_multiplier({"horizon": None}) == 1.0
    assert _timeframe_multiplier({"horizon": "unknown_bucket"}) == 1.0


def test_timeframe_multiplier_falls_back_to_chart_timeframe():
    """When horizon is null, parse instrument_detail_json.chart_timeframe."""
    def tf(chart_timeframe: str) -> float:
        return _timeframe_multiplier(
            {"instrument_detail_json": f'{{"chart_timeframe": "{chart_timeframe}"}}'}
        )

    # Explicit intraday numerics — always tactical.
    assert tf("2H") == 0.3
    assert tf("4-hour view") == 0.3
    assert tf("15m") == 0.3
    # Keyword ladder — daily is baseline, weekly = position, monthly = strategic.
    assert tf("daily") == 1.0
    assert tf("weekly chart") == 1.4
    assert tf("monthly view") == 1.6
    assert tf("intraday scalp") == 0.3


def test_timeframe_multiplier_handles_dict_instrument_detail():
    """instrument_detail can arrive as a dict (unpersisted signal path)."""
    assert _timeframe_multiplier(
        {"instrument_detail_json": {"chart_timeframe": "2H"}}
    ) == 0.3


def test_intraday_read_counts_less_than_swing_read(db):
    """Two identical-conviction rows, one intraday one swing → swing
    contributes more weight to net_bias. This is the whole point of
    timeframe-weighting."""
    _seed(db, side=SignalSide.LONG, conviction=3.0,
          horizon=SignalHorizon.INTRADAY, document_id="doc-intra")
    _seed(db, side=SignalSide.LONG, conviction=3.0,
          horizon=SignalHorizon.SWING, document_id="doc-swing")

    agg = aggregate_for_ticker("AAPL", db_path=db)
    # Intraday multiplier is 0.3, swing is 1.0 → net_bias = 3.0×0.3 + 3.0×1.0 = 3.9
    # (vs 6.0 if both had counted equally). Confirm the discount landed.
    assert agg["net_bias"] == pytest.approx(3.9, rel=0.05)


# ── Multi-window matrix ──────────────────────────────────────────────────────


def test_all_seven_windows_returned(db):
    """Every configured window shows up in `windows`, with the empty
    default aggregate shape when a window has no signals."""
    _seed(db, side=SignalSide.LONG)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    labels = {w[0] for w in DEFAULT_WINDOWS}
    assert set(agg["windows"].keys()) == labels
    # Fresh signal falls inside every window.
    for label in labels:
        assert agg["windows"][label]["n_signals"] == 1


def test_windows_filter_by_extracted_at(db):
    """A signal 10 days old must appear in the 14d+ windows but NOT the
    1d/3d/7d windows."""
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    _seed(db, side=SignalSide.LONG, extracted_at=old, document_id="doc-old")

    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["windows"]["1d"]["n_signals"] == 0
    assert agg["windows"]["3d"]["n_signals"] == 0
    assert agg["windows"]["7d"]["n_signals"] == 0
    assert agg["windows"]["14d"]["n_signals"] == 1
    assert agg["windows"]["28d"]["n_signals"] == 1
    assert agg["windows"]["90d"]["n_signals"] == 1
    assert agg["windows"]["180d"]["n_signals"] == 1


def test_default_blend_weights_sum_to_one():
    """A blend that doesn't sum to 1.0 silently over- or under-weights
    windows. Keep this as a live invariant on the baseline."""
    assert sum(DEFAULT_BLEND_WEIGHTS.values()) == pytest.approx(1.0, rel=1e-6)


def test_blend_returns_weights_and_coverage(db):
    """Blend dict carries `weights_applied` (normalized) and `coverage`
    (share of blend mass whose window saw at least one signal)."""
    _seed(db, side=SignalSide.LONG)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert set(agg["blend"]["weights_applied"].keys()) == set(DEFAULT_BLEND_WEIGHTS.keys())
    assert sum(agg["blend"]["weights_applied"].values()) == pytest.approx(1.0, rel=1e-6)
    # Fresh signal hits every window → full coverage.
    assert agg["blend"]["coverage"] == pytest.approx(1.0)


def test_blend_coverage_drops_with_stale_only_signals(db):
    """A signal 20 days old only lands in the 28d+ windows. Blend
    coverage = share of blend weight whose window saw signal =
    weights of 28d + 90d + 180d = 0.22 + 0.16 + 0.10 = 0.48."""
    old = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    _seed(db, side=SignalSide.LONG, extracted_at=old)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["blend"]["coverage"] == pytest.approx(
        DEFAULT_BLEND_WEIGHTS["28d"]
        + DEFAULT_BLEND_WEIGHTS["90d"]
        + DEFAULT_BLEND_WEIGHTS["180d"],
        rel=1e-3,
    )


def test_custom_windows_and_blend_weights(db):
    """Caller can override the window matrix — useful for callers with
    a narrower or wider view (e.g. a fast-only view)."""
    _seed(db, side=SignalSide.LONG)
    agg = aggregate_for_ticker(
        "AAPL",
        db_path=db,
        windows=[("2d", 2, 1.0), ("30d", 30, 15.0)],
        blend_weights={"2d": 0.7, "30d": 0.3},
    )
    assert set(agg["windows"].keys()) == {"2d", "30d"}
    assert set(agg["blend"]["weights_applied"].keys()) == {"2d", "30d"}
    assert agg["blend"]["weights_applied"]["2d"] == pytest.approx(0.7)


# ── Cross-window trend detection ────────────────────────────────────────────


def test_cross_window_stable_when_all_windows_agree(db):
    """3 fresh LONG signals → both blocs long → trend stable_long."""
    _seed(db, side=SignalSide.LONG, document_id="doc-a")
    _seed(db, side=SignalSide.LONG, document_id="doc-b")
    _seed(db, side=SignalSide.LONG, document_id="doc-c")
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["cross_window"]["trend"] == "stable_long"
    assert agg["cross_window"]["recent_flip"] is False
    assert not agg["cross_window"]["diverging_windows"]


def test_cross_window_flips_short_on_recent_bear_stack(db):
    """The ETH scenario: a deep old LONG stack (well outside the short
    bloc) + 3 fresh SHORT signals. Long bloc (28d/90d/180d) still reads
    LONG because the old stack's recency-weighted mass in 90d/180d
    dominates; short bloc (1d/3d/7d) only sees the fresh flip → trend =
    flipping_short.

    Numbers: 20 old LONGs at age 60 vs 3 fresh SHORTs. In 90d (half-life
    30d), old-long recency ≈ 0.25 → 20×3×0.25 = 15 long_w vs 9 short_w.
    In 180d (half-life 60d), 20×3×0.5 = 30 long_w vs 9 short_w.
    28d sees only fresh SHORTs (age-0). Bloc sum: long=45, short=27 →
    LONG bloc reads LONG."""
    old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    for i in range(20):
        _seed(db, side=SignalSide.LONG, conviction=3.0,
              extracted_at=old_ts, document_id=f"doc-old-long-{i}")
    for i in range(3):
        _seed(db, side=SignalSide.SHORT, conviction=3.0,
              document_id=f"doc-fresh-short-{i}")

    agg = aggregate_for_ticker("AAPL", db_path=db)
    cw = agg["cross_window"]
    assert cw["short_bloc"]["direction"] == "short"
    assert cw["long_bloc"]["direction"] == "long"
    assert cw["trend"] == "flipping_short"
    assert cw["recent_flip"] is True
    # 1d/3d/7d should all be in diverging_windows (opposite of the long
    # bloc's LONG anchor).
    for label in ("1d", "3d", "7d"):
        assert label in cw["diverging_windows"]


def test_cross_window_mixed_when_confidence_too_low(db):
    """A 55/45 split shouldn't trigger a flip badge — the confidence
    floor keeps noise from tripping divergence."""
    _seed(db, side=SignalSide.LONG, document_id="doc-l")
    _seed(db, side=SignalSide.SHORT, document_id="doc-s")
    agg = aggregate_for_ticker("AAPL", db_path=db)
    # Same direction across blocs (both long) OR mixed (50/50). Either
    # way, no recent_flip.
    assert agg["cross_window"]["recent_flip"] is False


# ── Blend math ──────────────────────────────────────────────────────────────


def test_blend_reweights_when_only_short_bloc_has_signal(db):
    """A single fresh LONG hits every window; the blend just equals the
    per-window value (all long_weights identical). Verify the blend
    long_weight == the raw signal weight (with weight * timeframe = 1)."""
    _seed(db, side=SignalSide.LONG, conviction=3.0,
          source_trust_weight=1.0, author_trust_weight=1.0)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    # All windows saw the same 3.0-weight signal — blend average = 3.0.
    assert agg["blend"]["long_weight"] == pytest.approx(3.0, rel=0.02)


def test_blend_pulls_toward_recent_when_windows_disagree(db):
    """Old LONG in long-bloc windows only; fresh SHORT in every window.
    The blend should end up net short OR strongly reduced, because the
    fresh SHORT hits every window (all weights) while the old LONG only
    contributes to 28d+ windows (0.22+0.16+0.10 = 0.48 of the mass)."""
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    _seed(db, side=SignalSide.LONG, conviction=3.0, extracted_at=old,
          document_id="doc-old-long")
    _seed(db, side=SignalSide.SHORT, conviction=3.0,
          document_id="doc-fresh-short")

    agg = aggregate_for_ticker("AAPL", db_path=db)
    # Fresh SHORT is present in all 7 windows; old LONG only in 3 windows
    # with recency decay. Blend net_bias should be materially below 0
    # (or at least not the strongly-long number the old aggregator produced).
    assert agg["blend"]["net_bias"] < 0.5
    # And the short bloc reads SHORT.
    assert agg["cross_window"]["short_bloc"]["direction"] == "short"


# ── Back-compat ─────────────────────────────────────────────────────────────


def test_topline_matches_blend_directional_fields(db):
    """Old callers reading `bias_direction`, `net_bias`, etc. at the top
    level see the blend's values — the composer keeps working unchanged."""
    _seed(db, side=SignalSide.LONG, conviction=4.0)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["bias_direction"] == agg["blend"]["bias_direction"]
    assert agg["net_bias"] == agg["blend"]["net_bias"]
    assert agg["bias_confidence"] == agg["blend"]["bias_confidence"]
    assert agg["alignment_score"] == agg["blend"]["alignment_score"]


def test_legacy_since_days_and_half_life_collapse_to_single_window(db):
    """Callers still on the pre-multi-window API (`since_days=`,
    `half_life_days=`) get a single 'legacy' window — no windows matrix
    behind their back."""
    _seed(db, side=SignalSide.LONG)
    agg = aggregate_for_ticker("AAPL", db_path=db, since_days=30, half_life_days=7.0)
    assert list(agg["windows"].keys()) == ["legacy"]
    assert list(agg["blend"]["weights_applied"].keys()) == ["legacy"]


def test_topline_counts_come_from_union_not_blend(db):
    """`n_signals`, `watch_count`, `avoid_count`, `dominant_horizon`,
    `dominant_catalyst` at top level should be raw counts over the widest
    window — not blended fractions."""
    _seed(db, side=SignalSide.WATCH, document_id="doc-w")
    _seed(db, side=SignalSide.AVOID, document_id="doc-a")
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["n_signals"] == 2
    assert agg["watch_count"] == 1
    assert agg["avoid_count"] == 1


def test_top_signals_includes_timeframe_multiplier(db):
    """Top signals report their applied timeframe multiplier so a UI or
    trail can show why a call was up- or down-weighted."""
    _seed(db, side=SignalSide.LONG, horizon=SignalHorizon.STRATEGIC)
    agg = aggregate_for_ticker("AAPL", db_path=db)
    assert agg["top_signals"][0]["timeframe_multiplier"] == pytest.approx(_HORIZON_MULT["strategic"])
