"""Tactical-executor standalone inspection view, rebuilt on shared shell.

READ-ONLY pull of tactical state. Sector-card style grid for active setups,
current agent_packet decision with macro gate applied, recent events table.
"""

from __future__ import annotations

from macro_positioning.dashboard.shell import ICONS, render_shell


TACTICAL_CSS = r"""
.status-banner {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 20px; border-radius: 10px;
  margin-bottom: 18px;
  border: 1px solid var(--border);
  background: var(--surface);
  font-size: 13px; color: var(--text-dim);
}
.status-banner.ok { border-color: rgba(16, 185, 129, 0.3); background: rgba(16, 185, 129, 0.04); color: var(--green-2); }
.status-banner.warn { border-color: rgba(245, 158, 11, 0.3); background: rgba(245, 158, 11, 0.04); color: var(--yellow-2); }
.status-banner.err { border-color: rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.04); color: var(--red-2); }

.decision-grid {
  display: grid; grid-template-columns: 1.3fr 1fr;
  gap: 18px; margin-bottom: 22px;
}
@media (max-width: 900px) { .decision-grid { grid-template-columns: 1fr; } }

.big-action {
  font-size: 44px; font-weight: 800; letter-spacing: -1.5px;
  line-height: 1; margin-bottom: 10px;
}
.big-action.LONG { color: var(--green-2); }
.big-action.SHORT { color: var(--red-2); }
.big-action.WAIT { color: var(--text-dim); }

.dec-meta { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 18px; font-size: 12px; color: var(--text-dim); }
.dec-meta b { color: var(--text); font-weight: 600; }
.dec-stats-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
  margin-bottom: 14px;
}
.dec-reasons {
  font-size: 11px; color: var(--text-dim);
  display: flex; flex-wrap: wrap; gap: 6px;
}
.reason-pill {
  font-family: var(--font-mono); font-size: 10px;
  padding: 3px 8px; background: var(--bg-2); border: 1px solid var(--border);
  border-radius: 4px; color: var(--text-dim);
}

.macro-gate-block {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.08), rgba(139, 92, 246, 0.06));
  border: 1px solid rgba(59, 130, 246, 0.25);
  border-radius: 10px; padding: 16px 18px;
}
.macro-gate-block .head {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
}
.macro-gate-block .head .lbl {
  font-size: 10px; letter-spacing: 1.3px; font-weight: 800; text-transform: uppercase;
  color: var(--accent-2);
}
.macro-gate-dir {
  font-size: 22px; font-weight: 800; letter-spacing: -0.4px; text-transform: uppercase;
  margin-bottom: 8px;
}
.macro-gate-notes {
  font-size: 12px; color: var(--text-dim); line-height: 1.5;
}
.gate-stats {
  display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap;
}

/* Sector-card style setup grid (for active setups + recent events) */
.setup-grid {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}
.setup-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
  position: relative; overflow: hidden;
}
.setup-card.trigger { border-top: 2px solid var(--accent); }
.setup-card.in_trade { border-top: 2px solid var(--green); }
.setup-card.tp_zone { border-top: 2px solid var(--purple); }
.setup-card.watch { border-top: 2px solid var(--text-muted); }
.setup-card.invalidated { border-top: 2px solid var(--red); opacity: 0.75; }
.setup-card.closed { border-top: 2px solid var(--text-mute-2); opacity: 0.6; }
.setup-card-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 10px;
}
.setup-symbol {
  font-family: var(--font-mono); font-size: 18px; font-weight: 800;
  letter-spacing: 0.5px; text-transform: uppercase;
}
.setup-id-chip {
  font-family: var(--font-mono); font-size: 10px;
  padding: 3px 8px; background: var(--bg-2); border: 1px solid var(--border);
  border-radius: 4px; color: var(--text-muted);
}
.setup-stats-row {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
  margin: 10px 0;
}
.setup-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding-top: 10px; border-top: 1px solid var(--border);
  font-size: 10px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;
}

.events-table { overflow-x: auto; }
.empty-pad { padding: 26px; text-align: center; color: var(--text-muted); font-size: 13px; }
"""


