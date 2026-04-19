"""Dev/Ops dashboard — builder-facing status UI, rebuilt on shared shell.

KPIs, data source health chips, build progress, interactive checklist,
brain activity log.
"""

from __future__ import annotations

from macro_positioning.dashboard.shell import ICONS, render_shell


DEV_CSS = r"""
.dev-kpi-row {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 20px;
}
@media (max-width: 900px) { .dev-kpi-row { grid-template-columns: repeat(2, 1fr); } }

.source-chips {
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-bottom: 22px;
}
.src-chip {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 6px 12px; border-radius: 7px;
  font-size: 11px; font-weight: 600;
  background: var(--surface); border: 1px solid var(--border);
  color: var(--text-dim);
}
.src-chip::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); }
.src-chip.ok { color: var(--green-2); border-color: rgba(16, 185, 129, 0.3); background: rgba(16, 185, 129, 0.05); }
.src-chip.ok::before { background: var(--green); box-shadow: var(--glow-green); }
.src-chip.warn { color: var(--yellow-2); border-color: rgba(245, 158, 11, 0.3); background: rgba(245, 158, 11, 0.05); }
.src-chip.warn::before { background: var(--yellow); }

.progress-shell { margin-bottom: 22px; }
.progress-bar {
  height: 8px; background: var(--bg-2); border: 1px solid var(--border);
  border-radius: 6px; overflow: hidden; margin-bottom: 8px;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--green) 0%, var(--green-2) 100%);
  transition: width 500ms ease;
}
.progress-meta {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 11px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600;
}
.progress-meta b { color: var(--text); font-family: var(--font-mono); }

.checklist { list-style: none; }
.checklist li {
  display: flex; gap: 12px; padding: 12px 4px;
  border-bottom: 1px solid var(--border);
  align-items: flex-start;
}
.checklist li:last-child { border-bottom: none; }
.check-icon {
  flex-shrink: 0; width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 800; cursor: pointer; user-select: none;
  transition: transform 150ms;
}
.check-icon:hover { transform: scale(1.12); }
.i-done { background: rgba(16, 185, 129, 0.14); color: var(--green-2); border: 1px solid rgba(16, 185, 129, 0.3); }
.i-wip { background: rgba(59, 130, 246, 0.14); color: var(--accent-2); border: 1px solid rgba(59, 130, 246, 0.3); }
.i-todo { background: transparent; border: 1px solid var(--border-hi); color: var(--text-muted); }
.check-text { flex: 1; min-width: 0; }
.check-title { font-weight: 600; font-size: 13px; }
.check-detail { font-size: 12px; color: var(--text-dim); margin-top: 3px; line-height: 1.45; }
.check-done .check-title, .check-done .check-detail { text-decoration: line-through; color: var(--text-muted); }
.pri {
  font-size: 9px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase;
  padding: 3px 8px; border-radius: 4px; flex-shrink: 0;
}
.pri-critical { background: rgba(239, 68, 68, 0.14); color: var(--red-2); }
.pri-high { background: rgba(245, 158, 11, 0.14); color: var(--yellow-2); }
.pri-medium { background: rgba(59, 130, 246, 0.12); color: var(--accent-2); }
.pri-low { background: rgba(148, 163, 184, 0.08); color: var(--text-muted); }

.brain-activity-list { display: flex; flex-direction: column; gap: 6px; }
.brain-row {
  display: grid; grid-template-columns: 120px 110px 1fr auto;
  align-items: center; gap: 12px;
  padding: 10px 14px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; font-size: 12px;
}
.brain-row .time { color: var(--text-muted); font-family: var(--font-mono); font-size: 11px; }
.brain-row .type {
  font-size: 10px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase;
  padding: 3px 9px; border-radius: 4px; width: fit-content;
}
.type.synthesis { background: rgba(139, 92, 246, 0.1); color: var(--purple-2); border: 1px solid rgba(139, 92, 246, 0.25); }
.type.vision { background: rgba(20, 184, 166, 0.1); color: var(--teal); border: 1px solid rgba(20, 184, 166, 0.25); }
.type.transcription { background: rgba(59, 130, 246, 0.1); color: var(--accent-2); border: 1px solid rgba(59, 130, 246, 0.25); }
.brain-row .meta { color: var(--text-dim); font-size: 11px; }
.brain-row .lat {
  font-family: var(--font-mono); font-size: 12px; font-weight: 700;
  text-align: right;
}
.brain-row .lat.ok { color: var(--green-2); }
.brain-row .lat.err { color: var(--red-2); }
"""


