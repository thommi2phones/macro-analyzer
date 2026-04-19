"""Self-contained HTML templates for dashboards.

Single unified dashboard: dev checklist on top, directional command center below.
"""

from __future__ import annotations


def ops_dashboard_html() -> str:
    return _UNIFIED_HTML


def command_center_html() -> str:
    return _UNIFIED_HTML


# ═══════════════════════════════════════════════════════════════════════════
# Unified Dashboard — Dev Checklist + Command Center
# ═══════════════════════════════════════════════════════════════════════════

_UNIFIED_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Positioning Analyzer</title>
<style>
:root {
  --bg: #0b0e13; --surface: #141820; --surface2: #1a1f2b;
  --border: #252b37; --border-light: #2f3746;
  --text: #e2e8f0; --text-dim: #7a8599; --text-muted: #4a5568;
  --accent: #60a5fa; --green: #34d399; --yellow: #fbbf24;
  --red: #f87171; --purple: #a78bfa; --orange: #fb923c; --teal: #2dd4bf;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }

/* Header */
.header { margin-bottom: 36px; }
.header h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }
.header p { font-size: 13px; color: var(--text-dim); margin-top: 4px; }

/* Tab nav */
.tabs { display: flex; gap: 2px; margin-bottom: 32px; background: var(--surface);
  border-radius: 8px; padding: 3px; width: fit-content; }
.tab { font-size: 13px; font-weight: 500; padding: 7px 18px; border-radius: 6px;
  cursor: pointer; color: var(--text-dim); transition: all .15s; border: none; background: none; }
.tab:hover { color: var(--text); }
.tab.active { background: var(--surface2); color: var(--text); }

/* Sections */
.panel { display: none; }
.panel.active { display: block; }
.section { margin-bottom: 28px; }
.section-head { font-size: 14px; font-weight: 600; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 14px; }

/* Cards */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px; }

/* ─── DEV CHECKLIST ─── */
.checklist { list-style: none; }
.checklist li { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0;
  border-bottom: 1px solid var(--border); font-size: 14px; }
.checklist li:last-child { border-bottom: none; }
.check-icon { flex-shrink: 0; width: 20px; height: 20px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 11px;
  margin-top: 1px; }
.check-done { background: rgba(52,211,153,.15); color: var(--green); }
.check-wip { background: rgba(96,165,250,.15); color: var(--accent); }
.check-todo { background: rgba(122,133,153,.1); color: var(--text-muted); border: 1px solid var(--border); }
.check-text { flex: 1; }
.check-text .title { font-weight: 500; }
.check-text .detail { font-size: 12px; color: var(--text-dim); margin-top: 2px; }
.done-text .title { text-decoration: line-through; color: var(--text-dim); }
.done-text .detail { text-decoration: line-through; }
.pri { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px;
  text-transform: uppercase; letter-spacing: .3px; flex-shrink: 0; }
.pri-critical { background: rgba(248,113,113,.12); color: var(--red); }
.pri-high { background: rgba(251,191,36,.1); color: var(--yellow); }
.pri-medium { background: rgba(96,165,250,.1); color: var(--accent); }
.pri-low { background: rgba(122,133,153,.08); color: var(--text-muted); }
.progress-bar { width: 100%; height: 6px; background: var(--border); border-radius: 3px;
  overflow: hidden; margin-bottom: 10px; }
.progress-fill { height: 100%; border-radius: 3px; background: var(--green); transition: width .5s ease; }
.progress-label { font-size: 12px; color: var(--text-dim); margin-bottom: 16px; }

/* Status chips */
.status-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }
.status-chip { font-size: 12px; padding: 4px 12px; border-radius: 6px; font-weight: 500; }
.chip-ok { background: rgba(52,211,153,.1); color: var(--green); border: 1px solid rgba(52,211,153,.2); }
.chip-warn { background: rgba(251,191,36,.08); color: var(--yellow); border: 1px solid rgba(251,191,36,.2); }
.chip-off { background: rgba(122,133,153,.06); color: var(--text-muted); border: 1px solid var(--border); }

/* ─── COMMAND CENTER ─── */
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 28px; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px 16px; }
.kpi-val { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }
.kpi-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase;
  letter-spacing: .4px; margin-top: 2px; }

