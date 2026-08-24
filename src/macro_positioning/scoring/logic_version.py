"""Fingerprint of the code that decides a score.

A score only means something next to the score before it, and that
comparison is only valid if the same logic produced both. On 2026-08-24
the conviction clock changed at 18:36 and the hourly job re-scored at
18:38; FCX moved 74 -> 76 on nothing but the new measurement, and the
alert layer announced "FCX cleared 75" as though the market had moved.

Hashing the modules that can move a score gives every persisted row a
stamp, so a consumer can tell "this went up" from "we started measuring
differently". The alert evaluator compares rows only within a version.

Deliberately a content hash rather than a hand-bumped constant: the
failure mode of a manual version is forgetting to bump it, and that
failure is silent and produces exactly the false alert this prevents. A
cosmetic edit costs one suppressed alert round, which is the safe
direction to be wrong in.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

# Modules whose contents can change a number in trade_scores. Ordered so
# the hash is stable across runs.
_SCORING_SOURCES = (
    "macro_positioning/signals/aggregation.py",
    "macro_positioning/scoring/runner.py",
    "macro_positioning/scoring/levels.py",
    "macro_positioning/scoring/level_crosscheck.py",
    "macro_positioning/scoring/setup_types.py",
    "macro_positioning/scoring/watchlist_resolver.py",
)
# The composer and its sub-scorers live under this tree; every .py in it
# is hashed so a new agent is covered without editing this list.
_SCORING_PACKAGES = ("macro_brain",)


def _src_root() -> Path:
    # …/src/macro_positioning/scoring/logic_version.py -> …/src
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def compute_logic_version() -> str:
    """Short stable hash of the scoring code. Memoized per process."""
    root = _src_root()
    digest = hashlib.sha256()

    paths: list[Path] = [root / rel for rel in _SCORING_SOURCES]
    for pkg in _SCORING_PACKAGES:
        pkg_dir = root / pkg
        if pkg_dir.is_dir():
            paths.extend(sorted(pkg_dir.rglob("*.py")))

    for path in paths:
        try:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
        except OSError:
            # A missing file is itself part of the fingerprint; never let
            # this raise into a scoring pass.
            digest.update(b"<unreadable>")
    return digest.hexdigest()[:12]
