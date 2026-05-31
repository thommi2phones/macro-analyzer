"""Portfolio-level rule checks: concurrent trades, deployed %, correlated buckets.

Reads only — the gate is advisory in v1 and this module never mutates.
Bucket assignment is derived from ticker via config/correlation_buckets.json,
not stored on the trades row, so this works pre-schema-change (Piece A).

Once Piece A lands a `correlated_bucket` column on `trades`, switch
`current_exposure` to read that column directly instead of recomputing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from macro_positioning.rules import load_buckets, load_caps
from macro_positioning.rules.risk import Violation


UNCORRELATED = "uncorrelated"


@dataclass(frozen=True)
class ExposureSnapshot:
    concurrent_trades: int
    pct_deployed: float
    by_bucket: dict[str, "BucketExposure"] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "concurrent_trades": self.concurrent_trades,
            "pct_deployed": self.pct_deployed,
            "by_bucket": {k: v.as_dict() for k, v in self.by_bucket.items()},
        }


@dataclass(frozen=True)
class BucketExposure:
    bucket_id: str
    label: str
    trade_count: int
    pct_of_equity: float
    tickers: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "bucket_id": self.bucket_id,
            "label": self.label,
            "trade_count": self.trade_count,
            "pct_of_equity": self.pct_of_equity,
            "tickers": list(self.tickers),
        }


def bucket_for_ticker(ticker: str, *, buckets_path: str | None = None) -> str:
    """Resolve a ticker to its bucket_id. Case-insensitive exact match;
    first match wins (per the config's documented resolution rule).
    Unmatched tickers return the literal "uncorrelated"."""
    if not ticker:
        return UNCORRELATED
    cfg = load_buckets(buckets_path) if buckets_path else load_buckets()
    needle = ticker.upper()
    for b in cfg["buckets"]:
        for m in b["members"]:
            if m.upper() == needle:
                return b["bucket_id"]
    return UNCORRELATED


def bucket_label(bucket_id: str, *, buckets_path: str | None = None) -> str:
    if bucket_id == UNCORRELATED:
        return "Uncorrelated"
    cfg = load_buckets(buckets_path) if buckets_path else load_buckets()
    for b in cfg["buckets"]:
        if b["bucket_id"] == bucket_id:
            return b["label"]
    return bucket_id


def current_exposure(
    conn: sqlite3.Connection,
    account_equity: float,
    *,
    buckets_path: str | None = None,
) -> ExposureSnapshot:
    """Aggregate live exposure from `trades.status='open'`.

    `pct_of_equity` per bucket is sum(position_size × entry_price) over
    the open rows in that bucket, divided by `account_equity`. Tickers
    are deduplicated within each bucket — two open trades on BTC count
    as two trades but one ticker in the listing.
    """
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT a.ticker, t.entry_price, t.position_size
        FROM trades t
        LEFT JOIN assets a ON a.asset_id = t.asset_id
        WHERE t.status = 'open'
        """
    ).fetchall()

    concurrent = len(rows)
    deployed_notional = 0.0
    by_bucket: dict[str, dict] = {}

    for r in rows:
        ticker = r["ticker"] or ""
        notional = (r["entry_price"] or 0.0) * (r["position_size"] or 0.0)
        deployed_notional += notional
        bid = bucket_for_ticker(ticker, buckets_path=buckets_path)
        slot = by_bucket.setdefault(
            bid,
            {"count": 0, "notional": 0.0, "tickers": []},
        )
        slot["count"] += 1
        slot["notional"] += notional
        if ticker and ticker not in slot["tickers"]:
            slot["tickers"].append(ticker)

    pct_deployed = deployed_notional / account_equity

    bucket_exposures: dict[str, BucketExposure] = {}
    for bid, slot in by_bucket.items():
        bucket_exposures[bid] = BucketExposure(
            bucket_id=bid,
            label=bucket_label(bid, buckets_path=buckets_path),
            trade_count=slot["count"],
            pct_of_equity=slot["notional"] / account_equity,
            tickers=tuple(slot["tickers"]),
        )

    return ExposureSnapshot(
        concurrent_trades=concurrent,
        pct_deployed=pct_deployed,
        by_bucket=bucket_exposures,
    )


def check_portfolio_caps(
    exposure: ExposureSnapshot,
    proposed_ticker: str,
    proposed_notional: float,
    account_equity: float,
    *,
    caps_path: str | None = None,
    buckets_path: str | None = None,
) -> list[Violation]:
    """Evaluate whether adding the proposed trade would breach portfolio caps.

    The proposed trade is folded into the existing exposure to test
    "what would the book look like if this fills?" — that's the only
    relevant question at gate time.
    """
    caps = load_caps(caps_path) if caps_path else load_caps()
    p = caps["portfolio_level"]
    sevs = caps["severities"]
    out: list[Violation] = []

    proposed_pct = proposed_notional / account_equity if account_equity > 0 else 0.0

    if exposure.concurrent_trades + 1 > p["max_concurrent_trades"]:
        out.append(
            Violation(
                code="concurrent_trades_exceeded",
                severity=sevs["concurrent_trades_exceeded"],
                message=(
                    f"concurrent trades {exposure.concurrent_trades}+1 exceeds cap "
                    f"{p['max_concurrent_trades']}"
                ),
            )
        )

    new_deployed = exposure.pct_deployed + proposed_pct
    if new_deployed > p["max_pct_deployed"]:
        out.append(
            Violation(
                code="pct_deployed_exceeded",
                severity=sevs["pct_deployed_exceeded"],
                message=(
                    f"pct deployed would be {new_deployed:.4f}, exceeds cap "
                    f"{p['max_pct_deployed']:.4f}"
                ),
            )
        )

    proposed_bucket = bucket_for_ticker(proposed_ticker, buckets_path=buckets_path)
    existing = exposure.by_bucket.get(proposed_bucket)
    existing_count = existing.trade_count if existing else 0
    existing_pct = existing.pct_of_equity if existing else 0.0
    bucket_label_ = bucket_label(proposed_bucket, buckets_path=buckets_path)

    # Don't apply the count cap to "uncorrelated" — that's the catch-all
    # for things that genuinely shouldn't share a bucket cap.
    if proposed_bucket != UNCORRELATED:
        if existing_count + 1 > p["max_trades_per_bucket"]:
            out.append(
                Violation(
                    code="bucket_trade_count_exceeded",
                    severity=sevs["bucket_trade_count_exceeded"],
                    message=(
                        f"bucket {bucket_label_!r} would hold {existing_count + 1} "
                        f"trades, exceeds cap {p['max_trades_per_bucket']}"
                    ),
                )
            )
        new_bucket_pct = existing_pct + proposed_pct
        if new_bucket_pct > p["max_bucket_exposure_pct"]:
            out.append(
                Violation(
                    code="bucket_exposure_pct_exceeded",
                    severity=sevs["bucket_exposure_pct_exceeded"],
                    message=(
                        f"bucket {bucket_label_!r} exposure would be "
                        f"{new_bucket_pct:.4f}, exceeds cap "
                        f"{p['max_bucket_exposure_pct']:.4f}"
                    ),
                )
            )

    return out
