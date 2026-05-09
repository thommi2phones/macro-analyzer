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

/* ─── Mgmt panel ─── */
.mgmt-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
  margin-bottom: 22px;
}
@media (max-width: 1100px) { .mgmt-grid { grid-template-columns: 1fr; } }

.mgmt-summary {
  display: flex; flex-direction: column; gap: 6px;
}
.mgmt-summary-row {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 12px; padding: 6px 0;
  border-bottom: 1px dashed var(--border);
}
.mgmt-summary-row:last-child { border-bottom: none; }
.mgmt-summary-row .label {
  color: var(--text-muted); text-transform: uppercase;
  letter-spacing: 0.5px; font-size: 10px; font-weight: 700;
}
.mgmt-summary-row .value {
  font-family: var(--font-mono); font-weight: 700; color: var(--text);
}
.mgmt-inprogress-list {
  margin-top: 10px; padding-top: 10px;
  border-top: 1px solid var(--border);
}
.mgmt-inprogress-list .ip-label {
  font-size: 10px; color: var(--accent-2); text-transform: uppercase;
  letter-spacing: 0.6px; font-weight: 700; margin-bottom: 6px;
}
.mgmt-inprogress-list .ip-item {
  font-size: 12px; color: var(--text-dim); padding: 3px 0;
  display: flex; gap: 8px; align-items: baseline;
}
.mgmt-inprogress-list .ip-item::before {
  content: '▶'; color: var(--accent-2); font-size: 9px;
}

