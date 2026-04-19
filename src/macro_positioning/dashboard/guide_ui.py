"""Platform guide — reference page with module docs + architecture overview."""

from __future__ import annotations

from macro_positioning.dashboard.shell import ICONS, render_shell


GUIDE_CSS = r"""
.guide-hero {
  text-align: center; max-width: 760px; margin: 28px auto 40px;
}
.guide-kicker {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 99px;
  background: rgba(139, 92, 246, 0.08);
  border: 1px solid rgba(139, 92, 246, 0.28);
  color: var(--purple-2);
  font-size: 11px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase;
}
.guide-title {
  font-size: 38px; font-weight: 800; letter-spacing: -1.2px;
  margin: 16px 0 10px;
}
.guide-title span { color: var(--purple-2); }
.guide-subtitle { font-size: 14px; color: var(--text-dim); line-height: 1.55; }

.guide-sections { display: flex; flex-direction: column; gap: 16px; }
.ref-doc {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px 24px;
}
.ref-doc h3 {
  font-size: 14px; font-weight: 700; letter-spacing: 0.4px;
  text-transform: uppercase; margin-bottom: 8px;
  color: var(--accent-2);
}
.ref-doc p { font-size: 13px; color: var(--text-dim); line-height: 1.6; margin-bottom: 10px; }
.ref-doc ul { margin: 8px 0 0 20px; color: var(--text-dim); font-size: 13px; line-height: 1.7; }
.ref-doc code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--bg-2); padding: 2px 6px; border-radius: 4px;
  color: var(--accent-2); border: 1px solid var(--border);
}
"""


def guide_dashboard_html() -> str:
    body = f"""
    <style>{GUIDE_CSS}</style>
    <section class="guide-hero">
      <span class="guide-kicker">◆ Platform Guide</span>
      <h1 class="guide-title">Everything about the <span>signal foundation</span></h1>
      <p class="guide-subtitle">
        Architecture overview, data sources, integration contracts, and what each module does.
      </p>
    </section>

    <div class="guide-sections">

      <div class="ref-doc">
        <h3>Architecture: Two Repos, Bidirectional Contract</h3>
        <p>
          <b>macro-analyzer</b> (this repo) is the strategic brain —
          ingests newsletters, FRED data, podcasts, synthesizes macro theses via Gemini 2.5 Pro through N8N.
          Outputs actionable signals, directional biases, risks.
        </p>
        <p>
          <b>Trading-Agent-V1-CODEX</b> is the tactical executor — receives TradingView webhooks,
          applies a deterministic decision engine, gates decisions against the macro view, tracks lifecycle,
          reports trade outcomes back to the macro side for source attribution.
        </p>
        <p>
          The two talk via HTTPS contract pinned at <code>CONTRACT_VERSION = 1.0.0</code>. Drift is blocked
          by CI (<code>schema-export-check</code>, <code>schema-drift-check</code>) and an auto-PR bot
          (<code>schema-mirror-pr</code>) that keeps both sides in sync.
        </p>
      </div>

      <div class="ref-doc">
        <h3>Modules at a Glance</h3>
        <ul>
          <li><b>Terminal</b> — platform hub, module launcher</li>
          <li><b>Positioning</b> — actionable signals, theme map, per-asset drilldown (primary operator view)</li>
          <li><b>Tactical</b> — read-only inspection of tactical-executor (events, decisions, lifecycle)</li>
          <li><b>Dev</b> — build checklist, brain activity telemetry, source connectivity, system health</li>
          <li><b>Guide</b> — this page</li>
        </ul>
      </div>

      <div class="ref-doc">
        <h3>Data Sources</h3>
        <ul>
          <li><b>FRED</b> — 50 macro series (Fed funds, Treasuries, CPI, PCE, employment, housing, etc.)</li>
          <li><b>Personal Gmail</b> — 17 financial newsletters (MacroMicro, Doomberg, Kaoboy, Blockworks, Capital Flows, Weekly Wizdom, more)</li>
          <li><b>Google News RSS</b> — macro topic feeds (inflation, rates, commodities, geopolitics)</li>
          <li><b>Finnhub</b> — per-ticker news + sentiment (60 calls/min free tier)</li>
          <li><b>Podcasts</b> — Forward Guidance, Wolf of All Streets, Real Vision Journey Man (full transcription via Gemini audio), Moonshots (show notes)</li>
          <li><b>Substack RSS</b> — complements Gmail; pulls public posts from substack-hosted sources</li>
        </ul>
      </div>

      <div class="ref-doc">
        <h3>The Brain</h3>
        <p>
          Primary: Gemini 2.5 Pro via N8N webhook (<code>MPA_N8N_WEBHOOK_URL</code>). Unlimited via user's Vertex access.
          Fallback: heuristic extractor (keyword-based, deterministic, always available).
        </p>
        <p>
          Every brain call is logged to the <code>brain_calls</code> SQLite table with latency, backend, model,
          success state, input/output size. Visible on the <b>Dev</b> dashboard.
        </p>
      </div>

      <div class="ref-doc">
        <h3>Out of Scope (Future Phases)</h3>
        <ul>
          <li>Trade execution logic (Layer 3 LLM for trade analysis, future)</li>
          <li>Market structure data — dark pools, options/GEX, open interest (Phase 2)</li>
          <li>Dual-snapshot close capture for trade-outcome attribution (deferred)</li>
          <li>ffmpeg audio chunking for >1hr podcasts</li>
          <li>Public deployment to Render / Railway</li>
        </ul>
      </div>

    </div>
    """

    return render_shell(
        active="guide",
        body=body,
        title="Macro Positioning · Guide",
        ticker_tag="Reference",
        ticker_label="Guide:",
        ticker_value="Architecture · data sources · integration contract",
    )
