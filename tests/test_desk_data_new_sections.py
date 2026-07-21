"""Dashboard surface tests — live_signals, data_health, and the
un-stubbed KPI block. All against an isolated tmp DB so they can
exercise both empty and populated states.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.dashboard.desk_data import (
    _build_active_trades_kpi,
    _build_cash_posture_kpi,
    _build_pnl_today_kpi,
    _build_spend_today_kpi,
    build_data_health_section,
    build_live_signals_section,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "desk.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///desk.db")
    return db_path


# ── KPI tile queries on empty + populated state ────────────────────────────


def test_active_trades_empty(db):
    out = _build_active_trades_kpi()
    assert out == {"count": 0, "exposureUsd": 0}


def test_active_trades_populated(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) "
            "VALUES ('a-aapl', 'AAPL', 'AAPL', 'equity')"
        )
        conn.execute(
            "INSERT INTO trades (trade_id, asset_id, entry_date, entry_price, "
            "position_size, stop_loss, status) "
            "VALUES ('t1', 'a-aapl', '2026-06-01', 100.0, 5.0, 95.0, 'open'), "
            "       ('t2', 'a-aapl', '2026-06-02', 200.0, 2.0, 195.0, 'open'), "
            "       ('t3', 'a-aapl', '2026-05-01', 90.0, 3.0, 85.0, 'closed')"
        )
        conn.commit()
    out = _build_active_trades_kpi()
    assert out["count"] == 2                              # only open
    assert out["exposureUsd"] == 100.0 * 5.0 + 200.0 * 2.0


def test_pnl_today_empty(db):
    out = _build_pnl_today_kpi()
    assert out == {"usd": 0.0, "pct": 0.0}


def test_pnl_today_realized_only(db):
    today = datetime.now(UTC).date().isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) "
            "VALUES ('a-spy', 'SPY', 'SPY', 'index')"
        )
        conn.execute(
            "INSERT INTO trades (trade_id, asset_id, entry_date, entry_price, "
            "position_size, stop_loss, status, exit_date, exit_price, pnl) "
            "VALUES ('t1', 'a-spy', '2026-05-15', 400.0, 10.0, 380.0, "
            "'closed', ?, 420.0, 200.0)",
            (today,),
        )
        conn.commit()
    out = _build_pnl_today_kpi()
    assert out["usd"] == 200.0
    assert out["pct"] > 0


def test_cash_posture_empty_defaults_to_neutral(db):
    out = _build_cash_posture_kpi()
    assert out["label"] == "Neutral"
    assert out["pct"] == 50


def test_cash_posture_aggressive(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO portfolio_exposure_snapshots "
            "(snapshot_id, taken_at, account_equity, concurrent_trades, "
            " pct_deployed, bucket_exposures_json) "
            "VALUES ('s1', ?, 100000, 5, 82.0, '{}')",
            (datetime.now(UTC).isoformat(),),
        )
        conn.commit()
    out = _build_cash_posture_kpi()
    assert out["label"] == "Aggressive"
    assert out["pct"] == 18.0     # 100 - 82


def test_spend_today_empty(db):
    out = _build_spend_today_kpi()
    assert out == {"usd": 0.0, "capUsd": 25.0}


def test_spend_today_aggregates(db):
    today_iso = datetime.now(UTC).isoformat()
    yesterday_iso = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO agent_call_log "
            "(call_id, agent_name, called_at, model_provider, model_name, "
            " prompt_version, input_payload_json, output_payload_json, "
            " success, estimated_cost_usd) "
            "VALUES ('c1', 'x', ?, 'gemini', 'g', 'v1', '{}', '{}', 1, 0.50), "
            "       ('c2', 'x', ?, 'gemini', 'g', 'v1', '{}', '{}', 1, 0.30), "
            "       ('c3', 'x', ?, 'gemini', 'g', 'v1', '{}', '{}', 1, 9.99)",
            (today_iso, today_iso, yesterday_iso),
        )
        conn.commit()
    out = _build_spend_today_kpi()
    assert out["usd"] == 0.80    # yesterday's row excluded


# ── live_signals ───────────────────────────────────────────────────────────


def _insert_doc(db_path: Path, doc_id: str = "doc-1") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (document_id, source_id, title, "
            "published_at, content_type, raw_text, cleaned_text, tags_json, "
            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (doc_id, "manual:t", "t", "2026-06-01", "manual_note",
             "raw", "clean", "{}", "2026-06-01"),
        )
        conn.commit()


def _insert_signal(
    db_path: Path, *, ticker: str, side: str, weighted: float,
    extracted_at: datetime, sid: str | None = None,
) -> None:
    _insert_doc(db_path, doc_id=f"d-{sid or ticker}")
    with sqlite3.connect(db_path) as conn:
        # author_id='self:me' is a stated author (seeded by
        # initialize_database); hero signals only surface allow-listed
        # authors — see authors.SEEDED_AUTHOR_WHERE.
        conn.execute(
            "INSERT INTO signals (signal_id, document_id, extracted_at, "
            "asset_ticker, side, conviction, source_slug, author_id, "
            "extractor_name, extractor_version, status, weighted_score) "
            "VALUES (?, ?, ?, ?, ?, ?, 'manual', 'self:me', 'llm_extractor', "
            "'v1', 'active', ?)",
            (sid or ticker, f"d-{sid or ticker}", extracted_at.isoformat(),
             ticker, side, 3.0, weighted),
        )
        conn.commit()


def test_live_signals_empty(db):
    assert build_live_signals_section() == []


def test_live_signals_ranked_by_weight(db):
    now = datetime.now(UTC)
    _insert_signal(db, ticker="AAPL", side="LONG", weighted=5.0,
                   extracted_at=now - timedelta(hours=1), sid="a1")
    _insert_signal(db, ticker="MSFT", side="LONG", weighted=2.0,
                   extracted_at=now - timedelta(hours=2), sid="m1")
    out = build_live_signals_section()
    assert len(out) == 2
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["weighted_score"] == 5.0


def test_live_signals_respects_72h_window(db):
    now = datetime.now(UTC)
    _insert_signal(db, ticker="FRESH", side="LONG", weighted=1.0,
                   extracted_at=now - timedelta(hours=2), sid="fresh")
    _insert_signal(db, ticker="STALE", side="LONG", weighted=1.0,
                   extracted_at=now - timedelta(hours=80), sid="stale")
    tickers = [s["ticker"] for s in build_live_signals_section()]
    assert "FRESH" in tickers
    assert "STALE" not in tickers


def test_live_signals_truncates_thesis_summary(db):
    long_thesis = "x" * 500
    _insert_doc(db, "d-long")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO signals (signal_id, document_id, extracted_at, "
            "asset_ticker, side, conviction, source_slug, author_id, "
            "extractor_name, extractor_version, status, weighted_score, "
            "thesis_summary) "
            "VALUES ('long1', 'd-long', ?, 'NVDA', 'LONG', 3.0, 'manual', "
            "'self:me', 'llm_extractor', 'v1', 'active', 3.0, ?)",
            (datetime.now(UTC).isoformat(), long_thesis),
        )
        conn.commit()
    out = build_live_signals_section()
    assert len(out[0]["thesis_summary"]) <= 160


# ── data_health ────────────────────────────────────────────────────────────


def test_data_health_empty_db_is_all_red(db):
    h = build_data_health_section()
    statuses = [s["status"] for s in h["sources"]]
    # Every source should be red because no rows anywhere
    assert all(s == "red" for s in statuses)


def test_data_health_fresh_signals_green(db):
    _insert_signal(db, ticker="QQQ", side="LONG", weighted=2.0,
                   extracted_at=datetime.now(UTC), sid="recent")
    h = build_data_health_section()
    sig = next(s for s in h["sources"] if s["key"] == "signals")
    assert sig["status"] == "green"
    assert sig["docs_today"] >= 1


def test_data_health_24h_old_is_yellow(db):
    _insert_signal(db, ticker="QQQ", side="LONG", weighted=2.0,
                   extracted_at=datetime.now(UTC) - timedelta(hours=12),
                   sid="halfday")
    h = build_data_health_section()
    sig = next(s for s in h["sources"] if s["key"] == "signals")
    assert sig["status"] == "yellow"


def test_data_health_matches_actual_source_prefixes(db):
    """Substack docs land with source_id='substack:{slug}' — make sure
    the data_health pattern matches that prefix, not 'substack' literal.
    """
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO documents (document_id, source_id, title, "
            "published_at, content_type, raw_text, cleaned_text, "
            "tags_json, ingested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("ss-1", "substack:doomberg", "post", "2026-06-04",
             "rss_item", "x", "x", "{}",
             datetime.now(UTC).isoformat()),
        )
        # Also a Google News doc (no colon in source_id — exact match needed)
        conn.execute(
            "INSERT INTO documents (document_id, source_id, title, "
            "published_at, content_type, raw_text, cleaned_text, "
            "tags_json, ingested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("gn-1", "google_news", "headline", "2026-06-04",
             "rss_item", "x", "x", "{}",
             datetime.now(UTC).isoformat()),
        )
        conn.commit()
    h = build_data_health_section()
    ss = next(s for s in h["sources"] if s["key"] == "substack")
    assert ss["status"] == "green"
    assert ss["docs_today"] == 1
    gn = next(s for s in h["sources"] if s["key"] == "news")
    assert gn["status"] == "green"
    assert gn["docs_today"] == 1
