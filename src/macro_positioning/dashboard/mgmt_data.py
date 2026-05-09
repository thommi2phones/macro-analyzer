"""Management snapshot for the /dev mgmt panel.

Surfaces three streams the operator wants visible while working on the project:

1. **Checklist summary** — quick counts (todo/in_progress/done) with the
   in-progress titles surfaced. Full checklist already lives in its own
   panel; this is the "at a glance" cut.
2. **Recent decisions** — sourced from `data/decisions.json`. These are
   architectural/scope decisions made in chat threads. Surfacing them
   here makes the chat thread's value persist outside the chat.
3. **Recent commits** — `git log --oneline -N` so the operator sees the
   project's recent activity without leaving the dashboard.

The endpoint is `/api/dashboard/mgmt` (see `dashboard/router.py`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings
from macro_positioning.dashboard.checklist import load_checklist


DECISIONS_PATH = settings.base_dir / "data" / "decisions.json"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Decision(BaseModel):
    decision_id: str
    decided_at: str
    topic: str
    decision: str
    rationale: str = ""
    alternatives_considered: str = ""
    chat_session_ref: str = ""
    affects_files: str = ""


class CommitEntry(BaseModel):
    sha: str
    short_sha: str
    author: str
    relative_date: str
    subject: str


class ChecklistSummary(BaseModel):
    total: int
    done: int
    in_progress: int
    todo: int
    pct_complete: int
    in_progress_titles: list[str] = Field(default_factory=list)


class MgmtSnapshot(BaseModel):
    checklist_summary: ChecklistSummary
    recent_decisions: list[Decision] = Field(default_factory=list)
    recent_commits: list[CommitEntry] = Field(default_factory=list)
    decisions_total: int = 0


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _load_decisions() -> list[Decision]:
    """Load decisions from data/decisions.json. Returns empty list on any error."""
    if not DECISIONS_PATH.exists():
        return []
    try:
        data = json.loads(DECISIONS_PATH.read_text())
        raw = data.get("decisions", [])
        return [Decision.model_validate(d) for d in raw]
    except Exception:
        return []


def _git_recent_commits(limit: int = 10) -> list[CommitEntry]:
    """Read the last N commits from git. Returns empty list on any failure
    (e.g., git not installed, not a repo, detached HEAD, etc.).

    Format: sha | short_sha | author | relative_date | subject
    """
    fmt = "%H%x1f%h%x1f%an%x1f%ar%x1f%s"
    try:
        result = subprocess.run(
            ["git", "log", f"-n{limit}", f"--pretty=format:{fmt}"],
            cwd=settings.base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    out = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        sha, short, author, when, subject = parts
        out.append(
            CommitEntry(
                sha=sha,
                short_sha=short,
                author=author,
                relative_date=when,
                subject=subject,
            )
        )
    return out


def _summarize_checklist() -> ChecklistSummary:
    """Compact checklist view: counts + in-progress titles only."""
    cl = load_checklist()
    items = cl.items
    total = len(items)
    done = sum(1 for i in items if i.status == "done")
    in_progress = sum(1 for i in items if i.status == "in_progress")
    todo = sum(1 for i in items if i.status == "todo")
    pct = round(done / total * 100) if total else 0
    in_progress_titles = [i.title for i in items if i.status == "in_progress"]
    return ChecklistSummary(
        total=total,
        done=done,
        in_progress=in_progress,
        todo=todo,
        pct_complete=pct,
        in_progress_titles=in_progress_titles,
    )


def build_mgmt_snapshot(
    decisions_limit: int = 8,
    commits_limit: int = 10,
) -> MgmtSnapshot:
    """Assemble the mgmt panel snapshot.

    `decisions_limit` and `commits_limit` cap what the API returns so the
    dashboard stays scannable. Most-recent-first ordering for both.
    """
    all_decisions = _load_decisions()
    # Most recent first by decided_at (lexicographic on ISO 8601 works).
    sorted_decisions = sorted(all_decisions, key=lambda d: d.decided_at, reverse=True)
    return MgmtSnapshot(
        checklist_summary=_summarize_checklist(),
        recent_decisions=sorted_decisions[:decisions_limit],
        recent_commits=_git_recent_commits(commits_limit),
        decisions_total=len(all_decisions),
    )
