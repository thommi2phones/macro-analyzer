"""Terminal hub — the landing page.

Grid of module cards (Positioning, Tactical, Dev, Guide) styled like an
institutional terminal's "features" page: category tag, title, tagline,
description, feature chips, CTA. Serves as the entry point for the
operator — click a card to enter the module.
"""

from __future__ import annotations

from macro_positioning.dashboard.shell import ICONS, render_shell


# Module card definitions. Each is a card on the hub.
MODULE_CARDS = [
    {
        "id": "positioning",
        "category": "Macro & Economy",
        "featured": True,
        "title": "Macro Positioning Brief",
        "tagline": "Actionable signals, regime, and per-asset bias",
        "description": (
            "Top trade expressions grouped LONG/SHORT/WATCH, theme direction "
            "map, per-asset drilldown. Built from newsletter synthesis + FRED "
            "validation. Inline tactical state annotation where available."
        ),
        "chips": ["Top Actionable Signals", "Theme Heatmap", "Per-Asset Bias", "Regime Summary"],
        "cta": "Open Positioning",
        "href": "/positioning",
        "icon": "macro",
        "accent": "var(--accent)",
    },
    {
        "id": "tactical",
        "category": "Tactical",
        "featured": False,
        "title": "Tactical State",
        "tagline": "Read-only inspection of the tactical-executor",
        "description": (
            "Live view of active setups, the latest agent_packet decision with "
            "macro gate applied, recent events feed, and lifecycle timeline. "
            "Pulled from the tactical-executor service in real time."
        ),
        "chips": ["Active Setups", "Decision + Macro Gate", "Events Feed", "Lifecycle"],
        "cta": "Inspect Tactical",
        "href": "/tactical",
        "icon": "tactical",
        "accent": "var(--teal)",
    },
    {
        "id": "dev",
        "category": "Ops",
        "featured": False,
        "title": "Dev Status",
        "tagline": "Build progress, brain activity, system health",
        "description": (
            "Interactive build checklist. Brain call telemetry (backend, latency, "
            "model, success). Data source connectivity chips. What's shipped vs "
            "what's next, sorted by priority."
        ),
        "chips": ["Build Checklist", "Brain Activity", "Source Health", "Telemetry"],
        "cta": "Open Dev",
        "href": "/dev",
        "icon": "dev",
        "accent": "var(--yellow)",
    },
    {
        "id": "guide",
        "category": "Reference",
        "featured": False,
        "title": "Platform Guide",
        "tagline": "What each module does and how to use it",
        "description": (
            "Feature documentation, data source catalog, architecture overview, "
            "integration contracts, and roadmap. Start here if you're new to "
            "the system."
        ),
        "chips": ["Module Docs", "Data Sources", "Architecture", "Roadmap"],
        "cta": "Read the Guide",
        "href": "/guide",
        "icon": "guide",
        "accent": "var(--purple)",
    },
]


def _module_card_html(card: dict) -> str:
    featured = '<span class="featured-tag">Featured</span>' if card.get("featured") else ""
    chips = "".join(f'<span class="feature-chip">{c}</span>' for c in card.get("chips", []))
    icon_svg = ICONS.get(card.get("icon", "terminal"), ICONS["terminal"])
    accent = card.get("accent", "var(--accent)")
    return f"""
    <a href="{card['href']}" class="hub-card">
      <div class="hub-card-preview" style="--hub-accent:{accent}">
        <div class="hub-card-icon">{icon_svg}</div>
        {featured}
      </div>
      <div class="hub-card-body">
        <div class="category-tag">{card['category']}</div>
        <div class="hub-card-title">{card['title']}</div>
        <div class="hub-card-tagline">{card['tagline']}</div>
        <p class="hub-card-desc">{card['description']}</p>
        <div class="hub-card-chips">{chips}</div>
        <div class="hub-card-cta">{card['cta']} <span class="arrow">→</span></div>
      </div>
    </a>
    """


