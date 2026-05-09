# Deployment — macro-analyzer on Render

Decision: **Render**, not Vercel. (D-2026-05-08-003 + 2026-05-09 mobile-readiness check.)
Vercel would force SQLite→Postgres migration + serverless rewrite of the
score runner — ~1–2 weeks of work that buys nothing this stack uses.
Render runs the existing FastAPI + SQLite + cron with no rewrite.

## Pre-deploy checklist

- [ ] **Auth stub** — public URL means basic auth needed before going live.
      Add `MPA_AUTH_TOKEN` env var + a middleware that checks `Authorization:
      Bearer $token` on every `/api/*` route. SPA reads from a same-origin
      cookie set at `/login`. Bypass middleware in dev when env var unset.
- [ ] **Mobile-responsive SPA pass** — current Claude Design output is
      desktop-first. At minimum: single-column stack below 768px, larger
      tap targets, hidden side panels under a hamburger. Test on real phone.
- [ ] **Relative API URLs only** — `web/data.js` and any client fetches
      use `/api/...`, never `http://127.0.0.1:8000/...`. Audit before deploy.
- [ ] **Generate `requirements.txt`** — Render's Python runtime doesn't
      ship `uv`. Export with `uv export --no-hashes -o requirements.txt`
      whenever `pyproject.toml` changes. Or run via `uv pip install -r`
      after pip-installing uv first (slower build).
- [ ] **Smoke-test from a fresh checkout** that `pip install -e .` works
      without `uv` (no editable-install gotchas).

## First deploy

1. Push the desired branch to GitHub (Render watches `main` per `render.yaml`).
2. Connect repo in Render dashboard; it'll detect `render.yaml` automatically.
3. Set the secrets in the dashboard (marked `sync: false`):
   - `MPA_AUTH_TOKEN` — generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `MPA_GEMINI_API_KEY`
   - `MPA_ANTHROPIC_API_KEY` (optional)
   - `MPA_FRED_API_KEY`
   - `MPA_N8N_*_WEBHOOK_URL` (optional)
4. Trigger the first deploy. Build takes ~2min on starter plan.
5. Health check: `curl https://macro-analyzer.onrender.com/api/desk/data \
   -H "Authorization: Bearer $TOKEN"` → 200 + JSON snapshot.

## SQLite on persistent disk

The `disk:` block in `render.yaml` mounts a 1GB persistent volume at `/var/data`.
SQLite + uploaded chart images both live there:

- `MPA_DATABASE_URL=sqlite:////var/data/macro_positioning.db` (4 slashes = absolute path)
- `MPA_BASE_DIR=/var/data` (so relative paths in `data/...` resolve correctly)
- `vendor/uploads/` and the manual-input `uploads/` dir need to write to
  `/var/data/uploads/` — ensure manual-input code respects `MPA_BASE_DIR`.

WAL mode persists across deploys (it's a pragma stored in the file). Render
restarts won't reset journal mode.

## Cron jobs

Render Cron Jobs require the paid plan (~$7/mo each). The `render.yaml` has
two cron entries commented out:

- `macro-prices-fetch` — `21:30 UTC` weekdays, post-close
- `macro-score-run` — every 30min during US market hours

**Until paid plan flip:** use one of these alternatives:

1. **GitHub Actions schedule** (free, recommended). Workflow that does
   `curl -X POST https://macro-analyzer.onrender.com/api/cron/score
   -H "Authorization: Bearer $MPA_AUTH_TOKEN"`. Need to add the
   `/api/cron/{score,prices}` endpoints — wrap the CLI commands.
2. **APScheduler in-process** — runs inside the web service. Free tier
   sleeps after 15min idle so this only runs when traffic wakes the
   service; not a fit for daily price fetches.

## Cost estimate

- Web service starter: $7/mo
- 1GB persistent disk: $0.25/mo
- 2 cron jobs (when enabled): $14/mo
- **Total under cron-on:** ~$21/mo
- **Total cron-off (with GH Actions):** ~$7.25/mo

Free tier works for early POC but the service sleeps after 15min idle, so
the SPA takes ~30s to wake on first hit. Acceptable for testing, not for
mobile usage.

## Rollback

Render keeps the prior image on every deploy. Click "Rollback" in the
deploys list to revert. SQLite state on the persistent disk is NOT rolled
back — that requires a separate snapshot strategy (Render snapshots are
manual on starter; daily on standard).

## Mobile target

POC desktop-only by ~2026-05-23 (2 weeks). Mobile usable by ~2026-06-09
(1 month), targeting ~30% of interface time. Mobile readiness:
- Public HTTPS URL — comes free with Render
- Auth — see "Auth stub" above
- Responsive SPA — separate task, every new component ships with breakpoints
- Touch targets — minimum 44×44px, hover states have tap equivalents
- No layout reliance on desktop-only `<select multiple>` etc.