.decisions-list { display: flex; flex-direction: column; gap: 8px; }
.decision-row {
  padding: 10px 12px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 7px;
  font-size: 12px; line-height: 1.45;
}
.decision-row .topic {
  font-weight: 700; font-size: 12px; color: var(--text);
  margin-bottom: 4px;
}
.decision-row .body { color: var(--text-dim); }
.decision-row .meta {
  font-size: 10px; color: var(--text-muted);
  font-family: var(--font-mono); margin-top: 6px;
  text-transform: uppercase; letter-spacing: 0.4px;
}
.decision-row .meta .dec-id { color: var(--purple-2); margin-right: 8px; }
.decision-row.expand .body {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.decision-row.expand:hover .body {
  -webkit-line-clamp: unset; overflow: visible;
}
.decision-row .rationale {
  font-size: 11px; color: var(--text-muted);
  margin-top: 6px; font-style: italic;
  display: none;
}
.decision-row:hover .rationale { display: block; }

.commits-list { display: flex; flex-direction: column; gap: 4px; }
.commit-row {
  display: grid; grid-template-columns: 80px 1fr auto;
  align-items: baseline; gap: 12px;
  padding: 8px 12px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px;
  font-size: 12px;
}
.commit-row .sha {
  font-family: var(--font-mono); font-weight: 700;
  color: var(--accent-2); font-size: 11px;
}
.commit-row .subject {
  color: var(--text); overflow: hidden;
  white-space: nowrap; text-overflow: ellipsis;
}
.commit-row .when {
  color: var(--text-muted); font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.4px;
  font-family: var(--font-mono);
}
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

      <!-- ─── Project Management panel ─── -->
      <div class="mgmt-grid">

        <!-- Left: Decisions log -->
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              <div class="panel-icon">{ICONS.get('check', '◆')}</div>
              <span>Recent Decisions</span>
            </div>
            <div class="panel-subtitle" id="mgmt-dec-meta">—</div>
          </div>
          <div class="panel-body">
            <div class="decisions-list" id="mgmt-decisions"></div>
          </div>
        </div>

        <!-- Right: Recent commits + checklist summary -->
        <div style="display:flex;flex-direction:column;gap:14px">
          <div class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <div class="panel-icon">{ICONS.get('check', '◆')}</div>
                <span>Recent Commits</span>
              </div>
              <div class="panel-subtitle">Last 10 from <code>git log</code></div>
            </div>
            <div class="panel-body">
              <div class="commits-list" id="mgmt-commits"></div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <div class="panel-icon">{ICONS.get('check', '◆')}</div>
                <span>Checklist Summary</span>
              </div>
              <div class="panel-subtitle">Live from <code>data/checklist.json</code></div>
            </div>
            <div class="panel-body">
              <div class="mgmt-summary" id="mgmt-summary"></div>
            </div>
          </div>
        </div>

      </div>

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
        const [ops, cl, brain, mgmt] = await Promise.all([
          fetch('/api/dashboard/ops').then(r => r.json()),
          fetch('/api/checklist').then(r => r.json()),
          fetch('/api/dashboard/brain/activity?limit=15').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch('/api/dashboard/mgmt').then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        render(ops, cl, brain, mgmt);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load: ' + e.message;
      }}
    }}

    function renderMgmt(mgmt){{
      if (!mgmt) return;

      // Decisions
      const dl = document.getElementById('mgmt-decisions');
      const decs = mgmt.recent_decisions || [];
      document.getElementById('mgmt-dec-meta').textContent =
        `${{decs.length}} of ${{mgmt.decisions_total}} shown · hover for rationale`;
      if (!decs.length){{
        dl.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-muted);font-size:12px">No decisions logged yet.</div>';
      }} else {{
        decs.forEach(d => {{
          const dateStr = (d.decided_at || '').split('T')[0];
          const div = document.createElement('div');
          div.className = 'decision-row';
          div.innerHTML = `
            <div class="topic">${{escapeHtml(d.topic)}}</div>
            <div class="body">${{escapeHtml(d.decision)}}</div>
            ${{d.rationale ? `<div class="rationale">↳ ${{escapeHtml(d.rationale)}}</div>` : ''}}
            <div class="meta"><span class="dec-id">${{escapeHtml(d.decision_id)}}</span>${{escapeHtml(dateStr)}}${{d.chat_session_ref ? ' · ' + escapeHtml(d.chat_session_ref) : ''}}</div>`;
          dl.appendChild(div);
        }});
      }}

      // Commits
      const cm = document.getElementById('mgmt-commits');
      const commits = mgmt.recent_commits || [];
      if (!commits.length){{
        cm.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-muted);font-size:12px">No commits found (or git unavailable).</div>';
      }} else {{
        commits.forEach(c => {{
          const div = document.createElement('div');
          div.className = 'commit-row';
          div.title = c.author + ' · ' + c.sha;
          div.innerHTML = `
            <span class="sha">${{escapeHtml(c.short_sha)}}</span>
            <span class="subject">${{escapeHtml(c.subject)}}</span>
            <span class="when">${{escapeHtml(c.relative_date)}}</span>`;
          cm.appendChild(div);
        }});
      }}

      // Checklist summary
      const sm = document.getElementById('mgmt-summary');
      const s = mgmt.checklist_summary || {{}};
      sm.innerHTML = `
        <div class="mgmt-summary-row">
          <span class="label">Done</span>
          <span class="value">${{s.done || 0}} / ${{s.total || 0}} (${{s.pct_complete || 0}}%)</span>
        </div>
        <div class="mgmt-summary-row">
          <span class="label">In progress</span>
          <span class="value">${{s.in_progress || 0}}</span>
        </div>
        <div class="mgmt-summary-row">
          <span class="label">Todo</span>
          <span class="value">${{s.todo || 0}}</span>
        </div>`;
      const ips = s.in_progress_titles || [];
      if (ips.length){{
        let html = '<div class="mgmt-inprogress-list"><div class="ip-label">Active</div>';
        ips.forEach(t => {{ html += `<div class="ip-item">${{escapeHtml(t)}}</div>`; }});
        html += '</div>';
        sm.innerHTML += html;
      }}
    }}

    function render(ops, cl, brain, mgmt){{
      document.getElementById('loading').style.display = 'none';
      document.getElementById('content').style.display = 'block';

      // Mgmt panel (decisions + commits + checklist summary)
      renderMgmt(mgmt);

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
