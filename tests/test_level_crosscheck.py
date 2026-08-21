"""Cross-check comparison math (scoring/level_crosscheck.py)."""

from macro_positioning.scoring.level_crosscheck import (
    compare_levels,
    is_scale_outlier,
    kol_entry_mid,
    pct_divergence,
    summarize,
)


def test_kol_entry_mid():
    assert kol_entry_mid(90.0, 110.0) == 100.0
    assert kol_entry_mid(90.0, None) == 90.0
    assert kol_entry_mid(None, 110.0) == 110.0
    assert kol_entry_mid(None, None) is None


def test_pct_divergence():
    assert pct_divergence(105.0, 100.0) == 0.05
    assert pct_divergence(95.0, 100.0) == 0.05
    assert pct_divergence(None, 100.0) is None
    assert pct_divergence(100.0, None) is None


def test_compare_levels_directional_agreement():
    agent = {"side": "LONG", "entry": 100.0, "stop": 95.0, "target": 115.0}
    kol = {"side": "LONG", "entry_zone_low": 98.0, "entry_zone_high": 102.0,
           "stop_loss": 94.0, "target_1": 110.0}
    c = compare_levels(agent, kol)
    assert c["entry_div"] == 0.0
    assert abs(c["stop_div"] - 1.0 / 94.0) < 1e-9
    assert abs(c["target_div"] - 5.0 / 110.0) < 1e-9
    assert c["side_comparable"] and c["side_agrees"]


def test_compare_levels_watch_side_not_comparable():
    agent = {"side": "LONG", "entry": 100.0, "stop": 95.0, "target": 115.0}
    kol = {"side": "WATCH", "entry_zone_low": 100.0, "entry_zone_high": None,
           "stop_loss": None, "target_1": None}
    c = compare_levels(agent, kol)
    assert not c["side_comparable"] and not c["side_agrees"]
    assert c["entry_div"] == 0.0
    assert c["stop_div"] is None and c["target_div"] is None


def test_summarize_medians_and_agreement():
    rows = [
        {"entry_div": 0.01, "stop_div": 0.02, "target_div": None,
         "side_comparable": True, "side_agrees": True},
        {"entry_div": 0.03, "stop_div": None, "target_div": 0.10,
         "side_comparable": True, "side_agrees": False},
        {"entry_div": None, "stop_div": 0.04, "target_div": 0.20,
         "side_comparable": False, "side_agrees": False},
    ]
    s = summarize(rows)
    assert s["n"] == 3
    assert s["median_entry_div"] == 0.02
    assert s["median_stop_div"] == 0.03
    assert s["median_target_div"] == 0.15
    assert s["n_directional"] == 2
    assert s["side_agreement"] == 0.5


def test_scale_outlier_detection():
    assert is_scale_outlier({"entry_div": 1022.0, "stop_div": None, "target_div": None})
    assert is_scale_outlier({"entry_div": None, "stop_div": 0.999, "target_div": None})
    assert not is_scale_outlier({"entry_div": 0.25, "stop_div": 0.7, "target_div": None})
    assert not is_scale_outlier({"entry_div": None, "stop_div": None, "target_div": None})


def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0 and s["median_entry_div"] is None
    assert s["side_agreement"] is None
