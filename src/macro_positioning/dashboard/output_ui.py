"""Positioning dashboard — trader-facing output UI (hero-first redesign).

Layout (top → bottom):
  1. Current macro regime
  2. TOP ACTIONABLE SIGNALS (hero) — LONG / SHORT / WATCH per asset
     with inline tactical state annotations
  3. Theme direction map (preserved)
  4. Per-asset breakdown (new — drill-down below themes)
  5. Risks to watch
  6. Active theses (expandable)

Nav: [Positioning *] [Tactical] [Dev]
"""

from __future__ import annotations


def positioning_dashboard_html() -> str:
    return _POSITIONING_HTML


_POSITIONING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Positioning</title>
<style>
:root {
  --bg:#0a0d14;--surface:#121824;--surface-hi:#1a2132;
  --border:#1f2a3a;--border-hi:#2a3852;
  --text:#e8eef7;--text-dim:#8094b0;--text-muted:#4a5a75;
  --accent:#5b9cfe;--green:#2ecc71;--red:#ff5a5f;
  --yellow:#f5b642;--purple:#a679f0;--orange:#ff8642;--teal:#2dd4bf;
}
* {margin:0;padding:0;box-sizing:border-box;}
body {font-family:'Inter',-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5;
  min-height:100vh;-webkit-font-smoothing:antialiased;
  background:linear-gradient(180deg,#0a0d14 0%,#0c1120 100%);}

/* Nav */
.nav {position:sticky;top:0;z-index:50;background:rgba(10,13,20,0.85);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--border);
  padding:14px 24px;display:flex;align-items:center;gap:20px;}
.nav-brand {font-weight:700;font-size:16px;}
.nav-brand .dot {display:inline-block;width:8px;height:8px;border-radius:50%;
  background:var(--green);margin-right:8px;box-shadow:0 0 8px var(--green);}
.nav-links {display:flex;gap:4px;margin-left:auto;}
.nav-link {color:var(--text-dim);text-decoration:none;padding:6px 12px;
  border-radius:6px;font-size:13px;font-weight:500;}
.nav-link:hover {color:var(--text);background:var(--surface);}
.nav-link.active {color:var(--accent);background:rgba(91,156,254,0.08);}

.container {max-width:1280px;margin:0 auto;padding:24px 24px 80px;}

/* Regime hero */
.regime-card {background:linear-gradient(135deg,#1a2132 0%,#0f1623 100%);
  border:1px solid var(--border-hi);border-radius:14px;padding:22px 26px;
  margin-bottom:18px;position:relative;overflow:hidden;}
.regime-card::before {content:'';position:absolute;top:0;right:0;width:280px;height:280px;
  background:radial-gradient(circle,rgba(91,156,254,0.08) 0%,transparent 70%);pointer-events:none;}
.regime-label {font-size:11px;font-weight:600;letter-spacing:1.5px;
  color:var(--text-dim);text-transform:uppercase;margin-bottom:10px;}
.regime-text {font-size:18px;line-height:1.45;font-weight:600;letter-spacing:-0.2px;}
.regime-ts {font-size:11px;color:var(--text-muted);margin-top:12px;
  display:flex;align-items:center;gap:8px;}

/* Signal hero */
.signals-hero {background:var(--surface);border:1px solid var(--border-hi);
  border-radius:14px;padding:22px 24px;margin-bottom:22px;}
.hero-title {font-size:12px;font-weight:700;letter-spacing:1.5px;
  color:var(--text-dim);text-transform:uppercase;margin-bottom:14px;}
.signal-group {margin-bottom:16px;}
.signal-group:last-child {margin-bottom:0;}
.signal-group-head {font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
  padding:6px 10px;border-radius:5px;display:inline-block;margin-bottom:10px;}
.group-LONG {background:rgba(46,204,113,0.14);color:var(--green);}
.group-SHORT {background:rgba(255,90,95,0.14);color:var(--red);}
.group-WATCH {background:rgba(166,121,240,0.14);color:var(--purple);}
.signal {padding:11px 14px;border:1px solid var(--border);border-radius:9px;
  margin-bottom:6px;display:grid;grid-template-columns:1fr auto;gap:10px;align-items:start;
  background:var(--surface-hi);transition:border-color .12s;}
.signal:hover {border-color:var(--border-hi);}
.signal-main .asset {font-size:15px;font-weight:700;letter-spacing:-0.2px;}
.signal-main .meta {font-size:12px;color:var(--text-dim);margin-top:2px;}
.signal-main .rat {font-size:12px;color:var(--text);margin-top:6px;line-height:1.4;}
.signal-main .rat {display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.signal-right {text-align:right;min-width:100px;}
.conv-bar {display:inline-block;vertical-align:middle;width:48px;height:5px;
  background:var(--border);border-radius:3px;overflow:hidden;margin-bottom:3px;}
.conv-bar > div {height:100%;background:var(--accent);}
.conv-label {font-size:11px;color:var(--text-dim);}
.tact-annotation {font-size:11px;color:var(--text-dim);margin-top:8px;
  padding-top:6px;border-top:1px dashed var(--border);grid-column:1/-1;display:flex;gap:10px;flex-wrap:wrap;}
.tact-pill {background:rgba(45,212,191,0.08);border:1px solid rgba(45,212,191,0.2);
  color:var(--teal);padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.3px;}
.tact-none {font-style:italic;color:var(--text-muted);}

/* Section headers */
.section {margin-bottom:24px;}
.section-head {font-size:14px;font-weight:600;letter-spacing:-0.1px;margin-bottom:12px;
  display:flex;justify-content:space-between;align-items:baseline;padding:0 4px;}
.section-meta {font-size:12px;color:var(--text-muted);font-weight:500;}

/* Themes */
.themes-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;}
.theme-card {background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:13px 15px;}
.theme-name {font-size:13px;font-weight:600;text-transform:capitalize;
  margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;}
.theme-bar {display:flex;height:22px;border-radius:5px;overflow:hidden;background:var(--border);margin-bottom:6px;}
.theme-bar > div {display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:600;color:white;min-width:22px;}
.theme-stats {font-size:11px;color:var(--text-dim);}

/* Per-asset */
.assets-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;}
.asset-card {background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;display:flex;justify-content:space-between;align-items:center;}
.asset-card .asset-name {font-weight:600;font-size:13px;text-transform:capitalize;}
.asset-card .asset-meta {font-size:10px;color:var(--text-dim);margin-top:2px;}
.dir-badge-sm {font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px;
  text-transform:uppercase;letter-spacing:0.3px;}
.dir-bullish {background:rgba(46,204,113,0.14);color:var(--green);}
.dir-bearish {background:rgba(255,90,95,0.14);color:var(--red);}
.dir-neutral {background:rgba(128,148,176,0.12);color:var(--text-dim);}
.dir-mixed {background:rgba(245,182,66,0.14);color:var(--yellow);}
.dir-watchful {background:rgba(166,121,240,0.14);color:var(--purple);}

/* Risks */
.risks-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px;}
.risk-card {background:rgba(255,90,95,0.04);border:1px solid rgba(255,90,95,0.22);
  border-radius:9px;padding:12px 14px 12px 38px;position:relative;font-size:13px;line-height:1.5;}
