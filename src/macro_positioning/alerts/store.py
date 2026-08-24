"""Persistence for fired alerts.

The `alerts` row is the durable record and the dedupe key; delivery is a
best-effort layer stamped on top of it (`delivered_json`). That ordering
matters: an alert that was correctly derived but failed to send is still
a fact about the tracker's state, and the next cycle can retry it.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from macro_positioning.core.settings import settings


@dataclass
class Alert:
    """One fired alert, pre-persistence."""

    rule: str
    severity: str            # 'high' | 'medium'
    ticker: str
    title: str
    body: str
    score_before: int | None = None
    score_after: int | None = None
    grade_before: str | None = None
    grade_after: str | None = None
    tier_after: str | None = None
    side: str | None = None
    score_id: str | None = None
    payload: dict = field(default_factory=dict)
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    fired_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_row(self) -> dict:
        d = asdict(self)
        d["payload_json"] = json.dumps(d.pop("payload"), default=str)
        return d


def _loads(raw: str | None) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def _connect(conn: sqlite3.Connection | None = None) -> tuple[sqlite3.Connection, bool]:
    if conn is not None:
        return conn, False
    c = sqlite3.connect(settings.sqlite_path)
    c.execute("PRAGMA busy_timeout=5000")
    return c, True


def recent_fire_keys(
    *,
    hours: int,
    conn: sqlite3.Connection | None = None,
) -> set[tuple[str, str]]:
    """(ticker, rule) pairs that fired inside the cooldown window.

    Returned as a set so the evaluator can filter its candidates in one
    pass rather than querying per candidate.
    """
    c, own = _connect(conn)
    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        rows = c.execute(
            "SELECT ticker, rule FROM alerts WHERE fired_at >= ?", (cutoff,)
        ).fetchall()
        return {(str(r[0]).upper(), str(r[1])) for r in rows}
    finally:
        if own:
            c.close()


def record(alerts: list[Alert], *, conn: sqlite3.Connection | None = None) -> int:
    """Insert alerts. Returns the number written."""
    if not alerts:
        return 0
    c, own = _connect(conn)
    try:
        c.executemany(
            """
            INSERT OR IGNORE INTO alerts (
                alert_id, fired_at, rule, severity, ticker, title, body,
                score_before, score_after, grade_before, grade_after,
                tier_after, side, score_id, payload_json, delivered_json, acked_at
            ) VALUES (
                :alert_id, :fired_at, :rule, :severity, :ticker, :title, :body,
                :score_before, :score_after, :grade_before, :grade_after,
                :tier_after, :side, :score_id, :payload_json, NULL, NULL
            )
            """,
            [a.to_row() for a in alerts],
        )
        c.commit()
        return len(alerts)
    finally:
        if own:
            c.close()


def pending_delivery(
    *,
    window_hours: int,
    channel: str,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Alerts inside the window with no successful delivery on `channel`.

    Covers three cases with one query: never attempted, attempted and
    failed, and "fired before the channel was configured".
    """
    c, own = _connect(conn)
    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=window_hours)).isoformat()
        rows = c.execute(
            """
            SELECT alert_id, fired_at, rule, severity, ticker, title, body,
                   score_before, score_after, grade_before, grade_after,
                   tier_after, side, delivered_json, payload_json
            FROM alerts
            WHERE fired_at >= ?
            ORDER BY fired_at ASC
            """,
            (cutoff,),
        ).fetchall()
        out = []
        for r in rows:
            try:
                delivered = json.loads(r[13]) if r[13] else {}
            except Exception:  # noqa: BLE001
                delivered = {}
            if delivered.get(channel) == "ok":
                continue
            out.append({
                "alert_id": r[0], "fired_at": r[1], "rule": r[2],
                "severity": r[3], "ticker": r[4], "title": r[5], "body": r[6],
                "score_before": r[7], "score_after": r[8],
                "grade_before": r[9], "grade_after": r[10], "tier_after": r[11],
                "side": r[12], "delivered": delivered,
                # Carries prev_scored_at / scored_at so the message can
                # say how long the move took, not just that it happened.
                "payload": _loads(r[14]),
            })
        return out
    finally:
        if own:
            c.close()


def mark_delivered(
    alert_id: str,
    channel: str,
    status: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Stamp one channel's outcome onto an alert, preserving the others."""
    c, own = _connect(conn)
    try:
        row = c.execute(
            "SELECT delivered_json FROM alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if row is None:
            return
        try:
            delivered = json.loads(row[0]) if row[0] else {}
        except Exception:  # noqa: BLE001
            delivered = {}
        delivered[channel] = status
        c.execute(
            "UPDATE alerts SET delivered_json = ? WHERE alert_id = ?",
            (json.dumps(delivered), alert_id),
        )
        c.commit()
    finally:
        if own:
            c.close()


def recent(limit: int = 50, *, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Newest alerts first — feeds the API/SPA alert list."""
    c, own = _connect(conn)
    try:
        rows = c.execute(
            """
            SELECT alert_id, fired_at, rule, severity, ticker, title, body,
                   score_before, score_after, grade_before, grade_after,
                   tier_after, side, delivered_json, acked_at
            FROM alerts ORDER BY fired_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [{
            "id": r[0], "firedAt": r[1], "rule": r[2], "severity": r[3],
            "ticker": r[4], "title": r[5], "body": r[6],
            "scoreBefore": r[7], "scoreAfter": r[8],
            "gradeBefore": r[9], "gradeAfter": r[10], "tier": r[11],
            "side": r[12],
            "delivered": json.loads(r[13]) if r[13] else {},
            "ackedAt": r[14],
        } for r in rows]
    finally:
        if own:
            c.close()
