"""The twice-daily desk digest.

Sections are built independently and capped independently — the point
being that a long watchlist can never truncate the hero setups, and one
broken section cannot cost the other two.
"""
from __future__ import annotations

from macro_positioning.alerts import digest


def _wl(asset, score, cls="equity", side="LONG", d=0):
    return {"asset": asset, "score": score, "assetClass": cls,
            "side": side, "dScore": d, "id": asset}


def test_live_signals_render_author_and_age():
    msg = digest.build_live_signals_message([{
        "ticker": "ETH", "side": "LONG", "conviction": 4.5,
        "author_id": "feather-hands:big-nuts",
        "extracted_at": "2020-01-01T00:00:00+00:00",
    }])
    assert "ETH" in msg and "big-nuts" in msg
    assert "🟢" in msg           # LONG
    assert "d" in msg            # an age was rendered


def test_hero_marks_placeholder_rails():
    """A mechanical 2xATR guess must not read like a structural level."""
    rows = [{"asset": "ADM", "score": 82, "tier": 2, "side": "LONG",
             "hasLevels": True, "entry": 50.0, "stop": 47.0, "target": 59.0,
             "rr": 3.0, "setup": "mechanical rails", "levelStructural": False}]
    assert "placeholder rails" in digest.build_hero_signals_message(rows)


def test_watchlist_groups_and_ranks():
    msg = digest.build_watchlist_message([
        _wl("SOL", 87, "crypto"), _wl("MSFT", 75), _wl("GLD", 60, "commodity"),
    ])
    assert "CRYPTO" in msg and "STOCKS & ETFs" in msg and "MACRO" in msg
    assert msg.index("SOL") < msg.index("MSFT")      # ranked by score


def test_watchlist_never_silently_drops_an_unknown_class():
    """~11 raw asset_class values exist; a ticker outside the three
    buckets must still appear rather than vanish."""
    msg = digest.build_watchlist_message([_wl("WEIRD", 70, "no_such_class")])
    assert "WEIRD" in msg
    assert "OTHER" in msg


def test_sections_are_capped_independently():
    """A 500-name watchlist must not eat the hero message's budget."""
    msg = digest.build_watchlist_message(
        [_wl(f"T{i}", 90 - (i % 50)) for i in range(500)]
    )
    assert len(msg) <= digest._MAX
    assert "more" in msg          # says what it dropped


def test_empty_sections_are_skipped_not_sent():
    assert digest.build_live_signals_message([]) is None
    assert digest.build_hero_signals_message([]) is None
    assert digest.build_watchlist_message([]) is None


def test_one_broken_section_does_not_cost_the_others(monkeypatch):
    from macro_positioning.dashboard import desk_data

    def boom():
        raise RuntimeError("section exploded")

    monkeypatch.setattr(desk_data, "build_hero_signals_section", boom)
    monkeypatch.setattr(desk_data, "build_live_signals_section",
                        lambda: [{"ticker": "ETH", "side": "LONG",
                                  "author_id": "x:y", "conviction": 3}])
    monkeypatch.setattr(desk_data, "build_watchlist_section",
                        lambda: [_wl("SOL", 87, "crypto")])
    names = [n for n, _ in digest.build_digest()]
    assert names == ["live", "watchlist"]
