"""Test isolation — no test may touch the production database.

`data/macro_positioning.db` is live, shared with launchd-owned services,
and holds months of ingested documents that cannot be re-fetched
(CLAUDE.md). On 2026-08-24 a full `pytest tests/` run was found holding
that file open with ten read-write descriptors and a 38MB WAL, because
nothing stopped a test from resolving `settings.sqlite_path` to the real
path. `tests/test_pipeline.py::test_pipeline_generates_memo` is the
clearest case: it calls `build_pipeline()`, which does
`initialize_database(settings.sqlite_path)` against production and wires
a *real* LLM backend, then runs the pipeline for real.

Two autouse fixtures close that off:

`isolate_database` redirects `settings.database_url` at an absolute path
under the test's own tmp_path. It deliberately leaves `settings.base_dir`
alone — base_dir is also how `config/*.json` is located, and several
modules capture those paths at import time, so redirecting it would break
legitimate config reads without helping.

`forbid_production_database` is the backstop: it wraps `sqlite3.connect`
and raises on any attempt to open the real file, whatever route got
there. A test that trips it fails loudly instead of silently writing to
live data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROD_DB = (_REPO_ROOT / "data" / "macro_positioning.db").resolve()


def _target_path(database) -> Path | None:
    """Resolve whatever was handed to sqlite3.connect into a real path.

    Handles the URI form (`file:/path/to.db?mode=ro`) that read-only
    callers use, and returns None for `:memory:` and anything unparseable
    — those can never be the production file.
    """
    raw = str(database)
    if raw == ":memory:" or not raw:
        return None
    if raw.startswith("file:"):
        raw = raw[len("file:"):].split("?", 1)[0]
    try:
        return Path(raw).resolve()
    except (OSError, ValueError, RuntimeError):
        return None


@pytest.fixture(autouse=True)
def isolate_database(tmp_path, monkeypatch):
    """Point settings at a throwaway DB for the duration of each test.

    An absolute path is used on purpose: `Settings.sqlite_path` computes
    `base_dir / database_url.removeprefix("sqlite:///")`, and joining an
    absolute path discards base_dir — so this holds regardless of what
    base_dir happens to be.

    The nested directory and unusual filename matter. Many tests build
    their own `tmp_path / "test.db"`; if this fixture claimed that same
    name, `settings.sqlite_path` would equal the test's own database and
    `initialize_database`'s "refusing to initialize the production DB"
    guard would fire on it — turning every such test into an error.
    """
    db_path = tmp_path / "_pytest_isolated" / "macro_test_scratch.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    return db_path


@pytest.fixture(autouse=True)
def forbid_production_database(monkeypatch):
    """Hard stop on opening the live database from a test."""
    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        if _target_path(database) == _PROD_DB:
            raise RuntimeError(
                f"Test tried to open the PRODUCTION database at {_PROD_DB}.\n"
                "This file is live, shared with the launchd services, and "
                "irreplaceable. Point the code under test at a tmp_path DB "
                "— see the `isolate_database` fixture — or pass an explicit "
                "db_path. Never widen this guard to let a test through."
            )
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
