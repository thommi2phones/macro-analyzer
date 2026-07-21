"""LDA.gov lobbying-disclosure scraper.

Public API, no key required (well-known endpoint at lda.senate.gov/api/v1
through 2026-06-30 cutoff; lda.gov/api/ takes over after that).

For each filing we do two things:
  1. Emit one ScrapedEvent attributed to the **registrant** (the lobbying
     firm) as actor/principal, with the client + issue + amount captured
     in the body text. This is the "filing went in" signal.
  2. Write typed edges into `lobbying_edges` so the /05 influence SPA tab
     can render the network without re-parsing filings each request.

Edges written per filing:
  - client_paid_registrant       (with amount_usd from income/expenses)
  - registrant_employs_lobbyist  (one per lobbyist)
  - filing_covers_issue          (one per general_issue_code)
  - filing_targets_agency        (one per government_entity)
  - lobbyist_prev_gov_role       (one per lobbyist with covered_position)

Idempotent: `lobbying_edges` has a unique index on
(filing_id, from_node, to_node, edge_kind) so re-running this scraper
silently dedupes via INSERT OR IGNORE.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Iterable, Optional

from macro_positioning.core.settings import settings
from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "lda"
CHANNEL = "lobbying"

_BASE = "https://lda.senate.gov/api/v1/filings/"
_UA = "macro-analyzer/0.1 (personal research)"


_PERIOD_MAP = {
    "first_quarter": "Q1",
    "second_quarter": "Q2",
    "third_quarter": "Q3",
    "fourth_quarter": "Q4",
    "mid_year": "H1",
    "year_end": "H2",
}


def _period_str(year: int, filing_period: str) -> str:
    return f"{year}-{_PERIOD_MAP.get(filing_period, 'X')}"


def _fetch_page(year: int, page: int, page_size: int = 25) -> dict:
    import httpx  # type: ignore

    with httpx.Client(timeout=60.0, headers={"User-Agent": _UA}) as client:
        resp = client.get(_BASE, params={
            "filing_year": year,
            "page": page,
            "page_size": page_size,
        })
        resp.raise_for_status()
        return resp.json()


# ── Edge writing ────────────────────────────────────────────────────────────


def _node(kind: str, name: str) -> str:
    return f"{kind}:{(name or 'unknown').strip()}"


def _write_edges(filing_uuid: str, period: str, edges: list[tuple]) -> int:
    """edges: list of (from_node, to_node, edge_kind, amount_usd, raw_dict).
    Returns number actually inserted."""
    if not edges:
        return 0
    inserted = 0
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        for from_node, to_node, kind, amount, raw in edges:
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO lobbying_edges
                        (filing_id, period, from_node, to_node, edge_kind,
                         amount_usd, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        filing_uuid, period, from_node, to_node, kind,
                        amount, json.dumps(raw) if raw else None,
                    ),
                )
                inserted += cur.rowcount or 0
            except sqlite3.Error as exc:
                log.warning("lobbying_edges insert failed: %s", exc)
        conn.commit()
    return inserted


def _filing_to_edges(filing: dict) -> list[tuple]:
    """Compose the full set of edges for one filing record."""
    period = _period_str(filing["filing_year"], filing.get("filing_period", ""))
    registrant_name = (filing.get("registrant") or {}).get("name", "")
    client_name = (filing.get("client") or {}).get("name", "")

    income = filing.get("income")
    expenses = filing.get("expenses")
    try:
        amount = float(income) if income is not None else (
            float(expenses) if expenses is not None else None
        )
    except (TypeError, ValueError):
        amount = None

    reg_node = _node("registrant", registrant_name)
    client_node = _node("client", client_name)
    out: list[tuple] = []

    if client_name and registrant_name:
        out.append((
            client_node, reg_node, "client_paid_registrant",
            amount,
            {"period": period, "income": income, "expenses": expenses},
        ))

    for activity in filing.get("lobbying_activities") or []:
        issue_disp = activity.get("general_issue_code_display") or activity.get("general_issue_code")
        if issue_disp:
            out.append((
                client_node, _node("issue", issue_disp),
                "filing_covers_issue", None, {"period": period},
            ))
            out.append((
                reg_node, _node("issue", issue_disp),
                "filing_covers_issue", None, {"period": period},
            ))
        for gov_entity in activity.get("government_entities") or []:
            agency_name = gov_entity.get("name") if isinstance(gov_entity, dict) else str(gov_entity)
            if agency_name:
                out.append((
                    client_node, _node("agency", agency_name),
                    "filing_targets_agency", None, {"period": period},
                ))
        for lob_entry in activity.get("lobbyists") or []:
            lob = lob_entry.get("lobbyist") or {}
            full = " ".join(filter(None, [
                lob.get("first_name"), lob.get("middle_name"), lob.get("last_name"),
            ])).strip()
            if not full:
                continue
            lob_node = _node("lobbyist", full)
            out.append((
                reg_node, lob_node, "registrant_employs_lobbyist",
                None, {"period": period},
            ))
            covered = lob_entry.get("covered_position")
            if covered:
                out.append((
                    lob_node, _node("prev_role", covered),
                    "lobbyist_prev_gov_role", None,
                    {"period": period, "covered_position": covered},
                ))
    return out


# ── Public entry ────────────────────────────────────────────────────────────


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    year: Optional[int] = None,
    max_pages: int = 4,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    """Walk recent LDA filings for `year` and emit one event per filing.

    `max_pages * page_size` upper-bounds the per-run pull so morning_run
    doesn't drag on the full 28k+ Q1 dataset; subsequent runs continue
    from the cursor.
    """
    from datetime import UTC, datetime
    year = year or datetime.now(UTC).year
    cursor_id = cursor or ""

    for page in range(1, max_pages + 1):
        try:
            payload = _fetch_page(year, page)
        except Exception as exc:  # noqa: BLE001
            log.warning("LDA page %d fetch failed: %s", page, exc)
            break

        for filing in payload.get("results", []):
            uuid_ = filing.get("filing_uuid", "")
            if not uuid_:
                continue
            if uuid_ == cursor_id:
                return
            if since and (filing.get("dt_posted") or "")[:10] < since:
                continue

            period = _period_str(filing["filing_year"], filing.get("filing_period", ""))
            registrant_name = (filing.get("registrant") or {}).get("name", "Unknown registrant")
            client_name = (filing.get("client") or {}).get("name", "")

            edges = _filing_to_edges(filing)
            _write_edges(uuid_, period, edges)

            income = filing.get("income")
            expenses = filing.get("expenses")
            amt_label = None
            if income or expenses:
                amt_label = f"income=${income}" if income else f"expenses=${expenses}"

            issues = [
                a.get("general_issue_code_display") or a.get("general_issue_code")
                for a in (filing.get("lobbying_activities") or [])
                if a.get("general_issue_code_display") or a.get("general_issue_code")
            ]
            raw = (
                f"{registrant_name} filed {filing.get('filing_type_display', '')} "
                f"on behalf of {client_name} ({period})"
                + (f" — {amt_label}" if amt_label else "")
                + (f" — issues: {', '.join(issues[:5])}" if issues else "")
            )

            yield ScrapedEvent(
                source_slug=SOURCE_SLUG,
                channel=CHANNEL,
                external_id=uuid_,
                filed_at=(filing.get("dt_posted") or "")[:10],
                actor_name=registrant_name,
                principal_name=registrant_name,
                actor_relationship="registrant",
                tickers=[],
                amount_range=amt_label,
                transaction_type=filing.get("filing_type") or "filing",
                raw_text=raw,
                source_url=filing.get("filing_document_url") or filing.get("url"),
            )
