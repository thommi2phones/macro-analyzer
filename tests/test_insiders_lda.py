"""Tests for the LDA filing -> lobbying_edges fan-out."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.insiders.lda import _filing_to_edges, _write_edges


SAMPLE_FILING = {
    "filing_uuid": "f00",
    "filing_year": 2026,
    "filing_period": "first_quarter",
    "filing_type": "RR",
    "filing_type_display": "Registration",
    "income": "55000",
    "expenses": None,
    "registrant": {"name": "ACME Lobbying LLC"},
    "client": {"name": "MegaCorp Inc"},
    "lobbying_activities": [
        {
            "general_issue_code": "BUD",
            "general_issue_code_display": "Budget/Appropriations",
            "lobbyists": [
                {
                    "lobbyist": {"first_name": "Jane", "middle_name": None, "last_name": "Doe"},
                    "covered_position": "Chief of Staff, Senator X",
                },
            ],
            "government_entities": [{"name": "U.S. Senate"}],
        },
    ],
}


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "lda.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///lda.db")
    return db_path


def test_filing_to_edges_emits_expected_kinds():
    edges = _filing_to_edges(SAMPLE_FILING)
    kinds = {e[2] for e in edges}
    assert kinds == {
        "client_paid_registrant",
        "filing_covers_issue",
        "filing_targets_agency",
        "registrant_employs_lobbyist",
        "lobbyist_prev_gov_role",
    }
    # Money edge carries the amount and correct direction.
    paid = next(e for e in edges if e[2] == "client_paid_registrant")
    assert paid[0] == "client:MegaCorp Inc"
    assert paid[1] == "registrant:ACME Lobbying LLC"
    assert paid[3] == 55000.0


def test_write_edges_dedupes_on_rerun(db):
    edges = _filing_to_edges(SAMPLE_FILING)
    inserted_a = _write_edges("f00", "2026-Q1", edges)
    inserted_b = _write_edges("f00", "2026-Q1", edges)
    assert inserted_a > 0
    assert inserted_b == 0  # all silently deduped via the unique index

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT count(*) FROM lobbying_edges WHERE filing_id='f00'"
        ).fetchone()
        assert rows[0] == inserted_a
