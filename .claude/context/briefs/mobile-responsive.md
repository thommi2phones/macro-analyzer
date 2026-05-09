# Worker brief: Mobile-responsive SPA pass

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

## Why this exists

The Claude Design SPA was authored desktop-first. Mobile target is ~30% of interface time starting ~2026-06-09. Public Render URL means the SPA WILL be loaded on a phone — make sure it doesn't fall apart at 375px.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — current state
2. `.claude/context/DECISIONS.md` — locked decisions
3. `docs/deployment.md` — mobile-readiness section at the bottom
4. `web/index.html` + `web/styles.css` — current style baseline
5. Each route file (`web/{positioning,journal,dev,reasoning}.jsx`) — see what's on each page

## Scope

Make the SPA usable at 375px width without horizontal scroll. NOT pretty — usable. Touch targets ≥44×44px. Everything readable.

### Three priorities

1. **Hero/positioning page** (`web/positioning.jsx`) — the page someone opens on their phone first. Stack columns, hide the macro indicator strip behind a collapsible, ensure watchlist table either wraps or scrolls horizontally with sticky first column.
2. **Journal page** (`web/journal.jsx`) — closed trades + sourceLeaderboard. Card layout for closed trades on mobile (table → list). Source leaderboard table needs horizontal scroll or compress.
3. **Dev page** (`web/dev.jsx`) — D1 mgmt panel, D2 brain activity, D3 cost tracker, D4 source health, D5 score correlation. Less critical than positioning/journal but should not crash the layout.

### Out of scope for this round

- Hamburger nav (4 tabs fit fine in a bottom nav strip)
- Dark mode (already dark)
- PWA install / iOS standalone meta tags (add later)
- Touch-specific interactions (swipe-to-archive etc)

## File territory (yours to edit)

- `web/styles.css` — add `@media (max-width: 768px)` blocks; introduce CSS variables for breakpoints if missing
- `web/{positioning,journal,dev,reasoning}.jsx` — add mobile-specific class branches where structure must change (table→cards), NOT just CSS
- `web/components.jsx` — shared components if you find a reusable mobile pattern
- `web/index.html` — viewport meta tag, ensure `<meta name="viewport" content="width=device-width, initial-scale=1">` is present
- `tests/` — no test changes expected; SPA isn't tested at the rendering layer

## Off-limits (escalate to PM)

- `web/data.mock.js` and `src/macro_positioning/dashboard/desk_data.py` — SPA contract; do NOT change shape
- Any backend code
- `.claude/context/*`

## Done criteria

- iPhone 13 Pro (390×844) and iPhone SE (375×667) both render every page without horizontal scroll
- All clickable/tappable elements ≥44×44px
- Tables on mobile either: stack into cards, OR scroll horizontally with a sticky leading column
- Touch device test: open `http://<your-laptop-ip>:8000/web/index.html` from your phone (need to bind to 0.0.0.0 for that — note in your hand-back if you did this)
- Desktop view (≥1024px) is UNCHANGED — diff your screenshots before/after
- Run the existing pytest suite: `uv run pytest -q` should still be 364/364 (no backend changes)

## Hand-back format

```
SHIPPED: mobile-responsive SPA pass
Branch: claude/<slug>
Commits: <list>
Tests: 364/364 (no backend changes)
Routes pass-mobile: positioning [yes/no], journal [yes/no], dev [yes/no], reasoning [yes/no]
Screenshots: <attach 6 — desktop + mobile of each major route>
Open questions: <if you found UX patterns that need user judgment>
```

## Conventions

- `uv` for everything
- Keep desktop view byte-identical where possible — wrap mobile changes in `@media` queries, don't refactor the desktop layout
- Don't introduce a CSS framework (Tailwind etc) — match the existing hand-rolled CSS style
- Don't add JS for layout decisions — pure CSS where possible
- Test breakpoints: 375 (iPhone SE), 390 (iPhone 13/14 Pro), 768 (iPad portrait), 1024 (iPad landscape)