.risk-card::before {content:'⚠';position:absolute;top:12px;left:12px;color:var(--red);font-size:15px;}

/* Theses */
.theses-list {display:flex;flex-direction:column;gap:8px;}
.thesis {background:var(--surface);border:1px solid var(--border);border-radius:9px;overflow:hidden;}
.thesis-head {padding:12px 16px;cursor:pointer;display:flex;align-items:center;gap:11px;}
.thesis-head:hover {background:var(--surface-hi);}
.thesis-theme {font-size:13px;font-weight:600;text-transform:capitalize;min-width:100px;}
.thesis-text {flex:1;font-size:13px;color:var(--text);overflow:hidden;
  text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
.thesis-conf {font-size:12px;color:var(--text-dim);white-space:nowrap;display:flex;align-items:center;gap:5px;}
.thesis-body {padding:0 16px 14px;font-size:12px;border-top:1px solid var(--border);
  max-height:0;overflow:hidden;transition:max-height .25s;}
.thesis.open .thesis-body {max-height:600px;padding-top:12px;}

.empty {text-align:center;padding:50px 18px;}
.empty h2 {font-size:17px;margin-bottom:6px;}
.empty p {color:var(--text-dim);font-size:13px;}
#loading {text-align:center;padding:70px 20px;color:var(--text-dim);font-size:14px;}
.tact-status {font-size:11px;color:var(--text-muted);padding:6px 0;}
.tact-status.ok {color:var(--teal);}
.tact-status.warn {color:var(--yellow);}

@media (max-width:640px){
  .container {padding:14px 12px 60px;}
  .nav {padding:12px 16px;}
  .regime-card {padding:18px;}
  .regime-text {font-size:16px;}
  .signal {grid-template-columns:1fr;}
  .signal-right {text-align:left;}
}
</style>
</head>
<body>
<nav class="nav">
  <span class="nav-brand"><span class="dot"></span>Macro Positioning</span>
  <div class="nav-links">
    <a href="/positioning" class="nav-link active">Positioning</a>
    <a href="/tactical" class="nav-link">Tactical</a>
    <a href="/dev" class="nav-link">Dev</a>
  </div>
</nav>
<div class="container">
<div id="loading">Loading positioning…</div>
<div id="empty" class="empty" style="display:none">
  <h2>No analysis yet</h2>
  <p>Run a pipeline to generate theses.</p>
</div>
<div id="content" style="display:none">

  <!-- 1. Regime -->
  <div class="regime-card">
    <div class="regime-label">Current Macro Regime</div>
    <div class="regime-text" id="regime-text">—</div>
    <div class="regime-ts">
      <span>⏱</span><span id="regime-ts">—</span>
      <span id="tact-status-inline" class="tact-status"></span>
    </div>
  </div>

  <!-- 2. Top Actionable Signals (HERO) -->
  <div class="signals-hero">
    <div class="hero-title">Top Actionable Signals</div>
    <div id="signals-long" class="signal-group"></div>
    <div id="signals-short" class="signal-group"></div>
    <div id="signals-watch" class="signal-group"></div>
    <div id="signals-empty" class="empty-msg" style="display:none;color:var(--text-muted);font-size:13px;text-align:center;padding:18px">
      No actionable signals yet — theses need `assets` populated.
    </div>
  </div>

  <!-- 3. Theme direction map -->
  <div class="section">
    <div class="section-head">
      <span>Theme Direction Map</span>
      <span class="section-meta" id="themes-count"></span>
    </div>
    <div class="themes-grid" id="themes-grid"></div>
  </div>

  <!-- 4. Per-asset breakdown -->
  <div class="section">
    <div class="section-head">
      <span>Per-Asset Breakdown</span>
      <span class="section-meta" id="assets-count"></span>
    </div>
    <div class="assets-grid" id="assets-grid"></div>
  </div>

  <!-- 5. Risks -->
  <div class="section" id="risks-section" style="display:none">
    <div class="section-head">
      <span>Risks to Watch</span>
      <span class="section-meta" id="risks-count"></span>
    </div>
    <div class="risks-grid" id="risks-grid"></div>
  </div>

  <!-- 6. Active Theses -->
  <div class="section">
    <div class="section-head">
      <span>Active Theses</span>
      <span class="section-meta" id="theses-count"></span>
    </div>
    <div class="theses-list" id="theses-list"></div>
  </div>

</div>
</div>

<script>
function escapeHtml(s){if(s==null)return'';return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

async function load(){
  try {
    const [cmdR, memoR] = await Promise.all([
      fetch('/api/dashboard/command-center').then(r=>r.json()),
      fetch('/memos/latest').then(r=>r.ok?r.json():null).catch(()=>null),
    ]);
    render(cmdR, memoR);
  } catch(e){
    document.getElementById('loading').textContent='Failed to load: '+e.message;
  }
}

function render(cmd, memo){
  document.getElementById('loading').style.display='none';
  if (!cmd || !cmd.has_data) {
    document.getElementById('empty').style.display='block';
    return;
  }
  document.getElementById('content').style.display='block';

  // Regime
  document.getElementById('regime-text').textContent = cmd.memo_summary || memo?.summary || 'No regime summary yet.';
  if (cmd.generated_at) {
    const d = new Date(cmd.generated_at);
    document.getElementById('regime-ts').textContent = d.toLocaleString();
  }
  const tactStatus = document.getElementById('tact-status-inline');
  if (cmd.tactical_reachable) {
    tactStatus.textContent = '· tactical: connected';
    tactStatus.className = 'tact-status ok';
  } else {
    tactStatus.textContent = '· tactical: offline';
    tactStatus.className = 'tact-status warn';
  }

  // Actionable signals
  const signals = cmd.actionable_signals || [];
  const groups = {LONG:[], SHORT:[], WATCH:[]};
  signals.forEach(s=>{(groups[s.side]||groups.WATCH).push(s);});

  if (signals.length === 0) {
    document.getElementById('signals-empty').style.display = 'block';
  }

  renderSignalGroup('signals-long', 'LONG', groups.LONG);
  renderSignalGroup('signals-short', 'SHORT', groups.SHORT);
  renderSignalGroup('signals-watch', 'WATCH', groups.WATCH);

  // Themes
  const themes = cmd.theme_clusters || [];
  document.getElementById('themes-count').textContent = themes.length + ' theme' + (themes.length!==1?'s':'');
  const tg = document.getElementById('themes-grid');
  themes.forEach(c=>{
    const total = c.bullish+c.bearish+c.neutral+c.mixed+c.watchful;
    const pct = n => total ? (n/total*100).toFixed(0) : 0;
    let bar = '';
    if (c.bullish) bar += '<div style="width:'+pct(c.bullish)+'%;background:var(--green)">'+c.bullish+'</div>';
    if (c.bearish) bar += '<div style="width:'+pct(c.bearish)+'%;background:var(--red)">'+c.bearish+'</div>';
    if (c.mixed) bar += '<div style="width:'+pct(c.mixed)+'%;background:var(--yellow)">'+c.mixed+'</div>';
    if (c.watchful) bar += '<div style="width:'+pct(c.watchful)+'%;background:var(--purple)">'+c.watchful+'</div>';
    if (c.neutral) bar += '<div style="width:'+pct(c.neutral)+'%;background:var(--text-muted)">'+c.neutral+'</div>';
    tg.innerHTML += '<div class="theme-card">'
      +'<div class="theme-name"><span>'+escapeHtml(c.theme)+'</span>'
      +'<span style="font-size:11px;color:var(--text-dim)">'+(c.avg_confidence*100).toFixed(0)+'%</span></div>'
      +'<div class="theme-bar">'+bar+'</div>'
      +'<div class="theme-stats">'+total+' thes'+(total===1?'is':'es')+' · '+c.dominant_direction+'</div>'
      +'</div>';
  });

  // Per-asset breakdown
  const assets = cmd.asset_breakdown || [];
  document.getElementById('assets-count').textContent = assets.length + ' asset' + (assets.length!==1?'s':'');
  const ag = document.getElementById('assets-grid');
  assets.forEach(a=>{
    ag.innerHTML += '<div class="asset-card">'
      +'<div><div class="asset-name">'+escapeHtml(a.asset)+'</div>'
      +'<div class="asset-meta">'+a.thesis_count+' thes'+(a.thesis_count===1?'is':'es')+' · '+(a.confidence*100).toFixed(0)+'% conv</div></div>'
      +'<span class="dir-badge-sm dir-'+a.dominant_direction+'">'+a.dominant_direction+'</span>'
      +'</div>';
  });

  // Risks
  const risks = (memo?.risks_to_watch) || cmd.risks_to_watch || [];
  if (risks.length) {
    document.getElementById('risks-section').style.display='block';
    document.getElementById('risks-count').textContent = risks.length;
    const rg = document.getElementById('risks-grid');
    risks.forEach(r=>{
      const el = document.createElement('div');
      el.className = 'risk-card';
      el.textContent = r;
      rg.appendChild(el);
    });
  }

  // Theses
  const theses = cmd.theses || [];
  document.getElementById('theses-count').textContent = theses.length + ' active';
  const tl = document.getElementById('theses-list');
  theses.forEach(t=>{
    const conf = Math.round((t.confidence||0)*100);
    const el = document.createElement('div');
    el.className = 'thesis';
    const positioning = (t.implied_positioning||[]).map(p=>'<li>'+escapeHtml(p)+'</li>').join('');
    el.innerHTML = '<div class="thesis-head">'
      +'<span class="dir-badge-sm dir-'+t.direction+'">'+t.direction+'</span>'
      +'<span class="thesis-theme">'+escapeHtml(t.theme)+'</span>'
      +'<span class="thesis-text">'+escapeHtml(t.thesis)+'</span>'
      +'<span class="thesis-conf">'+conf+'%</span>'
      +'</div>'
      +'<div class="thesis-body">'
      +'<div style="margin-bottom:8px"><strong>Horizon:</strong> '+escapeHtml(t.horizon||'—')+'</div>'
      +(positioning?'<div><strong>Positioning:</strong><ul style="margin-left:18px">'+positioning+'</ul></div>':'')
      +'</div>';
    el.querySelector('.thesis-head').addEventListener('click',()=>el.classList.toggle('open'));
    tl.appendChild(el);
  });
}

function renderSignalGroup(elementId, side, items){
  const el = document.getElementById(elementId);
  if (!items.length) { el.style.display='none'; return; }
  let html = '<div class="signal-group-head group-'+side+'">'+side+'</div>';
  items.slice(0,8).forEach(s=>{
    const conv = Math.round((s.conviction||0)*100);
    const rat = s.rationale ? '<div class="rat">'+escapeHtml(s.rationale)+'</div>' : '';
    let tactHtml = '';
    if (s.tactical && s.tactical.active_setups) {
      const parts = [];
      if (s.tactical.active_setups) parts.push('<span class="tact-pill">'+s.tactical.active_setups+' setup'+(s.tactical.active_setups>1?'s':'')+'</span>');
      if (s.tactical.at_entry) parts.push('<span class="tact-pill">'+s.tactical.at_entry+' at entry</span>');
      if (s.tactical.in_trade) parts.push('<span class="tact-pill">'+s.tactical.in_trade+' in trade</span>');
      if (s.tactical.latest_stage) parts.push('<span class="tact-pill">'+escapeHtml(s.tactical.latest_stage)+'</span>');
      tactHtml = '<div class="tact-annotation">'+parts.join('')+'</div>';
    } else {
      tactHtml = '<div class="tact-annotation tact-none">no tactical setups</div>';
    }
    html += '<div class="signal">'
      +'<div class="signal-main">'
      +'<div class="asset">'+escapeHtml(s.asset)+'</div>'
      +'<div class="meta">'+escapeHtml(s.theme||'—')+' · '+escapeHtml(s.horizon||'')+'</div>'
      +rat
      +'</div>'
      +'<div class="signal-right">'
      +'<div class="conv-bar"><div style="width:'+conv+'%"></div></div>'
      +'<div class="conv-label">'+conv+'% conv</div>'
      +'</div>'
      +tactHtml
      +'</div>';
  });
  el.innerHTML = html;
}
load();
</script>
</body>
</html>
"""
