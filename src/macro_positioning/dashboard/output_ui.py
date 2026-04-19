"""Positioning dashboard — trader-facing output UI, rebuilt on shared shell.

Layout (top → bottom):
  1. Regime banner + brain meta (compact strip)
  2. Directional mix KPIs (bull/bear/neutral + theme count + avg conf)
  3. Top actionable signals (LONG/SHORT/WATCH per asset with tactical annotation)
  4. Theme direction map (sector-card style)
  5. Per-asset breakdown (asset cards with regime + conviction)
  6. Risks to watch
  7. Active theses (expandable)
"""

from __future__ import annotations

from macro_positioning.dashboard.shell import ICONS, render_shell


POSITIONING_CSS = r"""
.regime-strip {
  background: linear-gradient(135deg, var(--surface) 0%, var(--bg-2) 100%);
  border: 1px solid var(--border-hi);
  border-radius: 14px; padding: 20px 24px;
  margin-bottom: 20px;
  position: relative; overflow: hidden;
}
.regime-strip::before {
  content: ''; position: absolute; inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), var(--green), transparent);
}
.regime-strip::after {
  content: ''; position: absolute; right: -40px; top: -40px;
  width: 200px; height: 200px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.1), transparent 70%);
  pointer-events: none;
}
.regime-strip-head {
  display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
}
.regime-strip-head .label {
  font-size: 10px; letter-spacing: 1.5px; font-weight: 700;
  color: var(--text-dim); text-transform: uppercase;
}
.regime-strip-text {
  font-size: 16px; font-weight: 600; line-height: 1.45;
  color: var(--text); max-width: 80ch;
}
.regime-strip-meta {
  display: flex; gap: 18px; margin-top: 14px;
  font-size: 11px; color: var(--text-muted);
}
.regime-strip-meta b { color: var(--text); font-weight: 600; }

.kpi-row {
  display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 14px; margin-bottom: 22px;
}
@media (max-width: 900px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
  position: relative;
}
.kpi-card .kpi-label {
  font-size: 10px; letter-spacing: 1px; font-weight: 700;
  color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;
}
.kpi-card .kpi-value {
  font-family: var(--font-mono); font-size: 28px; font-weight: 700;
  letter-spacing: -0.8px; line-height: 1;
}
.kpi-card .kpi-subvalue {
  font-size: 10px; color: var(--text-muted); margin-top: 6px;
  text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600;
}
.kpi-card.kpi-bull .kpi-value { color: var(--green-2); }
.kpi-card.kpi-bear .kpi-value { color: var(--red-2); }
.kpi-card.kpi-accent .kpi-value { color: var(--accent-2); }
.kpi-card.kpi-purple .kpi-value { color: var(--purple-2); }

/* Signal hero */
.signal-panel { margin-bottom: 22px; }
.signal-groups {
  display: grid; gap: 20px;
  grid-template-columns: repeat(3, 1fr);
}
@media (max-width: 1100px) { .signal-groups { grid-template-columns: 1fr; } }
.signal-column {}
.signal-column-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; margin-bottom: 10px;
  border-radius: 7px;
}
.signal-column-head .title {
  font-size: 11px; font-weight: 800; letter-spacing: 1.2px; text-transform: uppercase;
}
.signal-column-head .count {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
}
.signal-column.long .signal-column-head { background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); }
.signal-column.long .signal-column-head .title { color: var(--green-2); }
.signal-column.long .signal-column-head .count { color: var(--green-2); }
.signal-column.short .signal-column-head { background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25); }
.signal-column.short .signal-column-head .title { color: var(--red-2); }
.signal-column.short .signal-column-head .count { color: var(--red-2); }
.signal-column.watch .signal-column-head { background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.25); }
.signal-column.watch .signal-column-head .title { color: var(--purple-2); }
.signal-column.watch .signal-column-head .count { color: var(--purple-2); }

.signal-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
  transition: border-color 150ms, transform 150ms;
}
.signal-card:hover { border-color: var(--border-hi); transform: translateX(2px); }
.signal-card-top {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;
}
.signal-asset {
  font-family: var(--font-mono); font-size: 16px; font-weight: 700;
  letter-spacing: 0.5px; text-transform: uppercase;
}
.signal-meta {
  font-size: 10px; color: var(--text-muted); margin-top: 2px;
  text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600;
}
.signal-conv {
  text-align: right; flex-shrink: 0;
}
.signal-conv .num {
  font-family: var(--font-mono); font-size: 16px; font-weight: 700;
}
.signal-conv .lbl {
  font-size: 9px; color: var(--text-muted); letter-spacing: 0.8px;
  text-transform: uppercase; font-weight: 600;
}
.signal-bar {
  height: 4px; background: var(--bg-0); border-radius: 2px;
  overflow: hidden; margin: 10px 0 10px;
}
.signal-bar > div { height: 100%; background: currentColor; }
.signal-column.long .signal-card { border-left: 2px solid var(--green); }
.signal-column.long .signal-bar > div { background: var(--green); }
.signal-column.long .signal-asset, .signal-column.long .signal-conv .num { color: var(--green-2); }
.signal-column.short .signal-card { border-left: 2px solid var(--red); }
.signal-column.short .signal-bar > div { background: var(--red); }
.signal-column.short .signal-asset, .signal-column.short .signal-conv .num { color: var(--red-2); }
.signal-column.watch .signal-card { border-left: 2px solid var(--purple); }
.signal-column.watch .signal-bar > div { background: var(--purple); }
.signal-column.watch .signal-asset, .signal-column.watch .signal-conv .num { color: var(--purple-2); }
.signal-rat {
  font-size: 12px; color: var(--text-dim); line-height: 1.5;
  margin-bottom: 10px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.signal-tact {
  display: flex; gap: 6px; flex-wrap: wrap;
  padding-top: 10px; border-top: 1px dashed var(--border);
}
.signal-tact .pill-tact {
  font-size: 9px; font-weight: 700; letter-spacing: 0.6px;
  background: rgba(20, 184, 166, 0.1); border: 1px solid rgba(20, 184, 166, 0.28);
  color: var(--teal); padding: 3px 8px; border-radius: 5px; text-transform: uppercase;
}
.signal-tact .muted-tact {
  font-size: 10px; color: var(--text-mute-2); font-style: italic; letter-spacing: 0.3px;
}

.empty-col {
  padding: 24px 14px; text-align: center;
  border: 1px dashed var(--border); border-radius: 9px;
  color: var(--text-muted); font-size: 12px;
}

/* Theme cards (sector-card style) */
.theme-grid {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}
.theme-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
  position: relative; overflow: hidden;
}
.theme-card.bullish { border-top: 2px solid var(--green); }
.theme-card.bearish { border-top: 2px solid var(--red); }
.theme-card.neutral { border-top: 2px solid var(--text-muted); }
.theme-card.mixed { border-top: 2px solid var(--yellow); }
.theme-card.watchful { border-top: 2px solid var(--purple); }
.theme-card-head {
  display: flex; justify-content: space-between; align-items: start;
  margin-bottom: 12px;
}
.theme-card-name {
  font-family: var(--font-mono); font-size: 14px; font-weight: 700;
  letter-spacing: 0.3px; text-transform: uppercase;
}
.theme-card-num {
  font-family: var(--font-mono); font-size: 16px; font-weight: 700;
}
.theme-bar {
  display: flex; height: 22px; border-radius: 5px; overflow: hidden;
  background: var(--bg-2); margin-bottom: 10px;
}
.theme-bar > div {
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-mono); font-size: 10px; font-weight: 700;
  color: white; min-width: 22px;
}
.theme-stats {
  display: flex; justify-content: space-between;
  font-size: 10px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;
}

/* Asset breakdown grid */
.asset-grid {
  display: grid; gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
}
.asset-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 9px; padding: 12px 14px;
  display: flex; justify-content: space-between; align-items: center;
  gap: 10px;
}
.asset-card-left {}
.asset-card-name {
  font-family: var(--font-mono); font-size: 14px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.3px;
}
.asset-card-meta {
  font-size: 10px; color: var(--text-muted); margin-top: 2px;
  letter-spacing: 0.4px; font-weight: 600;
}
.asset-card-right { text-align: right; }
.asset-card-conv {
  font-family: var(--font-mono); font-size: 13px; font-weight: 700;
  margin-top: 3px;
}
.asset-card.bullish .asset-card-conv { color: var(--green-2); }
.asset-card.bearish .asset-card-conv { color: var(--red-2); }
.asset-card.neutral .asset-card-conv { color: var(--text-dim); }
.asset-card.mixed .asset-card-conv { color: var(--yellow-2); }
.asset-card.watchful .asset-card-conv { color: var(--purple-2); }

/* Risks */
.risks-grid {
  display: grid; gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
}
.risk-item {
  background: rgba(239, 68, 68, 0.03);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-left: 3px solid var(--red);
  border-radius: 8px;
  padding: 13px 14px 13px 40px;
  font-size: 13px; line-height: 1.55;
  position: relative;
}
.risk-item::before {
  content: '⚠'; position: absolute; left: 14px; top: 12px;
  color: var(--red); font-size: 15px;
}

/* Theses list */
.theses-list { display: flex; flex-direction: column; gap: 6px; }
.thesis-row {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 9px; overflow: hidden;
}
.thesis-summary {
  padding: 12px 14px; display: flex; align-items: center; gap: 12px;
  cursor: pointer; transition: background 150ms;
}
.thesis-summary:hover { background: var(--surface-hi); }
.thesis-theme {
  font-family: var(--font-mono); font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.5px;
  min-width: 110px; color: var(--text-dim);
}
.thesis-text {
  flex: 1; font-size: 13px; line-height: 1.45; color: var(--text);
  overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.thesis-conf-chip {
  font-family: var(--font-mono); font-size: 11px; font-weight: 700;
  padding: 3px 8px; background: var(--bg-2); border-radius: 4px;
  color: var(--text-dim);
}
.thesis-detail {
  padding: 0 18px; max-height: 0; overflow: hidden;
  transition: max-height 250ms, padding 250ms;
  border-top: 1px solid transparent;
  font-size: 12px; color: var(--text-dim); line-height: 1.6;
}
.thesis-row.open .thesis-detail {
  max-height: 800px; padding: 14px 18px 16px;
  border-top-color: var(--border);
}
.thesis-detail .label-inline {
  font-size: 9px; color: var(--text-muted); letter-spacing: 0.8px;
  text-transform: uppercase; font-weight: 700; margin-right: 8px;
}
.thesis-detail ul { margin: 6px 0 10px 20px; padding: 0; }
.thesis-detail li { margin-bottom: 4px; }
"""


