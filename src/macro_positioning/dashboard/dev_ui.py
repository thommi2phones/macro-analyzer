"""Dev/Ops dashboard — builder-facing status UI.

Shows project build state, checklist, system health, brain activity.
This is the "what do we need to build?" view, separate from the
trader-facing `/positioning` consumer UI.
"""

from __future__ import annotations


def dev_dashboard_html() -> str:
    return _DEV_HTML


_DEV_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Positioning · Dev</title>
<style>
:root {
  --bg: #0a0d14; --surface: #121824; --surface-hi: #1a2132;
  --border: #1f2a3a; --border-hi: #2a3852;
  --text: #e8eef7; --text-dim: #8094b0; --text-muted: #4a5a75;
  --accent: #5b9cfe; --green: #2ecc71; --red: #ff5a5f;
  --yellow: #f5b642; --purple: #a679f0; --orange: #ff8642; --teal: #2dd4bf;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg); color: var(--text); line-height:1.5; -webkit-font-smoothing:antialiased;
  background: linear-gradient(180deg, #0a0d14 0%, #0c1120 100%); }
.nav { position:sticky; top:0; z-index:50; background: rgba(10,13,20,0.85);
  backdrop-filter:blur(12px); border-bottom:1px solid var(--border);
  padding:14px 24px; display:flex; align-items:center; gap:20px; }
.nav-brand { font-weight:700; font-size:16px; }
.nav-brand .dot { display:inline-block; width:8px; height:8px; border-radius:50%;
  background: var(--yellow); margin-right:8px; box-shadow:0 0 8px var(--yellow); }
.nav-links { display:flex; gap:4px; margin-left:auto; }
.nav-link { color: var(--text-dim); text-decoration:none; padding:6px 12px;
  border-radius:6px; font-size:13px; font-weight:500; }
.nav-link:hover { color: var(--text); background: var(--surface); }
.nav-link.active { color: var(--accent); background: rgba(91,156,254,0.08); }
.container { max-width:1280px; margin:0 auto; padding:28px 24px 80px; }
.kpi-row { display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:12px; margin-bottom:22px; }
.kpi { background: var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 16px; }
.kpi .n { font-size:28px; font-weight:700; letter-spacing:-1px; line-height:1; }
.kpi .l { font-size:11px; color: var(--text-dim); text-transform:uppercase; letter-spacing:0.4px; margin-top:5px; }
.status-row { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:22px; }
.chip { font-size:12px; padding:5px 12px; border-radius:6px; font-weight:500;
  display:inline-flex; align-items:center; gap:6px; }
.chip::before { content:'●'; }
.chip-ok { background: rgba(46,204,113,0.1); color: var(--green); border:1px solid rgba(46,204,113,0.2); }
.chip-warn { background: rgba(245,182,66,0.08); color: var(--yellow); border:1px solid rgba(245,182,66,0.2); }
.chip-off { background: rgba(128,148,176,0.06); color: var(--text-muted); border:1px solid var(--border); }
.section { margin-bottom:28px; }
.section-head { font-size:15px; font-weight:600; margin-bottom:14px;
  display:flex; justify-content:space-between; align-items:baseline; padding:0 4px; }
.section-meta { font-size:12px; color: var(--text-muted); font-weight:500; }
.progress-bar { height:6px; background: var(--border); border-radius:3px; overflow:hidden; margin-bottom:8px; }
.progress-fill { height:100%; background: var(--green); transition: width .4s ease; }
.card { background: var(--surface); border:1px solid var(--border); border-radius:10px; padding:18px; }
.checklist { list-style:none; }
.checklist li { display:flex; gap:10px; padding:10px 0; border-bottom:1px solid var(--border); align-items:flex-start; }
.checklist li:last-child { border-bottom:none; }
.icon { flex-shrink:0; width:20px; height:20px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-size:11px; cursor:pointer; margin-top:1px; user-select:none; transition: transform .1s; }
.icon:hover { transform:scale(1.15); }
.i-done { background: rgba(46,204,113,0.14); color: var(--green); }
.i-wip { background: rgba(91,156,254,0.15); color: var(--accent); }
.i-todo { background:transparent; color: var(--text-muted); border:1px solid var(--border-hi); }
.t { flex:1; }
.t .title { font-weight:500; font-size:13px; }
.t .detail { font-size:12px; color: var(--text-dim); margin-top:2px; }
.done .title, .done .detail { text-decoration:line-through; color: var(--text-muted); }
.pri { font-size:10px; font-weight:700; padding:2px 7px; border-radius:4px;
  text-transform:uppercase; letter-spacing:0.3px; flex-shrink:0; }
.p-critical { background: rgba(255,90,95,0.12); color: var(--red); }
.p-high { background: rgba(245,182,66,0.12); color: var(--yellow); }
.p-medium { background: rgba(91,156,254,0.1); color: var(--accent); }
.p-low { background: rgba(128,148,176,0.08); color: var(--text-muted); }
.brain-list { display:flex; flex-direction:column; gap:8px; }
.brain-row { display:grid; grid-template-columns: 90px 110px 100px 1fr 60px; align-items:center;
  padding:9px 12px; background: var(--surface); border:1px solid var(--border); border-radius:8px; font-size:12px; }
.brain-row .t-time { color: var(--text-muted); font-family: 'SF Mono', Menlo, monospace; font-size:11px; }
.brain-row .t-type { font-weight:600; }
.brain-row .t-model { font-family: 'SF Mono', Menlo, monospace; color: var(--text-dim); }
.brain-row .t-meta { color: var(--text-dim); }
.brain-row .t-lat { text-align:right; font-family: 'SF Mono', Menlo, monospace; color: var(--text-dim); }
.empty-msg { font-size:13px; color: var(--text-muted); text-align:center; padding:20px; }
#loading { text-align:center; padding:80px 20px; color: var(--text-dim); font-size:14px; }
@media (max-width:640px) {
  .container { padding:16px 12px 60px; }
  .brain-row { grid-template-columns: 1fr 1fr; font-size:11px; }
  .brain-row .t-time, .brain-row .t-meta { grid-column:1/-1; }
}
</style>
</head>
<body>
<nav class="nav">
  <span class="nav-brand"><span class="dot"></span>Macro Positioning · Dev</span>
  <div class="nav-links">
    <a href="/positioning" class="nav-link">Positioning</a>
    <a href="/dev" class="nav-link active">Dev Status</a>
  </div>
</nav>
<div class="container">
<div id="loading">Loading…</div>
<div id="content" style="display:none">
  <div class="kpi-row" id="kpis"></div>
  <div class="status-row" id="chips"></div>
  <div class="section">
    <div class="section-head">
      <span>Build Progress</span>
      <span class="section-meta" id="progress-label">—</span>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progress"></div></div>
  </div>
  <div class="section">
    <div class="section-head">
      <span>Task Backlog</span>
      <span class="section-meta">Click ● to toggle status</span>
    </div>
    <div class="card"><ul class="checklist" id="checklist"></ul></div>
  </div>
  <div class="section">
    <div class="section-head">
      <span>Brain Activity</span>
      <span class="section-meta" id="brain-meta">—</span>
    </div>
    <div class="brain-list" id="brain-list"></div>
  </div>
</div>
</div>
<script>
async function load() {
  try {
    const [ops, cl, brain] = await Promise.all([
      fetch('/api/dashboard/ops').then(r => r.json()),
      fetch('/api/checklist').then(r => r.json()),
      fetch('/api/dashboard/brain/activity?limit=12').then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    render(ops, cl, brain);
  } catch (e) {
    document.getElementById('loading').textContent = 'Failed to load: ' + e.message;
  }
}
function render(ops, cl, brain) {
  document.getElementById('loading').style.display = 'none';
  document.getElementById('content').style.display = 'block';
  const fredCount = (ops.data_sources.find(s => s.name.includes('FRED'))?.series_count || 0);
  const kpis = [
    { n: ops.db_stats.documents, l: 'Documents', c: 'var(--accent)' },
    { n: ops.db_stats.theses, l: 'Theses', c: 'var(--purple)' },
    { n: ops.db_stats.memos, l: 'Memos', c: 'var(--green)' },
    { n: fredCount, l: 'FRED Series', c: 'var(--orange)' },
    { n: ops.newsletter_sources.length, l: 'Newsletters', c: 'var(--yellow)' },
    { n: brain?.stats?.total_calls || 0, l: 'Brain Calls', c: 'var(--teal)' },
  ];
  const k = document.getElementById('kpis');
  kpis.forEach(kp => {
    k.innerHTML += '<div class="kpi"><div class="n" style="color:' + kp.c + '">' + kp.n + '</div><div class="l">' + kp.l + '</div></div>';
  });
  const chips = document.getElementById('chips');
  (ops.data_sources || []).forEach(s => {
    const cls = s.connected ? 'chip-ok' : (s.detail.includes('catalogued') || s.detail.includes('not built') ? 'chip-off' : 'chip-warn');
    chips.innerHTML += '<span class="chip ' + cls + '">' + s.name.split('(')[0].trim() + '</span>';
  });
  const items = cl.items || [];
  const done = items.filter(i => i.status === 'done').length;
  const total = items.length;
  const pct = total ? Math.round(done/total*100) : 0;
  document.getElementById('progress').style.width = pct + '%';
  document.getElementById('progress-label').textContent = done + ' / ' + total + ' (' + pct + '%)';
  const order = { todo: 0, in_progress: 1, done: 2 };
  const pri = { critical: 0, high: 1, medium: 2, low: 3 };
  items.sort((a, b) => {
    if (order[a.status] !== order[b.status]) return order[a.status] - order[b.status];
    return (pri[a.priority]||9) - (pri[b.priority]||9);
  });
  const cle = document.getElementById('checklist');
  items.forEach(t => {
    const icon = t.status === 'done' ? '✓' : t.status === 'in_progress' ? '▶' : '';
    const iCls = t.status === 'done' ? 'i-done' : t.status === 'in_progress' ? 'i-wip' : 'i-todo';
    const doneCls = t.status === 'done' ? 'done' : '';
    const li = document.createElement('li');
    li.setAttribute('data-id', t.id);
    li.innerHTML = '<span class="icon ' + iCls + '" title="Click to toggle">' + icon + '</span>'
      + '<span class="t ' + doneCls + '"><span class="title">' + escapeHtml(t.title) + '</span>'
      + (t.detail ? '<div class="detail">' + escapeHtml(t.detail) + '</div>' : '') + '</span>'
      + '<span class="pri p-' + t.priority + '">' + t.priority + '</span>';
    li.querySelector('.icon').addEventListener('click', async () => {
      try {
        const r = await fetch('/api/checklist/' + encodeURIComponent(t.id), { method: 'PATCH' });
        if (r.ok) location.reload();
      } catch (e) { console.error(e); }
    });
    cle.appendChild(li);
  });
  const bl = document.getElementById('brain-list');
  const calls = brain?.recent || [];
  if (brain?.stats) {
    document.getElementById('brain-meta').textContent =
      brain.stats.synthesis_calls + ' synthesis · ' + brain.stats.vision_calls + ' vision · '
      + brain.stats.avg_latency_ms.toFixed(0) + 'ms avg · ' + (brain.stats.error_rate*100).toFixed(0) + '% err';
  }
  if (!calls.length) {
    bl.innerHTML = '<div class="empty-msg">No brain activity yet. Run a pipeline.</div>';
  } else {
    calls.forEach(c => {
      const t = new Date(c.timestamp);
      const timestr = t.toLocaleString(undefined, { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
      const statusCol = c.success ? 'var(--green)' : 'var(--red)';
      const typeCol = c.call_type === 'synthesis' ? 'var(--purple)' : 'var(--teal)';
      bl.innerHTML += '<div class="brain-row">'
        + '<span class="t-time">' + timestr + '</span>'
        + '<span class="t-type" style="color:' + typeCol + '">' + c.call_type + '</span>'
        + '<span class="t-model">' + escapeHtml(c.model || c.backend) + '</span>'
        + '<span class="t-meta">'
        + (c.input_size ? Math.round(c.input_size/1000) + 'k→' + Math.round(c.output_size/1000) + 'k' : '')
        + (c.theses_count ? ' · ' + c.theses_count + ' theses' : '')
        + (!c.success ? ' · <span style="color:var(--red)">' + escapeHtml(c.error||'err') + '</span>' : '')
        + '</span>'
        + '<span class="t-lat" style="color:' + statusCol + '">' + c.latency_ms.toFixed(0) + 'ms</span>'
        + '</div>';
    });
  }
}
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
load();
</script>
</body>
</html>
"""
