"""Vision extractor tests — mocked brain.vision backend.

Covers:
  - Happy path: chart read → Signal with stop/target derived from
    support/resistance and user metadata supplying ticker/side.
  - Cache hit: re-running the same image bytes skips the backend call.
  - No-ticker fallback: when user metadata is empty, the chart's `asset`
    field is used.
  - Backend error returns status=error.
  - Router fan-out: chart docs route to [vision_extractor, llm_extractor].
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.signals.base import SignalSide
from macro_positioning.signals.router import choose_extractors
from macro_positioning.signals.vision_extractor import VisionExtractor


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "vis.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///vis.db")
    return db_path


def _write_image(tmp_path: Path, name: str, content: bytes = b"\x89PNG\r\n\x1a\n_test_") -> str:
    """Drop a fake PNG under uploads/ and return the relative path."""
    rel = f"uploads/charts/2026-05/{name}"
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    return rel


def _insert_chart_doc(db_path: Path, tmp_path: Path, *, ticker="BTC", side="LONG", paths=None) -> str:
    rel_paths = paths or [_write_image(tmp_path, "btc_1d.png", b"\x89PNG\r\nUSER_BTC")]
    doc_id = "doc-chart-1"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO documents (
                document_id, source_id, title, url, published_at, author,
                content_type, raw_text, cleaned_text, tags_json, ingested_at,
                author_id, user_metadata_json, attachment_path, attachment_paths_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                doc_id, "manual:big-nuts", f"{ticker} chart drop", None,
                "2026-05-01", "Big_Nuts", "manual_chart",
                f"${ticker} breakout retest", f"${ticker} breakout retest",
                json.dumps({"tickers": [ticker], "tags": ["manual", "chart"]}),
                "2026-05-01",
                "big-nuts",
                json.dumps({
                    "user": {"ticker": ticker, "side": side, "conviction": 3,
                             "timeframe": "1D"},
                    "resolved": {"ticker": ticker, "side": side, "conviction": 3,
                                 "timeframe": "1D"},
                    "channel": "manual",
                    "channel_type": "telegram",
                }),
                rel_paths[0],
                json.dumps(rel_paths),
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO input_authors
               (author_id, display_name, channel, trust_weight)
               VALUES (?, ?, ?, ?)""",
            ("big-nuts", "Big_Nuts", "Feather Hands", 1.5),
        )
        conn.commit()
    return doc_id


# ── Router ─────────────────────────────────────────────────────────────────


def test_router_chart_doc_fan_out():
    doc = {
        "source_id": "manual:big-nuts",
        "author_id": "big-nuts",
        "attachment_paths_json": json.dumps(["uploads/charts/x.png"]),
    }
    assert choose_extractors(doc) == ["vision_extractor", "llm_extractor"]


def test_router_no_attachment_llm_only():
    doc = {"source_id": "manual:big-nuts", "author_id": "big-nuts"}
    assert choose_extractors(doc) == ["llm_extractor"]


def test_router_insider_overrides_attachment():
    doc = {
        "source_id": "manual:gov-insider-pelosi",
        "author_id": "gov-insider-pelosi",
        "attachment_paths_json": json.dumps(["uploads/charts/x.png"]),
    }
    # Insider docs ignore the chart for routing — they go to insider_extractor only.
    assert choose_extractors(doc) == ["insider_extractor"]


# ── Vision extractor ───────────────────────────────────────────────────────


def _fake_chart_read(asset="BTC", trend="bullish", strength="strong"):
    return {
        "asset": asset,
        "timeframe": "1D",
        "trend_direction": trend,
        "trend_strength": strength,
        "key_levels": {
            "support": [60000, 58000],
            "resistance": [72000, 78000],
        },
        "patterns": ["flag", "breakout_retest"],
        "momentum": "RSI 58 rising",
        "volume_signal": "Above-avg on breakout",
        "positioning_implications": ["Add on retest of 60k"],
        "confidence": 0.78,
        "summary": "Continuation pattern; trail stop under prior swing.",
    }


def test_vision_extractor_happy_path(db, tmp_path, monkeypatch):
    _insert_chart_doc(db, tmp_path, ticker="BTC", side="LONG")

    def fake_analyze(file_path, asset_context="", additional_context="", backend="gemini"):
        return _fake_chart_read()

    monkeypatch.setattr(
        "macro_positioning.signals.vision_extractor.analyze_chart_file",
        fake_analyze,
    )
    monkeypatch.setattr(settings, "brain_vision_backend", "gemini", raising=False)

    extractor = VisionExtractor()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        doc = dict(conn.execute(
            "SELECT * FROM documents WHERE document_id='doc-chart-1'"
        ).fetchone())

    result = extractor.extract(doc, run_id="vis-run")
    assert result.status == "success"
    assert len(result.signals) == 1

    s = result.signals[0]
    assert s.asset_ticker == "BTC"
    assert s.side == SignalSide.LONG
    # LONG → stop = first support, target_1 = first resistance
    assert s.stop_loss == 58000.0          # nearest support below entry (sorted asc)
    assert s.target_1 == 72000.0           # nearest resistance above entry
    assert s.target_2 == 78000.0
    # Strong + bullish + LONG → conv boost from 3 → 3.5
    assert s.conviction == pytest.approx(3.5)
    assert s.extractor_name == "vision_extractor"
    assert s.model_provider == "gemini"
    assert "flag" in s.thesis_tags
    assert s.instrument_detail["chart_timeframe"] == "1D"
    assert s.instrument_detail["chart_patterns"] == ["flag", "breakout_retest"]
    assert s.instrument_detail["vision_cached"] is False


