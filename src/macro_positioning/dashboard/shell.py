"""Shared dashboard shell — institutional-terminal aesthetic.

Every dashboard page wraps its body in `render_shell()` so they all get
the same top bar, nav, typography, and color palette.

Visual pattern inspired by institutional macro terminals:
- Deep navy background with elevated slate cards
- Gradient accent on panel top-borders
- Uppercase compact labels with proper typographic scale
- Status-indicator pills, category chips, stat boxes with big numbers
- Dense data tables with monospace number columns
"""

from __future__ import annotations


NAV_ITEMS = [
    ("terminal", "Terminal", "/terminal"),
    ("positioning", "Macro & Positioning", "/positioning"),
    ("tactical", "Tactical", "/tactical"),
    ("dev", "Dev", "/dev"),
    ("guide", "Guide", "/guide"),
]


# ---------------------------------------------------------------------------
# Shared CSS / SVG icon set / layout helpers
# ---------------------------------------------------------------------------

SHARED_CSS = r"""
:root {
  --bg-0: #070b14;
  --bg-1: #0b111c;
  --bg-2: #111827;
  --bg-3: #151c2e;
  --surface: #131a2a;
  --surface-hi: #1a2236;
  --border: #1e2942;
  --border-hi: #2a3758;
  --border-accent: #3b82f6;
  --text: #e5e7eb;
  --text-dim: #94a3b8;
  --text-muted: #64748b;
  --text-mute-2: #475569;
  --accent: #3b82f6;
  --accent-2: #60a5fa;
  --accent-3: #2563eb;
  --green: #10b981;
  --green-2: #34d399;
  --red: #ef4444;
  --red-2: #f87171;
  --yellow: #f59e0b;
  --yellow-2: #fbbf24;
  --purple: #8b5cf6;
  --purple-2: #a78bfa;
  --orange: #f97316;
  --teal: #14b8a6;
  --shadow-lg: 0 10px 40px -10px rgba(0, 0, 0, 0.6);
  --shadow-md: 0 4px 20px -4px rgba(0, 0, 0, 0.5);
  --glow-accent: 0 0 12px rgba(59, 130, 246, 0.35);
  --glow-green: 0 0 12px rgba(16, 185, 129, 0.35);
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Menlo', monospace;
  --font-ui: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  font-family: var(--font-ui);
  background: var(--bg-0);
  color: var(--text);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-feature-settings: 'ss01', 'cv02', 'cv11';
  background:
    radial-gradient(ellipse at top, rgba(59, 130, 246, 0.04), transparent 70%),
    radial-gradient(ellipse at bottom, rgba(16, 185, 129, 0.02), transparent 70%),
    var(--bg-0);
  min-height: 100vh;
}

/* ────────  TOP BAR  ──────── */
.app-bar {
  position: sticky; top: 0; z-index: 100;
  background: rgba(7, 11, 20, 0.88);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  border-bottom: 1px solid var(--border);
}
.app-bar-top {
  display: grid;
  grid-template-columns: auto auto 1fr auto auto;
  align-items: center;
  gap: 20px;
  padding: 12px 28px;
  border-bottom: 1px solid var(--border);
}
.brand {
  display: flex; align-items: center; gap: 12px;
}
.brand-mark {
  width: 36px; height: 36px; border-radius: 8px;
  background: radial-gradient(circle at 30% 30%, #60a5fa 0%, #1e40af 80%);
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: 14px; color: white; letter-spacing: -0.3px;
  box-shadow: var(--glow-accent);
}
.brand-text { line-height: 1.15; }
.brand-title { font-weight: 800; font-size: 15px; letter-spacing: -0.3px; }
.brand-sub {
  font-size: 10px; color: var(--text-mute-2); text-transform: uppercase;
  letter-spacing: 1.4px; font-weight: 500;
}
.status-pill {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 12px; border-radius: 6px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.28);
  color: var(--green-2);
  font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
  text-transform: uppercase;
}
.status-pill .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green); box-shadow: var(--glow-green);
  animation: pulse 2s infinite ease-in-out;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
.ticker {
  display: flex; align-items: center; gap: 14px;
  min-width: 0;
  overflow: hidden;
  padding: 0 4px;
}
.ticker-tag {
  font-size: 10px; font-weight: 800; letter-spacing: 1px;
  padding: 4px 9px; border-radius: 4px;
  text-transform: uppercase; flex-shrink: 0;
}
.ticker-tag.breaking {
  background: rgba(239, 68, 68, 0.12); color: var(--red-2);
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.ticker-tag.prediction {
  background: rgba(59, 130, 246, 0.1); color: var(--accent-2);
  border: 1px solid rgba(59, 130, 246, 0.3);
}
.ticker-text {
  font-size: 13px; color: var(--text-dim);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ticker-text b { color: var(--text); }
.user-chip {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 12px 6px 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  font-size: 12px;
}
.user-avatar {
  width: 28px; height: 28px; border-radius: 6px;
  background: linear-gradient(135deg, var(--accent), var(--purple));
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px; color: white;
}
.user-name { font-weight: 600; line-height: 1.1; }
.user-role { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.6px; }

/* Nav row */
.app-nav {
  display: flex; gap: 0; padding: 0 24px;
  overflow-x: auto; scrollbar-width: none;
}
.app-nav::-webkit-scrollbar { display: none; }
.nav-link {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 16px; border: none; background: none;
  color: var(--text-dim); text-decoration: none;
  font-size: 12px; font-weight: 600; letter-spacing: 0.6px;
  text-transform: uppercase;
  border-bottom: 2px solid transparent;
  white-space: nowrap; cursor: pointer;
  transition: color 150ms, border-color 150ms, background 150ms;
}
.nav-link:hover { color: var(--text); background: rgba(255, 255, 255, 0.02); }
.nav-link.active {
  color: var(--accent-2);
  border-bottom-color: var(--accent);
  background: linear-gradient(180deg, transparent, rgba(59, 130, 246, 0.08));
}
.nav-link svg { width: 14px; height: 14px; opacity: 0.85; }

/* ────────  PAGE BASE  ──────── */
.page {
  max-width: 1480px;
  margin: 0 auto;
  padding: 28px 28px 80px;
}
@media (max-width: 820px) {
  .page { padding: 20px 16px 60px; }
  .app-bar-top {
    grid-template-columns: auto 1fr auto;
    gap: 12px;
    padding: 12px 16px;
  }
  .status-pill, .ticker { display: none; }
  .app-nav { padding: 0 8px; }
  .nav-link { padding: 10px 12px; font-size: 11px; }
}

/* ────────  PANEL (top gradient accent)  ──────── */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 0;
  position: relative;
  overflow: hidden;
}
.panel::before {
  content: ''; position: absolute; inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.6;
}
.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px; border-bottom: 1px solid var(--border);
  gap: 14px; flex-wrap: wrap;
}
.panel-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 14px; font-weight: 700; letter-spacing: 0.3px;
  text-transform: uppercase;
}
.panel-icon {
  width: 32px; height: 32px; border-radius: 8px;
  background: var(--bg-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--accent-2);
}
.panel-icon svg { width: 16px; height: 16px; }
.panel-subtitle {
  font-size: 11px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.7px; font-weight: 500;
}
.panel-body { padding: 22px; }

/* ────────  SECTION / HEADINGS  ──────── */
.section-head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin: 24px 4px 14px;
  gap: 14px; flex-wrap: wrap;
}
.section-title {
  font-size: 12px; font-weight: 700; letter-spacing: 1.2px;
  color: var(--text-dim); text-transform: uppercase;
}
.section-meta {
  font-size: 11px; color: var(--text-muted); letter-spacing: 0.4px;
}

/* ────────  STATS BOX (labeled rectangle)  ──────── */
.stat-box {
  padding: 10px 12px; border: 1px solid var(--border);
  border-radius: 7px; background: var(--bg-2);
  min-width: 76px;
}
.stat-box .label {
  font-size: 9px; font-weight: 700; letter-spacing: 1px;
  color: var(--text-muted); text-transform: uppercase; margin-bottom: 3px;
}
.stat-box .value {
  font-family: var(--font-mono); font-size: 13px; font-weight: 600;
  color: var(--text); letter-spacing: -0.2px;
}

/* ────────  PILLS / BADGES  ──────── */
.pill {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 9px; border-radius: 14px;
  font-size: 10px; font-weight: 600; letter-spacing: 0.3px;
  background: var(--bg-2); border: 1px solid var(--border);
  color: var(--text-dim);
}
.pill.bullish { background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.3); color: var(--green-2); }
.pill.bearish { background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: var(--red-2); }
.pill.neutral { background: rgba(148, 163, 184, 0.08); border-color: rgba(148, 163, 184, 0.2); color: var(--text-dim); }
.pill.watchful { background: rgba(139, 92, 246, 0.1); border-color: rgba(139, 92, 246, 0.3); color: var(--purple-2); }
.pill.mixed { background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.3); color: var(--yellow-2); }

.regime-indicator {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
  text-transform: uppercase;
}
.regime-indicator::before {
  content: ''; width: 7px; height: 7px; border-radius: 50%;
}
.regime-indicator.bullish { color: var(--green-2); }
.regime-indicator.bullish::before { background: var(--green); }
.regime-indicator.bearish { color: var(--red-2); }
.regime-indicator.bearish::before { background: var(--red); }
.regime-indicator.neutral { color: var(--text-dim); }
.regime-indicator.neutral::before { background: var(--text-muted); }
.regime-indicator.watchful { color: var(--purple-2); }
.regime-indicator.watchful::before { background: var(--purple); }
.regime-indicator.mixed { color: var(--yellow-2); }
.regime-indicator.mixed::before { background: var(--yellow); }

.category-tag {
  display: inline-block; padding: 4px 10px;
  font-size: 10px; font-weight: 800; letter-spacing: 1px;
  text-transform: uppercase; border-radius: 4px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.25);
  color: var(--accent-2);
}
.featured-tag {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: 4px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: var(--yellow-2);
  font-size: 9px; font-weight: 800; letter-spacing: 1px;
  text-transform: uppercase;
}
.featured-tag::before { content: '★'; color: var(--yellow); }

.feature-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 5px 10px; border-radius: 6px;
  background: var(--bg-2); border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 11px; font-weight: 500;
}
.feature-chip::before { content: '•'; color: var(--accent); font-weight: 900; }

/* ────────  FILTER CHIPS (ALL / HIGH / MEDIUM / LOW)  ──────── */
.filter-bar {
  display: flex; gap: 2px; padding: 3px;
  background: var(--bg-2); border: 1px solid var(--border);
  border-radius: 8px; width: fit-content;
}
.filter-chip {
  padding: 6px 14px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.7px; text-transform: uppercase;
  background: transparent; color: var(--text-dim);
  border: none; border-radius: 5px; cursor: pointer;
  transition: all 150ms;
}
.filter-chip:hover { color: var(--text); }
.filter-chip.active {
  background: var(--accent); color: white;
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.3);
}

/* ────────  TABLE (dense, monospace numbers)  ──────── */
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table thead th {
  text-align: left; padding: 10px 14px;
  font-size: 10px; font-weight: 700; letter-spacing: 1px;
  color: var(--text-muted); text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}
.data-table tbody td {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  color: var(--text);
}
.data-table tbody tr:hover { background: rgba(59, 130, 246, 0.03); }
.data-table .num {
  font-family: var(--font-mono); text-align: right;
  font-variant-numeric: tabular-nums;
}
.data-table td.num-pos { color: var(--green-2); }
.data-table td.num-neg { color: var(--red-2); }

/* ────────  SIDEBAR (module sub-nav)  ──────── */
.page-with-sidebar {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 22px;
}
@media (max-width: 900px) { .page-with-sidebar { grid-template-columns: 1fr; } }
.sidebar {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden; align-self: start;
  position: sticky; top: 92px;
}
.sidebar-head {
  padding: 16px 18px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 11px;
}
.sidebar-head .icon {
  width: 34px; height: 34px; border-radius: 7px;
  background: var(--bg-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--accent-2);
}
.sidebar-head .label {
  font-size: 12px; font-weight: 800; letter-spacing: 1.2px;
  text-transform: uppercase;
}
.sidebar-nav { padding: 8px; }
.sidebar-link {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 7px;
  color: var(--text-dim); text-decoration: none;
  font-size: 13px; font-weight: 500;
  transition: all 150ms; margin-bottom: 2px;
}
.sidebar-link:hover { color: var(--text); background: var(--bg-2); }
.sidebar-link.active {
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.12), transparent);
  color: var(--accent-2);
  border-left: 2px solid var(--accent); padding-left: 10px;
}
.sidebar-link svg { width: 15px; height: 15px; opacity: 0.8; }

/* ────────  EMPTY / LOADING  ──────── */
.loading, .empty {
  text-align: center; padding: 60px 20px;
  color: var(--text-muted); font-size: 14px;
}
.empty h2 { font-size: 18px; color: var(--text); margin-bottom: 8px; font-weight: 700; }

/* Utility */
.hstack { display: flex; align-items: center; gap: 10px; }
.vstack { display: flex; flex-direction: column; gap: 10px; }
.grow { flex: 1 1 auto; min-width: 0; }
.muted { color: var(--text-muted); }
.mono { font-family: var(--font-mono); }
.nowrap { white-space: nowrap; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
@media (max-width: 900px) {
  .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
}
"""