def tactical_dashboard_html() -> str:
    body = f"""
    <style>{TACTICAL_CSS}</style>

    <div id="loading" class="loading">Loading tactical state…</div>

    <div id="content" style="display:none">

      <div id="status-banner"></div>

      <!-- KPI row -->
      <div class="kpi-row" style="display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:22px">
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">Active Setups</div>
          <div id="kpi-setups" class="kpi-value">0</div>
          <div class="kpi-subvalue">Unique</div>
        </div>
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">At Trigger</div>
          <div id="kpi-trigger" class="kpi-value">0</div>
          <div class="kpi-subvalue">Waiting entry</div>
        </div>
        <div class="kpi-card kpi-bull">
          <div class="kpi-label">In Trade</div>
          <div id="kpi-in-trade" class="kpi-value">0</div>
          <div class="kpi-subvalue">Live positions</div>
        </div>
        <div class="kpi-card kpi-bear">
          <div class="kpi-label">Closed/Invalid</div>
          <div id="kpi-closed" class="kpi-value">0</div>
          <div class="kpi-subvalue">Recent</div>
        </div>
        <div class="kpi-card kpi-purple">
          <div class="kpi-label">Recent Events</div>
          <div id="kpi-events" class="kpi-value">0</div>
          <div class="kpi-subvalue">Last 25</div>
        </div>
      </div>

      <!-- Latest decision + macro gate -->
      <div class="decision-grid" id="decision-grid" style="display:none">
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              <div class="panel-icon">{ICONS['tactical']}</div>
              <span>Latest Decision</span>
            </div>
            <div class="panel-subtitle" id="dec-subtitle">—</div>
          </div>
          <div class="panel-body">
            <div id="big-action" class="big-action">WAIT</div>
            <div class="dec-meta" id="dec-meta"></div>
            <div class="dec-stats-row" id="dec-stats"></div>
            <div class="dec-reasons" id="dec-reasons"></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              <div class="panel-icon">{ICONS['macro']}</div>
              <span>Macro Gate</span>
            </div>
            <div class="panel-subtitle">Applied to decision</div>
          </div>
          <div class="panel-body" id="macro-gate-body">
            <div class="empty-pad">No macro view attached</div>
          </div>
        </div>
      </div>

      <!-- Active setups -->
      <div class="panel" style="margin-bottom:22px">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['pulse']}</div>
            <span>Active Setups</span>
          </div>
          <div class="panel-subtitle" id="setups-count">—</div>
        </div>
        <div class="panel-body">
          <div id="setups-grid" class="setup-grid"></div>
          <div id="setups-empty" class="empty-pad" style="display:none">
            No active setups. Waiting for TradingView webhooks.
          </div>
        </div>
      </div>

      <!-- Recent events -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['activity']}</div>
            <span>Recent Events</span>
          </div>
          <div class="panel-subtitle" id="events-count">—</div>
        </div>
        <div class="events-table">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width:120px">Time</th>
                <th style="width:100px">Symbol</th>
                <th style="width:120px">Stage</th>
                <th>Pattern</th>
                <th style="width:90px">Bias</th>
                <th style="width:100px; text-align:right">Confluence</th>
              </tr>
            </thead>
            <tbody id="events-tbody"></tbody>
          </table>
          <div id="events-empty" class="empty-pad" style="display:none">
            No events yet.
          </div>
        </div>
      </div>

    </div>

    <script>
    function escapeHtml(s){{ if(s==null) return ''; return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}

    async function load(){{
      try {{
        const r = await fetch('/api/dashboard/tactical-state');
        const data = await r.json();
        render(data);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load: ' + e.message;
      }}
    }}

    function render(state){{
      document.getElementById('loading').style.display = 'none';
      document.getElementById('content').style.display = 'block';

      const banner = document.getElementById('status-banner');
      if (!state.configured){{
        banner.className = 'status-banner warn';
        banner.innerHTML = '<b>Tactical URL not configured.</b> Set <code>MPA_TACTICAL_EXECUTOR_URL</code> in .env to pull live state.';
        return;
      }}
      if (!state.health || (state.events === null && state.latest_decision === null)){{
        banner.className = 'status-banner err';
        banner.textContent = 'Tactical executor unreachable. Check the URL and service health.';
      }} else {{
        banner.className = 'status-banner ok';
        banner.textContent = '● Connected to tactical-executor';
      }}

      const events = state.events || [];
      const decision = state.latest_decision || {{}};

      // KPIs
      const uniq = new Set();
      let trig = 0, inT = 0, closed = 0;
      events.forEach(e => {{
        const p = e.payload || {{}};
        if (p.setup_id) uniq.add(p.setup_id);
        const stage = (p.setup_stage || '').toLowerCase();
        if (stage === 'trigger') trig++;
        else if (stage === 'in_trade') inT++;
        else if (stage === 'closed' || stage === 'invalidated') closed++;
      }});
      document.getElementById('kpi-setups').textContent = uniq.size;
      document.getElementById('kpi-trigger').textContent = trig;
      document.getElementById('kpi-in-trade').textContent = inT;
      document.getElementById('kpi-closed').textContent = closed;
      document.getElementById('kpi-events').textContent = events.length;

      // Decision
      if (decision && decision.decision){{
        document.getElementById('decision-grid').style.display = 'grid';
        const d = decision.decision;
        const ap = decision.agent_packet || {{}};
        const action = (d.action || 'WAIT').toUpperCase();
        const big = document.getElementById('big-action');
        big.textContent = action; big.className = 'big-action ' + action;

        document.getElementById('dec-subtitle').textContent = escapeHtml(ap.symbol || '') + ' · ' + escapeHtml(ap.setup_id || '');

        document.getElementById('dec-meta').innerHTML = [
          `<span><b>Confidence:</b> ${{escapeHtml(d.confidence || '')}}</span>`,
          `<span><b>Risk tier:</b> ${{escapeHtml(d.risk_tier || '')}}</span>`,
          `<span><b>Stage:</b> ${{escapeHtml(ap.stage || '')}}</span>`,
          `<span><b>Timeframe:</b> ${{escapeHtml(ap.timeframe || '')}}</span>`,
        ].join('');

        document.getElementById('dec-stats').innerHTML = [
          `<div class="stat-box"><div class="label">Direction Score</div><div class="value">${{d.direction_score ?? 0}}</div></div>`,
          `<div class="stat-box"><div class="label">Score</div><div class="value">${{ap.score ?? '—'}}</div></div>`,
          `<div class="stat-box"><div class="label">Confluence</div><div class="value">${{ap.confluence || '—'}}</div></div>`,
          `<div class="stat-box"><div class="label">Bias</div><div class="value">${{ap.bias || '—'}}</div></div>`,
        ].join('');

        document.getElementById('dec-reasons').innerHTML =
          (d.reason_codes || []).map(r => `<span class="reason-pill">${{escapeHtml(r)}}</span>`).join('');

        // Macro gate
        const mv = decision.macro_view;
        const gateBody = document.getElementById('macro-gate-body');
        if (mv && mv.direction){{
          const dir = mv.direction.toLowerCase();
          const gate = mv.gate_suggestion || {{}};
          gateBody.innerHTML = `
            <div class="macro-gate-block">
              <div class="head">
                <span class="regime-indicator ${{dir}}"></span>
                <span class="lbl">Macro View</span>
              </div>
              <div class="macro-gate-dir" style="color: var(--${{dir === 'bullish' ? 'green-2' : dir === 'bearish' ? 'red-2' : 'text-dim'}})">${{dir}}</div>
              <div class="macro-gate-notes">${{escapeHtml(gate.notes || '')}}</div>
              <div class="gate-stats">
                <div class="stat-box"><div class="label">Conf</div><div class="value">${{((mv.confidence || 0) * 100).toFixed(0)}}%</div></div>
                <div class="stat-box"><div class="label">Size mul</div><div class="value">${{(gate.size_multiplier || 1).toFixed(2)}}x</div></div>
                <div class="stat-box"><div class="label">Long</div><div class="value">${{gate.allow_long ? '✓' : '✗'}}</div></div>
                <div class="stat-box"><div class="label">Short</div><div class="value">${{gate.allow_short ? '✓' : '✗'}}</div></div>
              </div>
            </div>`;
        }}
      }}

      // Active setups (unique by setup_id, keep most recent event's state)
      const seen = new Map();
      for (const e of events){{
        const p = e.payload || {{}};
        if (!p.setup_id) continue;
        if (!seen.has(p.setup_id)) seen.set(p.setup_id, {{ payload: p, received_at: e.received_at }});
      }}
      const grid = document.getElementById('setups-grid');
      const setupsCount = document.getElementById('setups-count');
      const setups = Array.from(seen.values());
      setupsCount.textContent = setups.length + ' tracked';
      if (!setups.length){{
        document.getElementById('setups-empty').style.display = 'block';
      }} else {{
        setups.slice(0, 12).forEach(({{ payload: p, received_at }}) => {{
          const stage = (p.setup_stage || 'watch').toLowerCase();
          grid.innerHTML += `
            <div class="setup-card ${{stage}}">
              <div class="setup-card-head">
                <div>
                  <div class="setup-symbol">${{escapeHtml(p.symbol || '—')}}</div>
                  <div class="regime-indicator ${{stage === 'trigger' || stage === 'in_trade' ? 'bullish' : stage === 'invalidated' ? 'bearish' : 'neutral'}}" style="margin-top:4px">${{stage.replace('_', ' ')}}</div>
                </div>
                <span class="setup-id-chip">${{escapeHtml((p.setup_id || '').slice(0, 12))}}</span>
              </div>
              <div class="setup-stats-row">
                <div class="stat-box"><div class="label">Bias</div><div class="value">${{escapeHtml(p.bias || '—')}}</div></div>
                <div class="stat-box"><div class="label">Conf</div><div class="value">${{escapeHtml(p.confluence || '—')}}</div></div>
                <div class="stat-box"><div class="label">Score</div><div class="value">${{p.score ?? '—'}}</div></div>
              </div>
              <div class="setup-footer">
                <span>${{escapeHtml(p.pattern_type || '—')}}</span>
                <span>${{escapeHtml(p.timeframe || '')}}</span>
              </div>
            </div>`;
        }});
      }}

      // Events table
      const tbody = document.getElementById('events-tbody');
      document.getElementById('events-count').textContent = events.length + ' recent';
      if (!events.length){{
        document.getElementById('events-empty').style.display = 'block';
      }} else {{
        events.slice(0, 25).forEach(e => {{
          const p = e.payload || {{}};
          const t = new Date(e.received_at || '');
          const tstr = isNaN(t.getTime()) ? '' : t.toLocaleString(undefined, {{ month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }});
          const stage = (p.setup_stage || 'watch').toLowerCase();
          const conf = (p.confluence || 'LOW').toUpperCase();
          tbody.innerHTML += `
            <tr>
              <td class="muted mono" style="font-size:11px">${{tstr}}</td>
              <td><b>${{escapeHtml(p.symbol || '')}}</b></td>
              <td><span class="regime-indicator ${{stage === 'trigger' || stage === 'in_trade' ? 'bullish' : stage === 'invalidated' ? 'bearish' : 'neutral'}}">${{stage.replace('_', ' ')}}</span></td>
              <td>${{escapeHtml(p.pattern_type || '—')}}</td>
              <td>${{escapeHtml(p.bias || '—')}}</td>
              <td class="num"><span class="pill ${{conf === 'HIGH' ? 'bullish' : conf === 'LOW' ? 'neutral' : 'mixed'}}">${{conf}}</span></td>
            </tr>`;
        }});
      }}
    }}
    load();
    </script>
    """

    return render_shell(
        active="tactical",
        body=body,
        title="Macro Positioning · Tactical",
        ticker_tag="Read-only",
        ticker_label="Tactical state:",
        ticker_value="Live stream from trading-agent-v1-codex (contract v1.0.0)",
    )
