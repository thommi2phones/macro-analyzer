#!/usr/bin/env python3
"""Backup macro_positioning.db to a location OUTSIDE the project tree.

Stdlib-only on purpose: this script must keep working even if the app's
dependencies or settings module break. Safe against concurrent writers via
the sqlite3 online-backup API.

Foolproofing (added after the 2026-08-04 incident, when the live DB was
deleted on disk and nearly lost):
  * backups live in ~/Backups/macro-analyzer/, outside the repo, immune to
    git clean / worktree consolidation accidents
  * every backup is integrity-checked before it is accepted
  * poison guard: if the source DB is drastically smaller than the best
    existing backup, we still snapshot it but REFUSE to prune anything and
    raise a macOS notification — an emptied DB can never rotate out the
    good copies
  * schema is dumped to schema.sql alongside the binary backups

Retention: 14 dailies, 8 weeklies (Sunday), 12 monthlies (1st of month).
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

DB_PATH = Path("/Users/thom/Documents/Personal/Code Projects/Macro Analyzer/data/macro_positioning.db")
BACKUP_DIR = Path.home() / "Backups" / "macro-analyzer"
LOG_PATH = Path.home() / "Library" / "Logs" / "macro-db-backup.log"

KEEP_DAILY = 14
KEEP_WEEKLY = 8    # Sunday backups
KEEP_MONTHLY = 12  # 1st-of-month backups

# If the new backup is smaller than this fraction of the largest existing
# backup, treat the source as suspect: keep the snapshot, skip all pruning.
POISON_RATIO = 0.7

STAMP_RE = re.compile(r"^macro_positioning_(\d{8})_\d{6}\.db$")


def log(msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def notify(title: str, text: str) -> None:
    """Best-effort macOS notification; never fatal."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{text}" with title "{title}"'],
            timeout=10, capture_output=True,
        )
    except Exception:
        pass


def make_backup(dest: Path) -> None:
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def verify(path: Path) -> bool:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        log(f"verify: integrity={row[0]} documents={docs}")
        return row[0] == "ok"
    except sqlite3.Error as e:
        log(f"verify FAILED: {e}")
        return False
    finally:
        conn.close()


def dump_schema() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name"
        ).fetchall()
        (BACKUP_DIR / "schema.sql").write_text(
            ";\n\n".join(r[0] for r in rows) + ";\n"
        )
    finally:
        conn.close()


def existing_backups() -> list[Path]:
    return sorted(p for p in BACKUP_DIR.glob("macro_positioning_*.db")
                  if STAMP_RE.match(p.name))


def prune(backups: list[Path]) -> None:
    keep: set[Path] = set()
    dailies, weeklies, monthlies = [], [], []
    for p in sorted(backups, reverse=True):  # newest first
        m = STAMP_RE.match(p.name)
        assert m
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if len(dailies) < KEEP_DAILY:
            dailies.append(p)
        if d.weekday() == 6 and len(weeklies) < KEEP_WEEKLY:
            weeklies.append(p)
        if d.day == 1 and len(monthlies) < KEEP_MONTHLY:
            monthlies.append(p)
    keep.update(dailies, weeklies, monthlies)
    for p in backups:
        if p not in keep:
            log(f"prune: {p.name}")
            p.unlink()


def main() -> int:
    if not DB_PATH.exists():
        log(f"ALERT: source DB missing at {DB_PATH} — nothing backed up")
        notify("Macro DB backup FAILED", "Source database is MISSING.")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    prior = existing_backups()
    prior_max = max((p.stat().st_size for p in prior), default=0)

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = BACKUP_DIR / f".inprogress_{stamp}.db"
    final = BACKUP_DIR / f"macro_positioning_{stamp}.db"

    try:
        make_backup(tmp)
    except sqlite3.Error as e:
        log(f"ALERT: backup failed: {e}")
        notify("Macro DB backup FAILED", str(e))
        tmp.unlink(missing_ok=True)
        return 1

    if not verify(tmp):
        log("ALERT: integrity check failed — backup discarded")
        notify("Macro DB backup FAILED", "Integrity check failed on snapshot.")
        tmp.unlink(missing_ok=True)
        return 1

    tmp.rename(final)
    # sqlite sidecars of the temp name (created during backup/verify)
    for suffix in ("-shm", "-wal"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)
    size = final.stat().st_size
    log(f"backup ok: {final.name} ({size / 1e6:.1f} MB)")

    try:
        dump_schema()
    except sqlite3.Error as e:
        log(f"schema dump failed (non-fatal): {e}")

    if prior_max and size < prior_max * POISON_RATIO:
        log(f"ALERT: new backup ({size}B) is <{POISON_RATIO:.0%} of largest "
            f"existing backup ({prior_max}B) — source DB may be damaged. "
            f"PRUNING SKIPPED; old backups preserved.")
        notify("Macro DB backup WARNING",
               "New backup is much smaller than previous — DB may be damaged. "
               "Old backups preserved.")
        return 0

    prune(existing_backups())
    return 0


if __name__ == "__main__":
    sys.exit(main())