.memo-box { font-size: 14px; line-height: 1.7; padding: 16px 18px;
  background: rgba(96,165,250,.04); border-left: 3px solid var(--accent);
  border-radius: 0 8px 8px 0; margin-bottom: 24px; color: var(--text); }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
@media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }

.list-item { padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.list-item:last-child { border-bottom: none; }
.empty-msg { font-size: 13px; color: var(--text-muted); font-style: italic; }

/* Theme bars */
.theme-row { display: flex; align-items: center; gap: 12px; padding: 10px 0;
  border-bottom: 1px solid var(--border); }
.theme-row:last-child { border-bottom: none; }
.theme-label { font-size: 13px; font-weight: 600; min-width: 110px; }
.theme-bar { display: flex; height: 20px; border-radius: 4px; overflow: hidden; flex: 1; }
.theme-bar div { display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 600; min-width: 20px; }
.theme-conf { font-size: 11px; color: var(--text-dim); min-width: 50px; text-align: right; }
.asset-tag { display: inline-block; font-size: 10px; background: rgba(96,165,250,.08);
  border: 1px solid rgba(96,165,250,.15); padding: 1px 7px; border-radius: 8px;
  margin: 1px; color: var(--accent); }
.risk-tag { display: inline-block; font-size: 12px; background: rgba(248,113,113,.06);
  border: 1px solid rgba(248,113,113,.18); padding: 3px 10px; border-radius: 6px;
  margin: 3px; color: var(--red); }

/* Thesis table */
.thesis-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.thesis-table th { text-align: left; color: var(--text-muted); font-weight: 500;
  padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 11px;
  text-transform: uppercase; letter-spacing: .4px; }
.thesis-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
.dir-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
  text-transform: uppercase; }
.dir-bullish { background: rgba(52,211,153,.12); color: var(--green); }
.dir-bearish { background: rgba(248,113,113,.12); color: var(--red); }
.dir-neutral { background: rgba(122,133,153,.1); color: var(--text-dim); }
.dir-mixed { background: rgba(251,191,36,.1); color: var(--yellow); }
.dir-watchful { background: rgba(167,139,250,.1); color: var(--purple); }

.expert-row { font-size: 12px; font-family: 'SF Mono', 'Fira Code', monospace; padding: 6px 0;
  border-bottom: 1px solid var(--border); }
.expert-row:last-child { border-bottom: none; }
.expert-disagree { background: rgba(248,113,113,.06); padding: 4px 8px; border-radius: 4px; }

.no-data { text-align: center; padding: 48px; }
.no-data h3 { font-size: 18px; margin-bottom: 8px; }
.no-data p { color: var(--text-dim); font-size: 14px; }

#loading { text-align: center; padding: 60px; color: var(--text-dim); font-size: 14px; }
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>Macro Positioning Analyzer</h1>
  <p>Development status & directional command center</p>
</div>

<div class="tabs">
  <button class="tab active" onclick="showPanel('dev')">Dev Checklist</button>
  <button class="tab" onclick="showPanel('cmd')">Command Center</button>
</div>

<div id="loading">Loading...</div>

<!-- ═══ DEV CHECKLIST ═══ -->
<div id="panel-dev" class="panel">
  <div class="section">
    <div class="section-head">System Status</div>
    <div class="status-row" id="status-chips"></div>
    <div class="progress-bar"><div class="progress-fill" id="dev-progress"></div></div>
    <div class="progress-label" id="dev-progress-label"></div>
  </div>
  <div class="section">
    <div class="section-head">Build Checklist</div>
    <div class="card">
      <ul class="checklist" id="checklist"></ul>
    </div>
  </div>
</div>

