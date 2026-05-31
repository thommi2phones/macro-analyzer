"""Tests for rules/portfolio.py — bucket lookup + exposure + cap checks."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.rules import reset_caches
from macro_positioning.rules.portfolio import (
    UNCORRELATED,
    bucket_for_ticker,
    bucket_label,
    check_portfolio_caps,
    current_exposure,
)


@pytest.fixture(autouse=True)
def _clear_caps_cache():
    reset_caches()
    yield
    reset_caches()


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "portfolio.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _seed_open_trade(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    entry_price: float = 100.0,
    position_size: float = 1.0,
) -> None:
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    trade_id = f"trd-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, ticker, ticker, "equity"),
    )
    conn.execute(
        """INSERT INTO trades (
            trade_id, asset_id, entry_date, entry_price, position_size,
            stop_loss, status
        ) VALUES (?,?,?,?,?,?,?)""",
        (trade_id, asset_id, "2026-05-01T00:00:00Z", entry_price, position_size, entry_price * 0.95, "open"),
    )
    conn.commit()


def test_bucket_for_ticker_known_members():
    assert bucket_for_ticker("BTC") == "crypto_l1"
    assert bucket_for_ticker("eth") == "crypto_l1"  # case-insensitive
    assert bucket_for_ticker("GDX") == "precious_metals"
    assert bucket_for_ticker("XOP") == "energy_oil"
    assert bucket_for_ticker("NVDA") == "tech_megacap"


def test_bucket_for_ticker_unknown_is_uncorrelated():
    assert bucket_for_ticker("ZZZZ") == UNCORRELATED
    assert bucket_for_ticker("") == UNCORRELATED


def test_bucket_label_resolves():
    assert bucket_label("crypto_l1") == "Crypto L1"
    assert bucket_label(UNCORRELATED) == "Uncorrelated"


def test_current_exposure_empty_book(tmp_path: Path):
    conn = _conn(tmp_path)
    snap = current_exposure(conn, account_equity=100_000.0)
    assert snap.concurrent_trades == 0
    assert snap.pct_deployed == 0.0
    assert snap.by_bucket == {}


def test_current_exposure_aggregates_open_trades(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_open_trade(conn, ticker="BTC", entry_price=60_000.0, position_size=0.05)
    _seed_open_trade(conn, ticker="ETH", entry_price=3000.0, position_size=0.5)
    _seed_open_trade(conn, ticker="GDX", entry_price=40.0, position_size=20.0)

    snap = current_exposure(conn, account_equity=100_000.0)
    assert snap.concurrent_trades == 3

    # BTC + ETH share crypto_l1 bucket
    crypto = snap.by_bucket["crypto_l1"]
    assert crypto.trade_count == 2
    assert set(crypto.tickers) == {"BTC", "ETH"}
    # BTC notional = 3000, ETH notional = 1500; bucket pct = 4500/100000 = 0.045
    assert crypto.pct_of_equity == pytest.approx(0.045)

    # GDX alone in precious_metals
    pm = snap.by_bucket["precious_metals"]
    assert pm.trade_count == 1
    # notional 40*20 = 800, pct 0.008
    assert pm.pct_of_equity == pytest.approx(0.008)

    # total deployed = (3000+1500+800)/100000 = 0.053
    assert snap.pct_deployed == pytest.approx(0.053)


def test_check_portfolio_caps_concurrent_breach(tmp_path: Path):
    conn = _conn(tmp_path)
    # 5 trades already open → adding a 6th breaches max_concurrent_trades=5
    for i in range(5):
        _seed_open_trade(conn, ticker=f"TKR{i}", entry_price=100.0, position_size=1.0)
    snap = current_exposure(conn, account_equity=100_000.0)
    violations = check_portfolio_caps(
        snap,
        proposed_ticker="ZZZ",
        proposed_notional=100.0,
        account_equity=100_000.0,
    )
    codes = {v.code for v in violations}
    assert "concurrent_trades_exceeded" in codes


def test_check_portfolio_caps_bucket_count_breach(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_open_trade(conn, ticker="BTC", entry_price=60_000.0, position_size=0.01)
    snap = current_exposure(conn, account_equity=1_000_000.0)
    # Proposing ETH adds a second trade to crypto_l1 bucket (cap=1)
    violations = check_portfolio_caps(
        snap,
        proposed_ticker="ETH",
        proposed_notional=1500.0,
        account_equity=1_000_000.0,
    )
    codes = {v.code for v in violations}
    assert "bucket_trade_count_exceeded" in codes


def test_check_portfolio_caps_bucket_pct_breach(tmp_path: Path):
    conn = _conn(tmp_path)
    # Empty book; propose 11% notional in a single bucket → exceeds 10% cap
    snap = current_exposure(conn, account_equity=100_000.0)
    violations = check_portfolio_caps(
        snap,
        proposed_ticker="BTC",
        proposed_notional=11_000.0,
        account_equity=100_000.0,
    )
    codes = {v.code for v in violations}
    assert "bucket_exposure_pct_exceeded" in codes


def test_check_portfolio_caps_uncorrelated_skips_bucket_count(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_open_trade(conn, ticker="ZZZ", entry_price=10.0, position_size=10.0)
    snap = current_exposure(conn, account_equity=100_000.0)
    # Adding another uncorrelated should NOT trip the bucket count cap
    violations = check_portfolio_caps(
        snap,
        proposed_ticker="YYY",  # also unknown → uncorrelated
        proposed_notional=100.0,
        account_equity=100_000.0,
    )
    codes = {v.code for v in violations}
    assert "bucket_trade_count_exceeded" not in codes


def test_check_portfolio_caps_clean_proposal(tmp_path: Path):
    conn = _conn(tmp_path)
    snap = current_exposure(conn, account_equity=100_000.0)
    violations = check_portfolio_caps(
        snap,
        proposed_ticker="BTC",
        proposed_notional=3000.0,  # 3% — under all caps
        account_equity=100_000.0,
    )
    assert violations == []