HUB_CSS = """
.hub-intro {
  text-align: center; max-width: 760px; margin: 20px auto 40px;
}
.hub-kicker {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 99px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.25);
  color: var(--accent-2);
  font-size: 11px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase;
}
.hub-title {
  font-size: 42px; font-weight: 800; letter-spacing: -1.2px;
  margin: 16px 0 10px; line-height: 1.1;
}
.hub-title span { color: var(--accent-2); }
.hub-subtitle { color: var(--text-dim); font-size: 15px; line-height: 1.55; }
.hub-stats {
  display: flex; gap: 48px; justify-content: center;
  margin: 32px 0 16px; flex-wrap: wrap;
}
.hub-stat { text-align: center; }
.hub-stat .n { font-size: 28px; font-weight: 800; letter-spacing: -0.5px; font-family: var(--font-mono); }
.hub-stat .l { font-size: 10px; color: var(--text-muted); letter-spacing: 1.4px; text-transform: uppercase; font-weight: 600; margin-top: 3px; }
.hub-filter-bar {
  display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 22px;
  padding-bottom: 20px; border-bottom: 1px solid var(--border);
}
.hub-filter {
  padding: 7px 14px; border-radius: 6px;
  background: var(--surface); border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 11px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase;
  cursor: pointer;
}
.hub-filter.active {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.4);
  color: var(--accent-2);
}
.hub-grid {
  display: grid; gap: 20px;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
}
.hub-card {
  display: flex; flex-direction: column;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden;
  text-decoration: none; color: inherit;
  transition: transform 180ms, border-color 180ms, box-shadow 180ms;
  position: relative;
}
.hub-card::before {
  content: ''; position: absolute; inset: 0 0 auto 0;
  height: 2px; background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.45; transition: opacity 180ms;
}
.hub-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-hi);
  box-shadow: var(--shadow-lg);
}
.hub-card:hover::before { opacity: 1; }
.hub-card-preview {
  height: 130px; position: relative;
  background:
    radial-gradient(circle at 30% 20%, color-mix(in srgb, var(--hub-accent) 30%, transparent) 0%, transparent 60%),
    linear-gradient(135deg, var(--bg-2) 0%, var(--bg-1) 100%);
  border-bottom: 1px solid var(--border);
  overflow: hidden;
}
.hub-card-preview::after {
  /* grid overlay */
  content: ''; position: absolute; inset: 0;
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 40px 40px;
  opacity: 0.15;
  mask-image: linear-gradient(180deg, rgba(0,0,0,0.6), transparent);
}
.hub-card-icon {
  position: absolute; left: 18px; bottom: 14px;
  width: 44px; height: 44px; border-radius: 10px;
  background: var(--bg-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--hub-accent);
  box-shadow: 0 8px 20px -4px rgba(0, 0, 0, 0.4);
}
.hub-card-icon svg { width: 20px; height: 20px; }
.hub-card .featured-tag {
  position: absolute; top: 14px; right: 14px;
}
.hub-card-body { padding: 18px 20px 20px; flex: 1; display: flex; flex-direction: column; }
.hub-card-body .category-tag { margin-bottom: 12px; align-self: flex-start; }
.hub-card-title {
  font-size: 18px; font-weight: 700; letter-spacing: -0.3px;
  margin-bottom: 4px;
}
.hub-card-tagline { font-size: 13px; color: var(--text-dim); margin-bottom: 12px; }
.hub-card-desc {
  font-size: 13px; color: var(--text-dim); line-height: 1.55;
  margin-bottom: 14px;
}
.hub-card-chips {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-bottom: 16px;
}
.hub-card-cta {
  margin-top: auto; padding-top: 14px;
  border-top: 1px solid var(--border);
  font-size: 12px; font-weight: 700; letter-spacing: 0.8px;
  color: var(--accent-2); text-transform: uppercase;
  display: flex; align-items: center; gap: 6px;
}
.hub-card-cta .arrow { transition: transform 180ms; }
.hub-card:hover .hub-card-cta .arrow { transform: translateX(4px); }
"""


def terminal_hub_html() -> str:
    cards = "".join(_module_card_html(c) for c in MODULE_CARDS)

    body = f"""
    <style>{HUB_CSS}</style>
    <section class="hub-intro">
      <span class="hub-kicker">◆ Platform Hub</span>
      <h1 class="hub-title">Your macro positioning, <span>at a glance</span></h1>
      <p class="hub-subtitle">
        Four purpose-built modules for operating the signal foundation.
        Open any card to enter its workspace.
      </p>
      <div class="hub-stats">
        <div class="hub-stat"><div class="n" id="stat-theses">—</div><div class="l">Active Theses</div></div>
        <div class="hub-stat"><div class="n" id="stat-sources">—</div><div class="l">Data Sources</div></div>
        <div class="hub-stat"><div class="n" id="stat-brain">—</div><div class="l">Brain Calls</div></div>
        <div class="hub-stat"><div class="n" id="stat-docs">—</div><div class="l">Documents</div></div>
      </div>
    </section>

    <div class="hub-filter-bar">
      <button class="hub-filter active">All Modules</button>
      <button class="hub-filter">Macro</button>
      <button class="hub-filter">Tactical</button>
      <button class="hub-filter">Ops</button>
      <button class="hub-filter">Reference</button>
    </div>

    <div class="hub-grid">
      {cards}
    </div>

    <script>
    (async function(){{
      try {{
        const [ops, cmd, brain] = await Promise.all([
          fetch('/api/dashboard/ops').then(r => r.json()).catch(() => null),
          fetch('/api/dashboard/command-center').then(r => r.json()).catch(() => null),
          fetch('/api/dashboard/brain/stats').then(r => r.json()).catch(() => null),
        ]);
        document.getElementById('stat-theses').textContent = cmd?.unique_theses ?? '—';
        document.getElementById('stat-sources').textContent = (ops?.newsletter_sources?.length ?? 0) + (ops?.data_sources?.length ?? 0);
        document.getElementById('stat-brain').textContent = brain?.total_calls ?? 0;
        document.getElementById('stat-docs').textContent = ops?.db_stats?.documents ?? 0;
      }} catch (e) {{}}
    }})();
    </script>
    """

    return render_shell(
        active="terminal",
        body=body,
        title="Macro Positioning · Terminal",
        ticker_tag="Live",
        ticker_label="All systems nominal.",
        ticker_value="Pipeline + brain + integration contract v1.0.0 active.",
    )
