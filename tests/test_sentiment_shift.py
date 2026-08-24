"""Sentiment shift across 1d / 3d / 7d / 14d.

Both tests below guard against the same failure in different disguises:
reporting something the data does not say. The first draft of this module
scored ETH "turning bullish" because it had gone silent, and COIN
"turning bearish" because a long thesis was fading.
"""
from __future__ import annotations

from macro_positioning.alerts import sentiment


def _w(n, direction, conf):
    return {"n_signals": n, "bias_direction": direction, "bias_confidence": conf}


def test_empty_window_is_silence_not_neutrality():
    """n_signals=0 must read as 'no data', never as a 0.00 sentiment."""
    assert sentiment._tilt(_w(0, "long", 1.0)) is None
    assert sentiment._tilt(None) is None
    assert sentiment._tilt(_w(3, "long", 0.8)) == 0.8
    assert sentiment._tilt(_w(3, "short", 0.8)) == -0.8
    assert sentiment._tilt(_w(3, "neutral", 0.0)) == 0.0


def test_going_quiet_is_not_reported_as_a_reversal():
    """ETH was bearish and then nobody spoke. Treating the empty recent
    windows as 0.00 made that read as a bullish turn."""
    data = {"scored": 1, "thin": 0, "quiet": [
        {"ticker": "ETH", "calls": 2, "base": -1.0,
         "tilts": {"1d": None, "3d": None, "7d": -1.0, "14d": -1.0}}],
        "moved": []}
    msg = sentiment.build_message(data)
    assert "WENT QUIET" in msg
    assert "not a reversal" in msg
    assert "BUILDING" not in msg and "FLIPPED" not in msg
    assert "—" in msg              # silence renders as a dash, not +0.00


def test_fading_conviction_is_not_called_a_reversal():
    """+1.00 -> +0.50 is a long thesis losing steam, not a short."""
    data = {"scored": 1, "thin": 0, "quiet": [], "moved": [
        {"ticker": "COIN", "calls": 4, "recent": 0.5, "base": 1.0,
         "shift": -0.5, "flipped": False,
         "tilts": {"1d": 0.0, "3d": 1.0, "7d": 1.0, "14d": 1.0}}]}
    msg = sentiment.build_message(data)
    assert "FADING" in msg
    assert "long" in msg           # names the side that is fading
    assert "BEARISH" not in msg.upper()


def test_a_genuine_flip_is_called_out():
    data = {"scored": 1, "thin": 0, "quiet": [], "moved": [
        {"ticker": "ETH", "calls": 9, "recent": -0.8, "base": 0.9,
         "shift": -1.7, "flipped": True,
         "tilts": {"1d": -0.8, "3d": -0.8, "7d": 0.9, "14d": 0.9}}]}
    assert "FLIPPED SIDE" in sentiment.build_message(data)


def test_thin_coverage_is_counted_not_hidden():
    data = {"scored": 79, "thin": 69, "quiet": [], "moved": [
        {"ticker": "SOL", "calls": 31, "recent": 1.0, "base": 0.76,
         "shift": 0.24, "flipped": False,
         "tilts": {"1d": 1.0, "3d": 1.0, "7d": 0.77, "14d": 0.76}}]}
    msg = sentiment.build_message(data)
    assert "69 skipped" in msg
    assert "79 scored" in msg


def test_quiet_board_sends_nothing():
    assert sentiment.build_message(
        {"scored": 79, "thin": 79, "moved": [], "quiet": []}) is None
