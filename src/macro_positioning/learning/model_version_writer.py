"""Item 7 — model_version on every agent_call_log row.

Convention (locked in the brief): `model_version = f"{model_name}@{prompt_version}"`
e.g. `gemini-2.5-pro@regime_classifier@v1`. The format pins both the
model identity AND the prompt revision so any A/B between prompt
versions is queryable without re-parsing.

This module provides:
  - `compose_model_version(model_name, prompt_version)` — the canonical
    joiner used by logging_wrapper and by the LLM-agents chat.
  - `backfill_model_versions(conn)` — populates `model_version` on
    historical rows where it's NULL, using the already-stored
    `model_name` + `prompt_version`. Never overwrites a non-NULL value
    (so the LLM-agents chat's live writes are respected).
  - `version_stats(conn)` — counts per model_version with first/last
    seen timestamps, useful for the dashboard's deployment-history
    view and for items 4+5+6 to stratify by model_version.

Coordination
────────────
LLM-agents chat (pending merge) writes `model_version` at insert time.
Our backfill explicitly skips rows where it's already populated. The
helper `compose_model_version` is opt-in for them — they're free to
keep their existing string-build path so long as it matches the
convention.
"""

from __future__ import annotations

import logging
import sqlite3


log = logging.getLogger(__name__)


def compose_model_version(model_name: str, prompt_version: str) -> str:
    """Canonical `{model_name}@{prompt_version}` joiner.

    Tolerant of either piece being a falsy/empty string — falls back to
    whichever side has content so we never write a bare `@` separator.
    """
    m = (model_name or "").strip()
    p = (prompt_version or "").strip()
    if m and p:
        return f"{m}@{p}"
    return m or p or "unknown"


def backfill_model_versions(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    """Set `model_version` on every row where it's NULL.

    Uses the row's own `model_name` + `prompt_version` (both NOT NULL in
    schema). Never touches rows where model_version is already set —
    LLM-agents chat owns those writes and we defer.

    Returns a summary dict:
        {
          "total_rows": int,                      # rows in agent_call_log
          "already_versioned": int,               # had non-NULL already
          "backfilled": int,                      # newly populated (or
                                                   #  would-be on dry_run)
          "dry_run": bool,
          "examples": [{"call_id", "model_version"}, ...]  # first ≤5
        }
    """
    total = conn.execute("SELECT COUNT(*) FROM agent_call_log").fetchone()[0]
    already = conn.execute(
        "SELECT COUNT(*) FROM agent_call_log WHERE model_version IS NOT NULL AND model_version != ''"
    ).fetchone()[0]

    cur = conn.execute(
        """
        SELECT call_id, model_name, prompt_version
        FROM agent_call_log
        WHERE model_version IS NULL OR model_version = ''
        """
    )
    rows = cur.fetchall()
    examples: list[dict] = []
    backfilled = 0
    for call_id, model_name, prompt_version in rows:
        version = compose_model_version(model_name, prompt_version)
        if len(examples) < 5:
            examples.append({"call_id": call_id, "model_version": version})
        if not dry_run:
            conn.execute(
                "UPDATE agent_call_log SET model_version = ? WHERE call_id = ?",
                (version, call_id),
            )
        backfilled += 1
    if not dry_run and backfilled:
        conn.commit()

    log.info(
        "backfill_model_versions: total=%d already=%d backfilled=%d dry_run=%s",
        total, already, backfilled, dry_run,
    )
    return {
        "total_rows": int(total),
        "already_versioned": int(already),
        "backfilled": int(backfilled),
        "dry_run": dry_run,
        "examples": examples,
    }


def version_stats(conn: sqlite3.Connection) -> dict:
    """Per-model_version counts + first/last seen — feeds the dashboard
    deployment-history panel and stratifies item-4 quality summaries.
    """
    total = conn.execute("SELECT COUNT(*) FROM agent_call_log").fetchone()[0]
    if total == 0:
        return {
            "_meta": {
                "lens": "model_version_stats",
                "n_total": 0,
                "message": "no agent_call_log rows yet — no LLM calls have been logged",
            },
            "versions": [],
        }
    n_null = conn.execute(
        "SELECT COUNT(*) FROM agent_call_log WHERE model_version IS NULL OR model_version = ''"
    ).fetchone()[0]

    cur = conn.execute(
        """
        SELECT COALESCE(NULLIF(model_version, ''), '<unversioned>') AS mv,
               agent_name,
               COUNT(*) AS n,
               MIN(called_at) AS first_seen,
               MAX(called_at) AS last_seen,
               SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS n_success
        FROM agent_call_log
        GROUP BY mv, agent_name
        ORDER BY mv, agent_name
        """
    )
    rows: list[dict] = []
    for mv, agent_name, n, first_seen, last_seen, n_success in cur.fetchall():
        rows.append(
            {
                "model_version": mv,
                "agent_name": agent_name,
                "n_calls": int(n),
                "n_success": int(n_success or 0),
                "success_rate": round((n_success / n) if n else 0.0, 4),
                "first_seen": first_seen,
                "last_seen": last_seen,
            }
        )
    return {
        "_meta": {
            "lens": "model_version_stats",
            "n_total": int(total),
            "n_unversioned": int(n_null),
            "message": (
                f"{total} agent_call_log rows; {n_null} still missing model_version "
                "(run `learning version backfill`)" if n_null else
                f"{total} agent_call_log rows; all versioned"
            ),
        },
        "versions": rows,
    }
