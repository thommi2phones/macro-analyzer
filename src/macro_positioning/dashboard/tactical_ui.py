"""Tactical-executor standalone inspection dashboard.

READ-ONLY view of tactical state from the tactical-executor's public API.
Shows active setups, recent decisions with macro gate applied, lifecycle
states, and health. Used for debugging / inspection — not the operator's
primary flow (that's /positioning).

Nav: [Positioning]  [Tactical *]  [Dev]
"""

from __future__ import annotations


def tactical_dashboard_html() -> str:
    return _TACTICAL_HTML


_TACTICAL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Positioning · Tactical</title>
<style>
:root {
  --bg:#0a0d14;--surface:#121824;--surface-hi:#1a2132;--border:#1f2a3a;
  --border-hi:#2a3852;--text:#e8eef7;--text-dim:#8094b0;--text-muted:#4a5a75;
  --accent:#5b9cfe;--green:#2ecc71;--red:#ff5a5f;--yellow:#f5b642;
  --purple:#a679f0;--orange:#ff8642;--teal:#2dd4bf;
}
* {margin:0;padding:0;box-sizing:border-box;}
body {font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5;-webkit-font-smoothing:antialiased;
  background:linear-gradient(180deg,#0a0d14 0%,#0c1120 100%);}
.nav {position:sticky;top:0;z-index:50;background:rgba(10,13,20,0.85);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--border);
  padding:14px 24px;display:flex;align-items:center;gap:20px;}
.nav-brand {font-weight:700;font-size:16px;}
.nav-brand .dot {display:inline-block;width:8px;height:8px;border-radius:50%;
  background:var(--teal);margin-right:8px;box-shadow:0 0 8px var(--teal);}
.nav-links {display:flex;gap:4px;margin-left:auto;}
.nav-link {color:var(--text-dim);text-decoration:none;padding:6px 12px;
  border-radius:6px;font-size:13px;font-weight:500;}
.nav-link:hover {color:var(--text);background:var(--surface);}
.nav-link.active {color:var(--accent);background:rgba(91,156,254,0.08);}
.container {max-width:1280px;margin:0 auto;padding:28px 24px 80px;}
.status {padding:10px 14px;border-radius:8px;margin-bottom:20px;font-size:13px;}
.status-ok {background:rgba(46,204,113,0.08);border:1px solid rgba(46,204,113,0.22);color:var(--green);}
.status-warn {background:rgba(245,182,66,0.06);border:1px solid rgba(245,182,66,0.22);color:var(--yellow);}
.status-err {background:rgba(255,90,95,0.06);border:1px solid rgba(255,90,95,0.22);color:var(--red);}
.kpi-row {display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:22px;}
.kpi {background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}
.kpi .n {font-size:26px;font-weight:700;letter-spacing:-0.5px;line-height:1;}
.kpi .l {font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;}
.section {margin-bottom:24px;}
.section-head {font-size:14px;font-weight:600;color:var(--text-dim);
  text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;padding:0 4px;}
.card {background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;}
.decision-grid {display:grid;grid-template-columns:1fr 1fr;gap:16px;}
@media (max-width:720px){.decision-grid{grid-template-columns:1fr;}}
.event-row {display:grid;grid-template-columns:90px 60px 90px 1fr 80px;gap:10px;
  align-items:center;padding:8px 12px;border-bottom:1px solid var(--border);
  font-size:12px;font-family:'SF Mono',Menlo,monospace;}
.event-row:last-child {border-bottom:none;}
.event-time {color:var(--text-muted);}
.event-symbol {font-weight:600;color:var(--text);}
.event-stage {font-size:10px;padding:2px 8px;border-radius:3px;text-transform:uppercase;
  text-align:center;font-weight:600;letter-spacing:0.3px;}
.stage-watch {background:rgba(128,148,176,0.1);color:var(--text-dim);}
.stage-trigger {background:rgba(91,156,254,0.12);color:var(--accent);}
.stage-in_trade {background:rgba(46,204,113,0.14);color:var(--green);}
.stage-tp_zone {background:rgba(166,121,240,0.14);color:var(--purple);}
.stage-invalidated {background:rgba(255,90,95,0.12);color:var(--red);}
.stage-closed {background:rgba(122,133,153,0.08);color:var(--text-muted);}
.event-bias {font-size:11px;color:var(--text-dim);}
.confluence {font-size:10px;font-weight:600;padding:2px 7px;border-radius:3px;text-align:center;}
.conf-HIGH {background:rgba(46,204,113,0.14);color:var(--green);}
.conf-MEDIUM {background:rgba(245,182,66,0.12);color:var(--yellow);}
.conf-LOW {background:rgba(128,148,176,0.08);color:var(--text-dim);}
.dec-box {background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px;}
.dec-row {display:flex;justify-content:space-between;padding:5px 0;font-size:13px;}
.dec-row .k {color:var(--text-dim);}
.dec-row .v {font-weight:500;}
.dec-action {font-size:22px;font-weight:700;letter-spacing:-0.5px;margin-bottom:8px;}
.action-LONG {color:var(--green);}
.action-SHORT {color:var(--red);}
.action-WAIT {color:var(--text-dim);}
.macro-context {margin-top:12px;padding-top:10px;border-top:1px solid var(--border);font-size:12px;color:var(--text-dim);}
.empty-msg {color:var(--text-muted);font-size:13px;padding:18px;text-align:center;}
#loading {text-align:center;padding:60px;color:var(--text-dim);font-size:14px;}
@media (max-width:640px){.container{padding:14px 12px 60px;}.event-row{grid-template-columns:1fr 1fr;font-size:11px;}}
</style>
</head>
<body>
<nav class="nav">
  <span class="nav-brand"><span class="dot"></span>Tactical State</span>
  <div class="nav-links">
    <a href="/positioning" class="nav-link">Positioning</a>
    <a href="/tactical" class="nav-link active">Tactical</a>
    <a href="/dev" class="nav-link">Dev</a>
  </div>
</nav>
<div class="container">
<div id="loading">Loading tactical state…</div>
<div id="content" style="display:none">
  <div id="status-bar"></div>
  <div class="kpi-row" id="kpis"></div>
  <div class="section">
    <div class="section-head">Latest Decision (with Macro Gate)</div>
    <div id="decision-box" class="dec-box"><div class="empty-msg">No decision yet.</div></div>
  </div>
  <div class="section">
    <div class="section-head">Recent Events</div>
    <div class="card" id="events-card"><div class="empty-msg">No events yet.</div></div>
  </div>
  <div class="section">
    <div class="section-head">Lifecycle (active setups)</div>
    <div class="card" id="lifecycle-card"><div class="empty-msg">No lifecycle data.</div></div>
  </div>
</div>
</div>
<script>
async function load(){
  try {
    const r = await fetch('/api/dashboard/tactical-state');
    const data = await r.json();
    render(data);
  } catch(e){
    document.getElementById('loading').textContent='Failed to load: '+e.message;
  }
}
function escapeHtml(s){if(s==null)return'';return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function render(state){
  document.getElementById('loading').style.display='none';
  document.getElementById('content').style.display='block';

  // Status bar
  const sb = document.getElementById('status-bar');
  if (!state.configured) {
    sb.innerHTML = '<div class="status status-warn">MPA_TACTICAL_EXECUTOR_URL not configured. Set it in .env to see live tactical state.</div>';
    return;
  }
  if (!state.health || (state.events === null && state.latest_decision === null)) {
    sb.innerHTML = '<div class="status status-err">Tactical executor unreachable. Check URL and that the tactical service is running.</div>';
  } else {
    sb.innerHTML = '<div class="status status-ok">Connected to tactical-executor.</div>';
  }

  // KPIs
  const events = state.events || [];
  const lifecycle = state.lifecycle || {};
  const decision = state.latest_decision || {};

  const uniqSetups = new Set();
  let trigCount = 0, inTradeCount = 0, closedCount = 0;
  events.forEach(e=>{
    const p = e.payload || {};
    if (p.setup_id) uniqSetups.add(p.setup_id);
    const stage = (p.setup_stage||'').toLowerCase();
    if (stage === 'trigger') trigCount++;
    else if (stage === 'in_trade') inTradeCount++;
    else if (stage === 'closed' || stage === 'invalidated') closedCount++;
  });

  const k = document.getElementById('kpis');
  const kpis = [
    {n:uniqSetups.size,l:'Unique Setups',c:'var(--accent)'},
    {n:trigCount,l:'At Trigger',c:'var(--purple)'},
    {n:inTradeCount,l:'In Trade',c:'var(--green)'},
    {n:closedCount,l:'Closed/Inv',c:'var(--text-muted)'},
    {n:events.length,l:'Recent Events',c:'var(--teal)'},
  ];
  kpis.forEach(kp=>{
    k.innerHTML += '<div class="kpi"><div class="n" style="color:'+kp.c+'">'+kp.n+'</div><div class="l">'+kp.l+'</div></div>';
  });

  // Decision box
  if (decision && decision.ok && decision.decision) {
    const dec = decision.decision;
    const ap = decision.agent_packet || {};
    const mv = decision.macro_view || null;
    const action = (dec.action||'WAIT').toUpperCase();
    const reasons = (dec.reason_codes||[]).join(', ');
    let html = '<div class="dec-action action-'+action+'">'+action+'</div>';
    html += '<div class="dec-row"><span class="k">Symbol</span><span class="v">'+escapeHtml(ap.symbol||'')+'</span></div>';
    html += '<div class="dec-row"><span class="k">Setup</span><span class="v">'+escapeHtml(ap.setup_id||'')+'</span></div>';
    html += '<div class="dec-row"><span class="k">Stage</span><span class="v">'+escapeHtml(ap.stage||'')+'</span></div>';
    html += '<div class="dec-row"><span class="k">Confidence</span><span class="v">'+escapeHtml(dec.confidence||'')+'</span></div>';
    html += '<div class="dec-row"><span class="k">Risk tier</span><span class="v">'+escapeHtml(dec.risk_tier||'')+'</span></div>';
    html += '<div class="dec-row"><span class="k">Direction score</span><span class="v">'+(dec.direction_score||0)+'</span></div>';
    if (reasons) html += '<div class="dec-row"><span class="k">Reasons</span><span class="v" style="text-align:right;max-width:60%">'+escapeHtml(reasons)+'</span></div>';
    if (mv && mv.direction) {
      html += '<div class="macro-context"><strong>Macro context</strong>: '
          +escapeHtml(mv.direction)+' (conf '+(mv.confidence||0).toFixed(2)+')'
          +' · gate: '+escapeHtml(mv.gate_suggestion?.notes||'')+'</div>';
    }
    document.getElementById('decision-box').innerHTML = html;
  }

  // Events
  if (events.length) {
    const ec = document.getElementById('events-card');
    ec.innerHTML = '';
    events.slice(0,25).forEach(e=>{
      const p = e.payload || {};
      const ts = new Date(e.received_at||'');
      const tstr = isNaN(ts.getTime()) ? '' : ts.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
      const stage = (p.setup_stage||'watch').toLowerCase();
      const conf = (p.confluence||'LOW').toUpperCase();
      ec.innerHTML += '<div class="event-row">'
        +'<span class="event-time">'+tstr+'</span>'
        +'<span class="event-symbol">'+escapeHtml(p.symbol||'')+'</span>'
        +'<span class="event-stage stage-'+stage+'">'+stage+'</span>'
        +'<span class="event-bias">'+escapeHtml(p.pattern_type||'')+' · '+escapeHtml(p.bias||'')+'</span>'
        +'<span class="confluence conf-'+conf+'">'+conf+'</span>'
        +'</div>';
    });
  }

  // Lifecycle
  if (lifecycle && lifecycle.setups && lifecycle.setups.length) {
    const lc = document.getElementById('lifecycle-card');
    lc.innerHTML = '';
    lifecycle.setups.slice(0,20).forEach(s=>{
      lc.innerHTML += '<div class="event-row" style="grid-template-columns:100px 80px 1fr 80px">'
        +'<span class="event-symbol">'+escapeHtml(s.setup_id||'')+'</span>'
        +'<span class="event-stage stage-'+(s.current_state||'watch')+'">'+escapeHtml(s.current_state||'')+'</span>'
        +'<span class="event-bias">'+(s.transition_count||0)+' transitions</span>'
        +'<span class="event-time">'+((s.anomalies||[]).length)+' anomal</span>'
        +'</div>';
    });
  }
}
load();
</script>
</body>
</html>
"""
