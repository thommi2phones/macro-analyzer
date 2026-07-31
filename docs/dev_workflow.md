# Dev workflow (read this before starting new work)

## Source of truth

- **`main` on GitHub is authoritative.** The primary checkout at
  `/Users/thom/Documents/Personal/Code Projects/Macro Analyzer` tracks
  `main`, and the uvicorn dev server on port 8002 runs from that checkout.
  Anything not on `main` isn't "prod".
- There is currently no remote deploy (Render/Vercel/etc.). `render.yaml`
  is a scaffold, not wired up. Local uvicorn is prod today; mobile access
  is aspirational and will change this.

## Starting new work

1. From the primary checkout, `git fetch && git checkout main && git pull`.
2. Create a fresh worktree branched from `main`:
   ```bash
   git worktree add .claude/worktrees/<short-name> -b <branch-name> main
   ```
3. Do the work in that worktree. Commit as you go.

## Landing work

1. Push the branch: `git push -u origin <branch-name>`.
2. Open a PR against `main`: `gh pr create --base main`.
3. Owner (Thom) reviews and clicks merge in GitHub. **Do not fast-forward
   push to `main`.** Every change lands via PR so history is legible.
4. After merge:
   - `git worktree remove .claude/worktrees/<short-name>`
   - `git branch -d <branch-name>` (local) — the remote branch auto-deletes
     if the PR was merged with the "delete branch" toggle
   - In the primary checkout: `git pull` — the server will pick up the new
     code on next uvicorn restart.

## Do NOT

- Commit directly to `main` in any worktree.
- Force-push `main`.
- Leave long-running `claude/*` worktrees hanging. If a worktree has been
  idle > 2 weeks, either PR it or archive-tag + delete it (see below).
- Commit `data/personal_gmail_token.json*` or any `data/*_token.json.dead-*`
  file. These are ignored by `.gitignore`; if you see one staged, unstage.

## Archiving abandoned branches

If a branch has commits you don't want to merge but might want to reference:

```bash
git tag archive/wip-<date>/<slug> <branch>
git branch -D <branch>
git push origin --delete <branch>   # if it was pushed
```

The commits stay addressable by tag. Reflog also retains them ~90 days.

## Session handoff (Claude sessions)

Per global `CLAUDE.md`: at end of a substantive session, run `/checkpoint`
to update `.claude/context/STATE.md` so the next session picks up in ~2K
tokens instead of replaying history.