<!-- ═══ COMMAND CENTER ═══ -->
<div id="panel-cmd" class="panel">
  <div id="cmd-no-data" class="no-data" style="display:none">
    <h3>No positioning data yet</h3>
    <p>Run the pipeline to generate theses and a positioning memo.</p>
  </div>
  <div id="cmd-content" style="display:none">
    <div class="kpi-strip" id="kpi-strip"></div>
    <div class="memo-box" id="memo-box" style="display:none"></div>

    <div class="section">
      <div class="section-head">Theme Direction Map</div>
      <div class="card" id="theme-map"></div>
    </div>

    <div class="two-col">
      <div class="card">
        <div class="section-head" style="margin-bottom:10px">Consensus</div>
        <div id="consensus-list"></div>
      </div>
      <div class="card">
        <div class="section-head" style="margin-bottom:10px">Divergence</div>
        <div id="divergence-list"></div>
      </div>
    </div>

    <div class="section">
      <div class="section-head">Top Trade Expressions</div>
      <div class="card" id="trades-list"></div>
    </div>

    <div id="expert-section" class="section" style="display:none">
      <div class="section-head">Expert vs Market</div>
      <div class="card" id="expert-list"></div>
    </div>

    <div class="section">
      <div class="section-head">Risks to Watch</div>
      <div class="card" id="risks-card"></div>
    </div>

    <div class="section">
      <div class="section-head">Active Theses</div>
      <div class="card" style="overflow-x:auto">
        <table class="thesis-table">
          <thead><tr><th>Theme</th><th>Dir</th><th>Thesis</th><th>Assets</th><th>Conf</th><th>Horizon</th></tr></thead>
          <tbody id="thesis-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

</div>

<script>
function showPanel(id) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  event.target.classList.add('active');
}

async function load() {
  const [opsResp, cmdResp, clResp] = await Promise.all([
    fetch('/api/dashboard/ops'), fetch('/api/dashboard/command-center'), fetch('/api/checklist')
  ]);
  const ops = await opsResp.json();
  const cmd = await cmdResp.json();
  const cl = await clResp.json();
  document.getElementById('loading').style.display = 'none';
  renderDev(ops, cl);
  renderCmd(cmd);
  document.getElementById('panel-dev').classList.add('active');
}

function renderDev(d, cl) {
  // Status chips from data sources
  const chips = document.getElementById('status-chips');
  const sources = d.data_sources || [];
  sources.forEach(s => {
    const cls = s.connected ? 'chip-ok' : (s.detail.includes('catalogued') ? 'chip-off' : 'chip-warn');
    chips.innerHTML += '<span class="status-chip ' + cls + '">' + s.name.split('(')[0].trim() + '</span>';
  });

  // Use persistent checklist
  const items = cl.items || [];
  const done = items.filter(t => t.status === 'done').length;
  const total = items.length;
  const pct = total ? Math.round(done / total * 100) : 0;
  document.getElementById('dev-progress').style.width = pct + '%';
  document.getElementById('dev-progress-label').textContent = done + ' / ' + total + ' tasks complete (' + pct + '%)';

  // Sort: todo first, then in_progress, then done
  const order = { todo: 0, in_progress: 1, done: 2 };
  const pri = { critical: 0, high: 1, medium: 2, low: 3 };
  items.sort((a, b) => {
    if (order[a.status] !== order[b.status]) return order[a.status] - order[b.status];
    return (pri[a.priority] || 3) - (pri[b.priority] || 3);
  });

  const list = document.getElementById('checklist');
  items.forEach(t => {
    let icon = '', iconCls = '';
    if (t.status === 'done') { icon = '&#10003;'; iconCls = 'check-done'; }
    else if (t.status === 'in_progress') { icon = '&#9654;'; iconCls = 'check-wip'; }
    else { icon = ''; iconCls = 'check-todo'; }

    const li = document.createElement('li');
    li.setAttribute('data-id', t.id);
    li.innerHTML =
      '<span class="check-icon ' + iconCls + '" style="cursor:pointer" title="Click to toggle">' + icon + '</span>' +
      '<span class="check-text' + (t.status === 'done' ? ' done-text' : '') + '"><span class="title">' + t.title + '</span>' +
      (t.detail ? '<div class="detail">' + t.detail + '</div>' : '') +
      '</span>' +
      '<span class="pri pri-' + t.priority + '">' + t.priority + '</span>';

    // Click handler to toggle status
    li.querySelector('.check-icon').addEventListener('click', async () => {
      try {
        const resp = await fetch('/api/checklist/' + t.id, { method: 'PATCH' });
        if (resp.ok) { location.reload(); }
      } catch (e) { console.error('Toggle failed', e); }
    });

    list.appendChild(li);
  });
}