def test_vision_extractor_short_inverts_levels(db, tmp_path, monkeypatch):
    _insert_chart_doc(db, tmp_path, ticker="QQQ", side="SHORT",
                      paths=[_write_image(tmp_path, "qqq.png", b"PNG_QQQ_SHORT")])
    # Patch doc_id to differ
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE documents SET document_id='doc-qqq-short'")
        conn.commit()

    monkeypatch.setattr(
        "macro_positioning.signals.vision_extractor.analyze_chart_file",
        lambda *a, **k: _fake_chart_read(asset="QQQ", trend="bearish"),
    )
    extractor = VisionExtractor()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        doc = dict(conn.execute("SELECT * FROM documents").fetchone())

    result = extractor.extract(doc)
    s = result.signals[0]
    # SHORT → stop = highest resistance, target_1 = highest support
    assert s.stop_loss == 78000.0
    assert s.target_1 == 60000.0
    # Strong + bearish + SHORT → conv boost
    assert s.conviction == pytest.approx(3.5)


def test_vision_cache_hit_skips_backend(db, tmp_path, monkeypatch):
    _insert_chart_doc(db, tmp_path, ticker="BTC", side="LONG")

    call_count = {"n": 0}

    def fake_analyze(file_path, asset_context="", additional_context="", backend="gemini"):
        call_count["n"] += 1
        return _fake_chart_read()

    monkeypatch.setattr(
        "macro_positioning.signals.vision_extractor.analyze_chart_file",
        fake_analyze,
    )

    extractor = VisionExtractor()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        doc = dict(conn.execute("SELECT * FROM documents").fetchone())

    r1 = extractor.extract(doc)
    r2 = extractor.extract(doc)
    assert r1.status == "success" and r2.status == "success"
    assert call_count["n"] == 1, "second run should use vision_cache"
    assert r2.signals[0].instrument_detail["vision_cached"] is True


def test_vision_falls_back_to_chart_asset(db, tmp_path, monkeypatch):
    rel = _write_image(tmp_path, "mystery.png", b"PNG_MYSTERY")
    doc_id = "doc-no-ticker"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO documents (document_id, source_id, title, published_at,
                content_type, raw_text, cleaned_text, tags_json, ingested_at,
                user_metadata_json, attachment_path, attachment_paths_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, "manual:anon", "drop", "2026-05-01", "manual_chart",
             "", "", "{}", "2026-05-01",
             json.dumps({"user": {}, "resolved": {}, "channel": "manual"}),
             rel, json.dumps([rel])),
        )
        conn.commit()

    monkeypatch.setattr(
        "macro_positioning.signals.vision_extractor.analyze_chart_file",
        lambda *a, **k: _fake_chart_read(asset="$AAPL"),
    )

    extractor = VisionExtractor()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        doc = dict(conn.execute(
            "SELECT * FROM documents WHERE document_id='doc-no-ticker'"
        ).fetchone())
    result = extractor.extract(doc)
    assert result.status == "success"
    assert result.signals[0].asset_ticker == "AAPL"   # stripped from $AAPL


def test_vision_backend_error(db, tmp_path, monkeypatch):
    _insert_chart_doc(db, tmp_path)
    monkeypatch.setattr(
        "macro_positioning.signals.vision_extractor.analyze_chart_file",
        lambda *a, **k: {"error": "Gemini quota exhausted"},
    )

    extractor = VisionExtractor()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        doc = dict(conn.execute("SELECT * FROM documents").fetchone())
    result = extractor.extract(doc)
    assert result.status == "error"
    assert "Gemini quota exhausted" in (result.error_message or "")


def test_vision_missing_file(db, tmp_path, monkeypatch):
    # Insert doc that points at a path that doesn't exist
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO documents (document_id, source_id, title, published_at,
                content_type, raw_text, cleaned_text, tags_json, ingested_at,
                user_metadata_json, attachment_path, attachment_paths_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("doc-missing", "manual:big-nuts", "drop", "2026-05-01",
             "manual_chart", "", "", "{}", "2026-05-01",
             json.dumps({"user": {"ticker": "AAPL", "side": "LONG"},
                         "resolved": {}, "channel": "manual"}),
             "uploads/charts/does_not_exist.png",
             json.dumps(["uploads/charts/does_not_exist.png"])),
        )
        conn.commit()

    extractor = VisionExtractor()
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        doc = dict(conn.execute(
            "SELECT * FROM documents WHERE document_id='doc-missing'"
        ).fetchone())
    result = extractor.extract(doc)
    assert result.status == "error"
    assert "image not found" in (result.error_message or "")