def dev_dashboard_html() -> str:
    body = f"""
    <style>{DEV_CSS}</style>

    <div id="loading" class="loading">Loading dev status…</div>

    <div id="content" style="display:none">

      <!-- KPIs -->
      <div class="dev-kpi-row">
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">Documents</div>
          <div id="k-docs" class="kpi-value">0</div>
          <div class="kpi-subvalue">Ingested</div>
        </div>
        <div class="kpi-card kpi-purple">
          <div class="kpi-label">Theses</div>
          <div id="k-theses" class="kpi-value">0</div>
          <div class="kpi-subvalue">Active</div>
        </div>
        <div class="kpi-card kpi-bull">
          <div class="kpi-label">Memos</div>
          <div id="k-memos" class="kpi-value">0</div>
          <div class="kpi-subvalue">Generated</div>
        </div>
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">FRED Series</div>
          <div id="k-fred" class="kpi-value">0</div>
          <div class="kpi-subvalue">Tracked</div>
        </div>
        <div class="kpi-card kpi-purple">
          <div class="kpi-label">Newsletters</div>
          <div id="k-news" class="kpi-value">0</div>
          <div class="kpi-subvalue">Configured</div>
        </div>
        <div class="kpi-card kpi-accent">
          <div class="kpi-label">Brain Calls</div>
          <div id="k-brain" class="kpi-value">0</div>
          <div class="kpi-subvalue">Total</div>
        </div>
      </div>

      <div class="source-chips" id="chips"></div>

      <!-- Build progress -->
      <div class="panel progress-shell">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['check']}</div>
            <span>Build Progress</span>
          </div>
          <div class="panel-subtitle" id="progress-label">—</div>
        </div>
        <div class="panel-body">
          <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
          <div class="progress-meta">
            <span>Completed tasks</span>
            <b id="progress-text">—</b>
          </div>
        </div>
      </div>

      <!-- Checklist -->
      <div class="panel" style="margin-bottom:22px">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['check']}</div>
            <span>Task Backlog</span>
          </div>
          <div class="panel-subtitle">Click ● to cycle: todo → in progress → done</div>
        </div>
        <div class="panel-body">
          <ul class="checklist" id="checklist"></ul>
        </div>
      </div>

      <!-- Brain activity -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon">{ICONS['brain']}</div>
            <span>Brain Activity</span>
          </div>
          <div class="panel-subtitle" id="brain-meta">—</div>
        </div>
        <div class="panel-body">
          <div class="brain-activity-list" id="brain-list"></div>
        </div>
      </div>

    </div>

    <script>
    function escapeHtml(s){{ if(s==null) return ''; return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}

    async function load(){{
      try {{
        const [ops, cl, brain] = await Promise.all([
          fetch('/api/dashboard/ops').then(r => r.json()),
          fetch('/api/checklist').then(r => r.json()),
          fetch('/api/dashboard/brain/activity?limit=15').then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        render(ops, cl, brain);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load: ' + e.message;
      }}
    }}

    function render(ops, cl, brain){{
      document.getElementById('loading').style.display = 'none';
      document.getElementById('content').style.display = 'block';

      // KPIs
      document.getElementById('k-docs').textContent = ops.db_stats?.documents || 0;
      document.getElementById('k-theses').textContent = ops.db_stats?.theses || 0;
      document.getElementById('k-memos').textContent = ops.db_stats?.memos || 0;
      document.getElementById('k-fred').textContent = (ops.data_sources || []).find(s => s.name.includes('FRED'))?.series_count || 0;
      document.getElementById('k-news').textContent = ops.newsletter_sources?.length || 0;
      document.getElementById('k-brain').textContent = brain?.stats?.total_calls || 0;

      // Source chips
      const chips = document.getElementById('chips');
      (ops.data_sources || []).forEach(s => {{
        const cls = s.connected ? 'ok' : (s.detail?.includes('catalogued') || s.detail?.includes('not built') ? '' : 'warn');
        chips.innerHTML += `<span class="src-chip ${{cls}}">${{escapeHtml(s.name.split('(')[0].trim())}}</span>`;
      }});

      // Progress
      const items = cl.items || [];
      const done = items.filter(i => i.status === 'done').length;
      const total = items.length;
      const pct = total ? Math.round(done / total * 100) : 0;
      document.getElementById('progress-fill').style.width = pct + '%';
      document.getElementById('progress-label').textContent = pct + '% complete';
      document.getElementById('progress-text').textContent = `${{done}} / ${{total}}`;

      // Checklist (sort: todo → in_progress → done, then by priority)
      const order = {{ todo: 0, in_progress: 1, done: 2 }};
      const pri = {{ critical: 0, high: 1, medium: 2, low: 3 }};
      items.sort((a, b) => {{
        if (order[a.status] !== order[b.status]) return order[a.status] - order[b.status];
        return (pri[a.priority] || 9) - (pri[b.priority] || 9);
      }});
      const cle = document.getElementById('checklist');
      items.forEach(t => {{
        const icon = t.status === 'done' ? '✓' : t.status === 'in_progress' ? '▶' : '';
        const iCls = t.status === 'done' ? 'i-done' : t.status === 'in_progress' ? 'i-wip' : 'i-todo';
        const doneCls = t.status === 'done' ? 'check-done' : '';
        const li = document.createElement('li');
        li.innerHTML = `
          <span class="check-icon ${{iCls}}" title="Click to toggle">${{icon}}</span>
          <span class="check-text ${{doneCls}}">
            <div class="check-title">${{escapeHtml(t.title)}}</div>
            ${{t.detail ? `<div class="check-detail">${{escapeHtml(t.detail)}}</div>` : ''}}
          </span>
          <span class="pri pri-${{t.priority}}">${{t.priority}}</span>`;
        li.querySelector('.check-icon').addEventListener('click', async () => {{
          try {{
            const r = await fetch('/api/checklist/' + encodeURIComponent(t.id), {{ method: 'PATCH' }});
            if (r.ok) location.reload();
          }} catch (e) {{}}
        }});
        cle.appendChild(li);
      }});

      // Brain activity
      const bl = document.getElementById('brain-list');
      const calls = brain?.recent || [];
      if (brain?.stats){{
        const s = brain.stats;
        document.getElementById('brain-meta').textContent =
          `${{s.synthesis_calls}} synthesis · ${{s.vision_calls}} vision · ${{s.avg_latency_ms.toFixed(0)}}ms avg · ${{(s.error_rate*100).toFixed(0)}}% err`;
      }}
      if (!calls.length){{
        bl.innerHTML = '<div class="empty-pad" style="padding:20px;text-align:center;color:var(--text-muted)">No brain activity yet. Run a pipeline.</div>';
      }} else {{
        calls.forEach(c => {{
          const t = new Date(c.timestamp);
          const tstr = t.toLocaleString(undefined, {{ month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }});
          const latCls = c.success ? 'ok' : 'err';
          bl.innerHTML += `
            <div class="brain-row">
              <span class="time">${{tstr}}</span>
              <span class="type ${{c.call_type}}">${{c.call_type}}</span>
              <span class="meta">${{escapeHtml(c.model || c.backend)}}${{c.theses_count ? ' · ' + c.theses_count + ' theses' : ''}}${{!c.success ? ' · <span style="color:var(--red-2)">' + escapeHtml(c.error || 'err') + '</span>' : ''}}</span>
              <span class="lat ${{latCls}}">${{c.latency_ms.toFixed(0)}}ms</span>
            </div>`;
        }});
      }}
    }}
    load();
    </script>
    """

    return render_shell(
        active="dev",
        body=body,
        title="Macro Positioning · Dev",
        ticker_tag="Ops",
        ticker_label="Build status:",
        ticker_value="Foundation shipped · P1-A + P1-B complete · 123 tests green",
    )