function renderCmd(d) {
  if (!d.has_data) {
    document.getElementById('cmd-no-data').style.display = 'block';
    return;
  }
  document.getElementById('cmd-content').style.display = 'block';

  // KPIs
  const strip = document.getElementById('kpi-strip');
  const kpis = [
    { v: d.unique_theses, l: 'Unique Theses', c: 'var(--accent)' },
    { v: d.bullish_count, l: 'Bullish', c: 'var(--green)' },
    { v: d.bearish_count, l: 'Bearish', c: 'var(--red)' },
    { v: (d.avg_confidence * 100).toFixed(0) + '%', l: 'Avg Confidence', c: 'var(--purple)' },
    { v: d.theme_clusters.length, l: 'Themes', c: 'var(--teal)' },
  ];
  kpis.forEach(k => {
    strip.innerHTML += '<div class="kpi"><div class="kpi-val" style="color:' + k.c + '">' + k.v + '</div><div class="kpi-label">' + k.l + '</div></div>';
  });

  // Memo
  if (d.memo_summary) {
    document.getElementById('memo-box').style.display = 'block';
    document.getElementById('memo-box').textContent = d.memo_summary;
  }

  // Theme map
  const tm = document.getElementById('theme-map');
  d.theme_clusters.forEach(c => {
    const total = c.bullish + c.bearish + c.neutral + c.mixed + c.watchful;
    const pct = n => total ? (n / total * 100).toFixed(0) : 0;
    let bar = '';
    if (c.bullish) bar += '<div style="width:' + pct(c.bullish) + '%;background:var(--green)">' + c.bullish + '</div>';
    if (c.bearish) bar += '<div style="width:' + pct(c.bearish) + '%;background:var(--red)">' + c.bearish + '</div>';
    if (c.neutral) bar += '<div style="width:' + pct(c.neutral) + '%;background:var(--text-muted)">' + c.neutral + '</div>';
    if (c.mixed) bar += '<div style="width:' + pct(c.mixed) + '%;background:var(--yellow)">' + c.mixed + '</div>';
    if (c.watchful) bar += '<div style="width:' + pct(c.watchful) + '%;background:var(--purple)">' + c.watchful + '</div>';
    tm.innerHTML += '<div class="theme-row"><span class="theme-label">' + c.theme + '</span>' +
      '<div class="theme-bar">' + bar + '</div>' +
      '<span class="theme-conf">' + (c.avg_confidence * 100).toFixed(0) + '%</span></div>';
  });

  // Consensus / Divergence
  renderList('consensus-list', d.consensus_views, 'No consensus yet');
  renderList('divergence-list', d.divergent_views, 'No divergence detected');

  // Trades
  renderList('trades-list', d.suggested_positioning, 'No positioning suggestions');

  // Expert vs Market
  if (d.expert_vs_market && d.expert_vs_market.length) {
    document.getElementById('expert-section').style.display = 'block';
    const el = document.getElementById('expert-list');
    d.expert_vs_market.forEach(r => {
      const cls = r.includes('DISAGREES') ? 'expert-row expert-disagree' : 'expert-row';
      el.innerHTML += '<div class="' + cls + '">' + r + '</div>';
    });
  }

  // Risks
  const rc = document.getElementById('risks-card');
  if (d.risks_to_watch.length) {
    d.risks_to_watch.forEach(r => { rc.innerHTML += '<span class="risk-tag">' + r + '</span>'; });
  } else { rc.innerHTML = '<span class="empty-msg">No risks flagged</span>'; }

  // Thesis table
  const tb = document.getElementById('thesis-tbody');
  d.theses.forEach(t => {
    const assets = t.assets.map(a => '<span class="asset-tag">' + a + '</span>').join('');
    tb.innerHTML += '<tr>' +
      '<td><strong>' + t.theme + '</strong></td>' +
      '<td><span class="dir-badge dir-' + t.direction + '">' + t.direction + '</span></td>' +
      '<td style="max-width:320px">' + t.thesis + '</td>' +
      '<td>' + assets + '</td>' +
      '<td>' + (t.confidence * 100).toFixed(0) + '%</td>' +
      '<td style="font-size:12px;color:var(--text-dim)">' + t.horizon + '</td>' +
      '</tr>';
  });
}

function renderList(id, items, empty) {
  const el = document.getElementById(id);
  if (items && items.length) {
    items.forEach(v => { el.innerHTML += '<div class="list-item">' + v + '</div>'; });
  } else {
    el.innerHTML = '<span class="empty-msg">' + empty + '</span>';
  }
}

load();
</script>
</body>
</html>
"""