def positioning_dashboard_html() -> str:
    body = f"""
    <style>{POSITIONING_CSS}</style>

    <div id="loading" class="loading">Loading macro positioning…</div>
    <div id="empty" class="empty" style="display:none">
      <h2>No analysis yet</h2>
      <p>Run a pipeline to generate theses.</p>
    </div>

    <div id="content" style="display:none">

      <!-- 1. Regime strip -->
      <div class="regime-strip">
        <div class="regime-strip-head">
          <span class="label">Current Macro Regime</span>
          <span id="tact-chip" class="pill"></span>
        </div>
        <div id="regime-text" class="regime-strip-text">—</div>
        <div class="regime-strip-meta">
          <span>⏱ <b id="regime-ts">—</b></span>
          <span id="brain-meta">—</span>
        </div>
      </div>

      <!-- 2. KPI row -->
      <div class="kpi-row">
        <div class="kpi-card kpi-bull">
          <div class="kpi-label">Bullish</div>
          <div id="kpi-bull" class="kpi-value">0</div>
          <div class="kpi-subvalue">Theses</div>
        </div>
        <div class="kpi-card kpi-bear">
          <div class="kpi-label">Bearish</div>
          <div id="kpi-bear" class="kpi-value">0</div>
          <div class="kpi-subvalue">Theses</div>
        </div>
        <div class="kpi-card kpi-purple">
          <div class="kpi-label">Mixed / Watch</div>
          <div id="kpi-neutral" class="kpi-value">0</div>
          <div class="kpi-subvalue">Theses</div>
        </div>
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">Themes</div>
          <div id="kpi-themes" class="kpi-value">0</div>
          <div class="kpi-subvalue">Active</div>
        </div>
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">Avg Conviction</div>
          <div id="kpi-conf" class="kpi-value">0%</div>
          <div class="kpi-subvalue">Across all</div>
        </div>
      </div>

      <!-- 3. Top Actionable Signals -->
      <div class="panel signal-panel">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['signal']}</div>
            <span>Top Actionable Signals</span>
          </div>
          <div class="panel-subtitle">Hero view · grouped by side · tactical state inline</div>
        </div>
        <div class="panel-body">
          <div class="signal-groups">
            <div id="col-long" class="signal-column long">
              <div class="signal-column-head"><span class="title">Long</span><span class="count" id="count-long">0</span></div>
              <div id="signals-long"></div>
            </div>
            <div id="col-short" class="signal-column short">
              <div class="signal-column-head"><span class="title">Short</span><span class="count" id="count-short">0</span></div>
              <div id="signals-short"></div>
            </div>
            <div id="col-watch" class="signal-column watch">
              <div class="signal-column-head"><span class="title">Watch</span><span class="count" id="count-watch">0</span></div>
              <div id="signals-watch"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 4. Theme direction map -->
      <div class="panel" style="margin-bottom:22px">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['theme']}</div>
            <span>Theme Direction Map</span>
          </div>
          <div class="panel-subtitle"><span id="themes-count">—</span></div>
        </div>
        <div class="panel-body">
          <div class="theme-grid" id="theme-grid"></div>
        </div>
      </div>

      <!-- 5. Per-asset breakdown -->
      <div class="panel" style="margin-bottom:22px">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['asset']}</div>
            <span>Per-Asset Breakdown</span>
          </div>
          <div class="panel-subtitle"><span id="assets-count">—</span> · sorted by conviction</div>
        </div>
        <div class="panel-body">
          <div class="asset-grid" id="asset-grid"></div>
        </div>
      </div>

      <!-- 6. Risks -->
      <div class="panel" id="risks-panel" style="display:none; margin-bottom:22px">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon" style="color:var(--red-2)">{ICONS['risk']}</div>
            <span>Risks to Watch</span>
          </div>
          <div class="panel-subtitle"><span id="risks-count"></span></div>
        </div>
        <div class="panel-body">
          <div class="risks-grid" id="risks-grid"></div>
        </div>
      </div>

      <!-- 7. Active theses -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['brain']}</div>
            <span>Active Theses</span>
          </div>
          <div class="panel-subtitle"><span id="theses-count">—</span> · click to expand</div>
        </div>
        <div class="panel-body">
          <div id="theses-list" class="theses-list"></div>
        </div>
      </div>

    </div>

    <script>
    function escapeHtml(s){{ if(s==null) return ''; return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}

    async function load(){{
      try {{
        const [cmdR, memoR] = await Promise.all([
          fetch('/api/dashboard/command-center').then(r => r.json()),
          fetch('/memos/latest').then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        render(cmdR, memoR);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load: ' + e.message;
      }}
    }}

    function render(cmd, memo){{
      document.getElementById('loading').style.display = 'none';
      if (!cmd || !cmd.has_data){{
        document.getElementById('empty').style.display = 'block';
        return;
      }}
      document.getElementById('content').style.display = 'block';

      // Regime
      const regime = cmd.memo_summary || memo?.summary || 'No regime summary yet.';
      document.getElementById('regime-text').textContent = regime;
      if (cmd.generated_at){{
        const d = new Date(cmd.generated_at);
        document.getElementById('regime-ts').textContent = d.toLocaleString();
      }}
      // Tactical chip
      const chip = document.getElementById('tact-chip');
      if (cmd.tactical_reachable){{
        chip.className = 'pill bullish';
        chip.textContent = '● Tactical online';
      }} else {{
        chip.className = 'pill neutral';
        chip.textContent = '○ Tactical offline';
      }}
      const theseCount = cmd.theme_clusters?.length || 0;
      const avgConf = Math.round((cmd.avg_confidence || 0) * 100);

      // KPIs
      document.getElementById('kpi-bull').textContent = cmd.bullish_count || 0;
      document.getElementById('kpi-bear').textContent = cmd.bearish_count || 0;
      document.getElementById('kpi-neutral').textContent = cmd.neutral_count || 0;
      document.getElementById('kpi-themes').textContent = theseCount;
      document.getElementById('kpi-conf').textContent = avgConf + '%';

      // Signals
      const signals = cmd.actionable_signals || [];
      const groups = {{LONG: [], SHORT: [], WATCH: []}};
      signals.forEach(s => (groups[s.side] || groups.WATCH).push(s));

      renderSignalGroup('signals-long', 'count-long', groups.LONG);
      renderSignalGroup('signals-short', 'count-short', groups.SHORT);
      renderSignalGroup('signals-watch', 'count-watch', groups.WATCH);

      // Theme map
      const themes = cmd.theme_clusters || [];
      document.getElementById('themes-count').textContent = themes.length + ' active';
      const tg = document.getElementById('theme-grid');
      themes.forEach(c => {{
        const total = c.bullish + c.bearish + c.neutral + c.mixed + c.watchful;
        const pct = n => total ? (n/total*100).toFixed(0) : 0;
        let bar = '';
        if (c.bullish) bar += `<div style="width:${{pct(c.bullish)}}%;background:var(--green)">${{c.bullish}}</div>`;
        if (c.bearish) bar += `<div style="width:${{pct(c.bearish)}}%;background:var(--red)">${{c.bearish}}</div>`;
        if (c.mixed) bar += `<div style="width:${{pct(c.mixed)}}%;background:var(--yellow)">${{c.mixed}}</div>`;
        if (c.watchful) bar += `<div style="width:${{pct(c.watchful)}}%;background:var(--purple)">${{c.watchful}}</div>`;
        if (c.neutral) bar += `<div style="width:${{pct(c.neutral)}}%;background:var(--text-muted)">${{c.neutral}}</div>`;
        tg.innerHTML += `
          <div class="theme-card ${{c.dominant_direction}}">
            <div class="theme-card-head">
              <div>
                <div class="theme-card-name">${{escapeHtml(c.theme)}}</div>
                <div class="regime-indicator ${{c.dominant_direction}}" style="margin-top:6px">${{c.dominant_direction}}</div>
              </div>
              <div class="theme-card-num">${{(c.avg_confidence * 100).toFixed(0)}}%</div>
            </div>
            <div class="theme-bar">${{bar}}</div>
            <div class="theme-stats">
              <span>${{total}} THES${{total !== 1 ? 'ES' : 'IS'}}</span>
              <span>${{escapeHtml((c.top_assets || []).slice(0, 3).join(' · ').toUpperCase())}}</span>
            </div>
          </div>`;
      }});

      // Per-asset
      const assets = cmd.asset_breakdown || [];
      document.getElementById('assets-count').textContent = assets.length + ' asset' + (assets.length !== 1 ? 's' : '');
      const ag = document.getElementById('asset-grid');
      assets.forEach(a => {{
        ag.innerHTML += `
          <div class="asset-card ${{a.dominant_direction}}">
            <div class="asset-card-left">
              <div class="asset-card-name">${{escapeHtml(a.asset)}}</div>
              <div class="asset-card-meta">${{a.thesis_count}} THES${{a.thesis_count !== 1 ? 'ES' : 'IS'}}</div>
            </div>
            <div class="asset-card-right">
              <span class="regime-indicator ${{a.dominant_direction}}">${{a.dominant_direction}}</span>
              <div class="asset-card-conv">${{(a.confidence * 100).toFixed(0)}}%</div>
            </div>
          </div>`;
      }});

      // Risks
      const risks = (memo?.risks_to_watch) || cmd.risks_to_watch || [];
      if (risks.length){{
        document.getElementById('risks-panel').style.display = 'block';
        document.getElementById('risks-count').textContent = risks.length + ' flagged';
        const rg = document.getElementById('risks-grid');
        risks.forEach(r => {{
          const el = document.createElement('div');
          el.className = 'risk-item';
          el.textContent = r;
          rg.appendChild(el);
        }});
      }}

      // Theses
      const theses = cmd.theses || [];
      document.getElementById('theses-count').textContent = theses.length + ' active';
      const tl = document.getElementById('theses-list');
      theses.forEach(t => {{
        const conf = Math.round((t.confidence || 0) * 100);
        const positioning = (t.implied_positioning || []).map(p => `<li>${{escapeHtml(p)}}</li>`).join('');
        const el = document.createElement('div');
        el.className = 'thesis-row';
        el.innerHTML = `
          <div class="thesis-summary">
            <span class="regime-indicator ${{t.direction}}">${{t.direction}}</span>
            <span class="thesis-theme">${{escapeHtml(t.theme)}}</span>
            <span class="thesis-text">${{escapeHtml(t.thesis)}}</span>
            <span class="thesis-conf-chip">${{conf}}%</span>
          </div>
          <div class="thesis-detail">
            <div><span class="label-inline">Horizon</span>${{escapeHtml(t.horizon || '—')}}</div>
            ${{positioning ? `<div style="margin-top:10px"><span class="label-inline">Positioning</span><ul>${{positioning}}</ul></div>` : ''}}
          </div>`;
        el.querySelector('.thesis-summary').addEventListener('click', () => el.classList.toggle('open'));
        tl.appendChild(el);
      }});
    }}

    function renderSignalGroup(listId, countId, items){{
      document.getElementById(countId).textContent = items.length;
      const el = document.getElementById(listId);
      if (!items.length){{
        el.innerHTML = '<div class="empty-col">No signals in this group</div>';
        return;
      }}
      let html = '';
      items.slice(0, 6).forEach(s => {{
        const conv = Math.round((s.conviction || 0) * 100);
        let tactHtml = '';
        if (s.tactical && s.tactical.active_setups){{
          const parts = [];
          if (s.tactical.active_setups) parts.push(`<span class="pill-tact">${{s.tactical.active_setups}} SETUP${{s.tactical.active_setups > 1 ? 'S' : ''}}</span>`);
          if (s.tactical.at_entry) parts.push(`<span class="pill-tact">${{s.tactical.at_entry}} AT ENTRY</span>`);
          if (s.tactical.in_trade) parts.push(`<span class="pill-tact">${{s.tactical.in_trade}} IN TRADE</span>`);
          tactHtml = `<div class="signal-tact">${{parts.join('')}}</div>`;
        }} else {{
          tactHtml = `<div class="signal-tact"><span class="muted-tact">No tactical setups</span></div>`;
        }}
        html += `
          <div class="signal-card">
            <div class="signal-card-top">
              <div>
                <div class="signal-asset">${{escapeHtml(s.asset)}}</div>
                <div class="signal-meta">${{escapeHtml(s.theme || '—')}} · ${{escapeHtml(s.horizon || '')}}</div>
              </div>
              <div class="signal-conv">
                <div class="num">${{conv}}%</div>
                <div class="lbl">Conviction</div>
              </div>
            </div>
            <div class="signal-bar"><div style="width:${{conv}}%"></div></div>
            ${{s.rationale ? `<div class="signal-rat">${{escapeHtml(s.rationale)}}</div>` : ''}}
            ${{tactHtml}}
          </div>`;
      }});
      el.innerHTML = html;
    }}

    load();
    </script>
    """

    return render_shell(
        active="positioning",
        body=body,
        title="Macro Positioning · Positioning",
        ticker_tag="Live",
        ticker_label="Brain:",
        ticker_value="Gemini 2.5 Pro · FRED 50 series · 8 core sources",
    )