# Icon set — inline SVGs, 16x16 via currentColor. Reusable across pages.
ICONS = {
    "terminal": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
    "macro": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    "tactical": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    "dev": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    "guide": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    "signal": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    "theme": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 2 7l10 5 10-5-10-5z"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
    "asset": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
    "risk": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    "brain": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z"/></svg>',
    "source": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
    "pulse": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    "podcast": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 18 0"/><path d="M6 17a3 3 0 0 1 0-6h2v6z"/><path d="M18 17a3 3 0 0 0 0-6h-2v6z"/></svg>',
    "check": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "activity": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
}


def render_shell(
    active: str,
    body: str,
    *,
    title: str = "Macro Positioning",
    ticker_tag: str = "STATUS",
    ticker_label: str = "",
    ticker_value: str = "",
    status_label: str = "Terminal Active",
) -> str:
    """Wrap page body in the shared shell.

    `active` must match one of the NAV_ITEMS keys ('terminal', 'positioning',
    'tactical', 'dev', 'guide'). Unknown falls back to no highlight.
    """

    # Build nav
    nav_links = []
    for key, label, href in NAV_ITEMS:
        klass = "nav-link active" if key == active else "nav-link"
        icon = ICONS.get(key, "")
        nav_links.append(
            f'<a href="{href}" class="{klass}">{icon}<span>{label}</span></a>'
        )
    nav_html = "".join(nav_links)

    # Ticker tag styling
    tag_classes = "ticker-tag"
    up = (ticker_tag or "").upper()
    if up == "BREAKING":
        tag_classes += " breaking"
    elif up == "PREDICTION":
        tag_classes += " prediction"

    ticker_block = ""
    if ticker_label or ticker_value:
        ticker_block = (
            f'<div class="ticker">'
            f'<span class="{tag_classes}">{up or "LIVE"}</span>'
            f'<span class="ticker-text"><b>{ticker_label or ""}</b> {ticker_value or ""}</span>'
            f'</div>'
        )
    else:
        ticker_block = '<div class="ticker"></div>'

    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
        f'<title>{title}</title>'
        f'<style>{SHARED_CSS}</style>'
        '</head><body>'
        '<header class="app-bar">'
        '<div class="app-bar-top">'
        '<div class="brand">'
        '<div class="brand-mark">MP</div>'
        '<div class="brand-text">'
        '<div class="brand-title">Macro Positioning</div>'
        '<div class="brand-sub">Institutional Terminal</div>'
        '</div>'
        '</div>'
        f'<span class="status-pill"><span class="dot"></span>{status_label}</span>'
        f'{ticker_block}'
        '<div></div>'
        '<div class="user-chip">'
        '<div class="user-avatar">T</div>'
        '<div>'
        '<div class="user-name">Thomas</div>'
        '<div class="user-role">Operator</div>'
        '</div>'
        '</div>'
        '</div>'
        f'<nav class="app-nav">{nav_html}</nav>'
        '</header>'
        '<main class="page">'
        f'{body}'
        '</main>'
        '</body></html>'
    )
