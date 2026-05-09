"""Tests for ingestion/freshness.py — pure functions, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from macro_positioning.ingestion.freshness import (
    average_freshness,
    freshness_label,
    freshness_score,
    is_stale,
    parse_iso8601,
)


NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


def test_score_at_publish_time_is_one():
    assert freshness_score(NOW, sla_hours=24, now=NOW) == 1.0


def test_score_at_sla_is_half():
    pub = NOW - timedelta(hours=24)
    assert freshness_score(pub, sla_hours=24, now=NOW) == pytest.approx(0.5)


def test_score_at_double_sla_is_zero():
    pub = NOW - timedelta(hours=48)
    assert freshness_score(pub, sla_hours=24, now=NOW) == 0.0


def test_score_beyond_double_sla_clamps_zero():
    pub = NOW - timedelta(hours=200)
    assert freshness_score(pub, sla_hours=24, now=NOW) == 0.0


def test_score_future_published_clamps_one():
    pub = NOW + timedelta(hours=5)
    assert freshness_score(pub, sla_hours=24, now=NOW) == 1.0


def test_no_sla_means_always_fresh():
    pub = NOW - timedelta(days=365)
    assert freshness_score(pub, sla_hours=None, now=NOW) == 1.0
    assert freshness_score(pub, sla_hours=0, now=NOW) == 1.0


def test_iso_string_input_accepted():
    pub_str = (NOW - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    score = freshness_score(pub_str, sla_hours=24, now=NOW)
    assert score == pytest.approx(0.75)


def test_naive_iso_assumed_utc():
    pub_str = "2026-05-07T12:00:00"  # naive
    # That's 24h before NOW → score 0.5
    assert freshness_score(pub_str, sla_hours=24, now=NOW) == pytest.approx(0.5)


def test_freshness_label_buckets():
    assert freshness_label(1.0) == "fresh"
    assert freshness_label(0.8) == "fresh"
    assert freshness_label(0.6) == "recent"
    assert freshness_label(0.3) == "stale"
    assert freshness_label(0.1) == "expiring"
    assert freshness_label(0.0) == "expired"


def test_is_stale_default_threshold():
    pub = NOW - timedelta(hours=40)  # past 75% decay → score 0.166
    assert is_stale(pub, sla_hours=24, now=NOW)
    fresh_pub = NOW - timedelta(hours=6)  # score 0.875
    assert not is_stale(fresh_pub, sla_hours=24, now=NOW)


def test_average_freshness_empty():
    assert average_freshness([], sla_hours=24, now=NOW) == 0.0


def test_average_freshness_mixed():
    pubs = [
        NOW,                              # 1.0
        NOW - timedelta(hours=24),        # 0.5
        NOW - timedelta(hours=48),        # 0.0
    ]
    assert average_freshness(pubs, sla_hours=24, now=NOW) == pytest.approx(0.5)


def test_parse_iso8601_handles_z_suffix():
    dt = parse_iso8601("2026-05-08T12:00:00Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_parse_iso8601_handles_offset():
    dt = parse_iso8601("2026-05-08T12:00:00+00:00")
    assert dt.tzinfo is not None


def test_parse_iso8601_empty_raises():
    with pytest.raises(ValueError):
        parse_iso8601("")
