"""Positioning dashboard — trader-facing output UI.

This is the CONSUMER dashboard — what you look at when you want to see
the macro analysis itself, not the build status. Clean, focused,
mobile-friendly. Designed to answer: "what's the current positioning?"
in under 5 seconds.
"""

from __future__ import annotations


def positioning_dashboard_html() -> str:
    return _POSITIONING_HTML


_POSITIONING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Positioning</title>
<style>
:root {
  --bg: #0a0d14; --surface: #121824; --surface-hi: #1a2132;
  --border: #1f2a3a; --border-hi: #2a3852;
  --text: #e8eef7; --text-dim: #8094b0; --text-muted: #4a5a75;
  --accent: #5b9cfe; --green: #2ecc71; --red: #ff5a5f;
  --yellow: #f5b642; --purple: #a679f0; --orange: #ff8642; --teal: #2dd4bf;
  --shadow: 0 4px 24px rgba(0,0,0,0.2);
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.5;
  min-height: 100vh; -webkit-font-smoothing: antialiased;
  background: linear-gradient(180deg, #0a0d14 0%, #0c1120 100%);
}

/* Top nav */
.nav { position: sticky; top: 0; z-index: 50; background: rgba(10,13,20,0.85);
  backdrop-filter: blur(12px); border-bottom: 1px solid var(--border);
  padding: 14px 24px; display: flex; align-items: center; gap: 20px; }
.nav-brand { font-weight: 700; font-size: 16px; letter-spacing: -0.2px; }
.nav-brand .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: var(--green); margin-right: 8px; box-shadow: 0 0 8px var(--green); }
.nav-links { display: flex; gap: 4px; margin-left: auto; }
.nav-link { color: var(--text-dim); text-decoration: none; padding: 6px 12px;
  border-radius: 6px; font-size: 13px; font-weight: 500; }
.nav-link:hover { color: var(--text); background: var(--surface); }
.nav-link.active { color: var(--accent); background: rgba(91,156,254,0.08); }

.container { max-width: 1280px; margin: 0 auto; padding: 28px 24px 80px; }

/* HERO — regime + bias */
.hero { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 24px; }
@media (max-width: 900px) { .hero { grid-template-columns: 1fr; } }
.hero-regime { background: linear-gradient(135deg, #1a2132 0%, #0f1623 100%);
  border: 1px solid var(--border-hi); border-radius: 14px; padding: 24px;
  position: relative; overflow: hidden; }
.hero-regime::before { content: ''; position: absolute; top: 0; right: 0;
  width: 280px; height: 280px; background: radial-gradient(circle, rgba(91,156,254,0.08) 0%, transparent 70%); pointer-events: none; }
.hero-label { font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
  color: var(--text-dim); text-transform: uppercase; margin-bottom: 12px; }
.hero-regime h1 { font-size: 20px; line-height: 1.4; font-weight: 600;
  letter-spacing: -0.3px; color: var(--text); }
.hero-timestamp { font-size: 12px; color: var(--text-muted); margin-top: 14px;
  display: flex; align-items: center; gap: 8px; }

.bias-panel { background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px; display: flex; flex-direction: column;
  justify-content: space-between; }
.bias-counts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.bias-cell { text-align: center; padding: 10px 4px; border-radius: 8px; }
.bias-cell.bull { background: rgba(46,204,113,0.08); border: 1px solid rgba(46,204,113,0.2); }
.bias-cell.bear { background: rgba(255,90,95,0.08); border: 1px solid rgba(255,90,95,0.2); }
.bias-cell.neut { background: rgba(128,148,176,0.08); border: 1px solid rgba(128,148,176,0.2); }
.bias-cell .n { font-size: 32px; font-weight: 700; line-height: 1; letter-spacing: -1px; }
.bias-cell .lbl { font-size: 11px; color: var(--text-dim); margin-top: 4px;
  text-transform: uppercase; letter-spacing: 0.4px; }
.bias-cell.bull .n { color: var(--green); }
.bias-cell.bear .n { color: var(--red); }

/* Section headers */
.section { margin-bottom: 28px; }
.section-header { display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 14px; padding: 0 4px; }
.section-title { font-size: 15px; font-weight: 600; letter-spacing: -0.2px; }
.section-meta { font-size: 12px; color: var(--text-muted); }

/* TOP TRADES */
.trades-list { display: flex; flex-direction: column; gap: 10px; }
.trade { background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--accent); border-radius: 10px;
  padding: 14px 18px; display: flex; align-items: center; gap: 14px;
  transition: transform .12s, border-color .12s; }
.trade:hover { border-color: var(--border-hi); transform: translateX(2px); }
.trade-rank { font-size: 11px; font-weight: 700; color: var(--text-muted);
  min-width: 18px; }
.trade-body { flex: 1; font-size: 14px; line-height: 1.5; }

/* THEME HEATMAP */
.themes-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr));
  gap: 12px; }
.theme-card { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; }
.theme-name { font-size: 13px; font-weight: 600; text-transform: capitalize;
  margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }
.theme-bar { display: flex; height: 24px; border-radius: 6px; overflow: hidden;
  margin-bottom: 6px; background: var(--border); }
.theme-bar > div { display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; color: white; }
.theme-stats { font-size: 11px; color: var(--text-dim); }
.theme-assets { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.asset-chip { font-size: 10px; background: rgba(91,156,254,0.08);
  color: var(--accent); padding: 2px 7px; border-radius: 10px; font-weight: 500; }

/* THESIS CARDS */
.theses-list { display: flex; flex-direction: column; gap: 10px; }
.thesis { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden; }
.thesis-head { padding: 14px 18px; cursor: pointer; display: flex;
  align-items: center; gap: 12px; transition: background .12s; }
.thesis-head:hover { background: var(--surface-hi); }
.dir-badge { font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 4px;
  text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0; min-width: 66px; text-align: center; }
.dir-bullish { background: rgba(46,204,113,0.14); color: var(--green); }
.dir-bearish { background: rgba(255,90,95,0.14); color: var(--red); }
.dir-neutral { background: rgba(128,148,176,0.12); color: var(--text-dim); }
.dir-mixed { background: rgba(245,182,66,0.14); color: var(--yellow); }
.dir-watchful { background: rgba(166,121,240,0.14); color: var(--purple); }
.thesis-theme { font-size: 13px; font-weight: 600; text-transform: capitalize;
  min-width: 110px; }
.thesis-text { flex: 1; font-size: 13px; line-height: 1.5; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.thesis-conf { font-size: 12px; color: var(--text-dim); white-space: nowrap;
  display: flex; align-items: center; gap: 6px; }
.conf-bar { width: 36px; height: 4px; background: var(--border); border-radius: 2px;
  overflow: hidden; }
.conf-bar > div { height: 100%; background: var(--accent); }
.thesis-body { padding: 0 18px 16px 18px; font-size: 13px;
  border-top: 1px solid var(--border); max-height: 0; overflow: hidden;
  transition: max-height .25s; }
.thesis.open .thesis-body { max-height: 800px; padding-top: 14px; }
.thesis-meta { display: flex; gap: 18px; color: var(--text-dim); font-size: 12px;
  margin-bottom: 12px; flex-wrap: wrap; }
.thesis-meta b { color: var(--text); font-weight: 600; }
.thesis-section { margin-top: 10px; }
.thesis-section-label { font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
  color: var(--text-dim); text-transform: uppercase; margin-bottom: 4px; }
.thesis-list-item { padding: 4px 0; color: var(--text); font-size: 13px;
  line-height: 1.5; }
.thesis-list-item::before { content: '• '; color: var(--accent); }

/* RISKS */
.risks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px,1fr)); gap: 12px; }
.risk-card { background: rgba(255,90,95,0.04); border: 1px solid rgba(255,90,95,0.22);
  border-radius: 10px; padding: 14px 16px; position: relative; font-size: 13px;
  line-height: 1.55; }
.risk-card::before { content: '⚠'; position: absolute; top: 14px; left: 14px;
  color: var(--red); font-size: 16px; }
.risk-card { padding-left: 40px; }

/* EMPTY STATE */
.empty { text-align: center; padding: 60px 20px; }
.empty h2 { font-size: 18px; margin-bottom: 8px; color: var(--text); }
.empty p { color: var(--text-dim); font-size: 14px; }
.empty a { color: var(--accent); }

#loading { text-align: center; padding: 80px 20px; color: var(--text-dim); font-size: 14px; }

/* Mobile */
@media (max-width: 640px) {
  .container { padding: 16px 12px 60px; }
  .nav { padding: 12px 16px; }
  .nav-brand { font-size: 14px; }
  .hero-regime { padding: 18px; }
  .hero-regime h1 { font-size: 17px; }
  .thesis-head { flex-wrap: wrap; }
  .thesis-text { flex-basis: 100%; order: 10; -webkit-line-clamp: 3; }
}
</style>
</head>
<body>

<nav class="nav">
  <span class="nav-brand"><span class="dot"></span>Macro Positioning</span>
  <div class="nav-links">
    <a href="/positioning" class="nav-link active">Positioning</a>
    <a href="/dev" class="nav-link">Dev Status</a>
  </div>
</nav>

<div class="container">

<div id="loading">Loading positioning…</div>

<div id="empty" class="empty" style="display:none">
  <h2>No analysis yet</h2>
  <p>Run a pipeline to generate theses. Nothing in the DB to show.</p>
</div>

<div id="content" style="display:none">

  <!-- HERO: regime + bias -->
  <div class="hero">
    <div class="hero-regime">
      <div class="hero-label">Current Macro Regime</div>
      <h1 id="regime-text">—</h1>
      <div class="hero-timestamp">
        <span>⏱</span>
        <span id="generated-at">—</span>
        <span id="model-info"></span>
      </div>
    </div>
    <div class="bias-panel">
      <div class="hero-label">Directional Mix</div>
      <div class="bias-counts" id="bias-counts"></div>
    </div>
  </div>

  <!-- TOP TRADES -->
  <div class="section" id="trades-section" style="display:none">
    <div class="section-header">
      <div class="section-title">Top Trade Expressions</div>
      <div class="section-meta" id="trades-count"></div>
    </div>
    <div class="trades-list" id="trades-list"></div>
  </div>

  <!-- THEME HEATMAP -->
  <div class="section">
    <div class="section-header">
      <div class="section-title">Theme Direction Map</div>
      <div class="section-meta" id="themes-count"></div>
    </div>
    <div class="themes-grid" id="themes-grid"></div>
  </div>

  <!-- THESES -->
  <div class="section">
    <div class="section-header">
      <div class="section-title">Active Theses</div>
      <div class="section-meta" id="theses-count"></div>
    </div>
    <div class="theses-list" id="theses-list"></div>
  </div>

  <!-- RISKS -->
  <div class="section" id="risks-section" style="display:none">
    <div class="section-header">
      <div class="section-title">Risks to Watch</div>
      <div class="section-meta" id="risks-count"></div>
    </div>
    <div class="risks-grid" id="risks-grid"></div>
  </div>

</div>
</div>

<script>
async function load() {
  try {
    const [cmdR, memoR, brainR] = await Promise.all([
      fetch('/api/dashboard/command-center').then(r => r.json()),
      fetch('/memos/latest').then(r => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/dashboard/brain/stats').then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    render(cmdR, memoR, brainR);
  } catch (e) {
    document.getElementById('loading').textContent = 'Failed to load data: ' + e.message;
  }
}

function render(cmd, memo, brain) {
  document.getElementById('loading').style.display = 'none';
  if (!cmd || !cmd.has_data) {
    document.getElementById('empty').style.display = 'block';
    return;
  }
  document.getElementById('content').style.display = 'block';

  // Hero regime
  const regime = cmd.memo_summary || memo?.summary || 'No regime summary yet.';
  document.getElementById('regime-text').textContent = regime;
  if (cmd.generated_at) {
    const d = new Date(cmd.generated_at);
    document.getElementById('generated-at').textContent = d.toLocaleString();
  }
  if (brain?.total_calls) {
    document.getElementById('model-info').textContent =
      `· ${brain.total_calls} brain calls, ${brain.avg_latency_ms.toFixed(0)}ms avg`;
  }

  // Bias counts
  const bc = document.getElementById('bias-counts');
  bc.innerHTML = `
    <div class="bias-cell bull"><div class="n">${cmd.bullish_count||0}</div><div class="lbl">Bullish</div></div>
    <div class="bias-cell bear"><div class="n">${cmd.bearish_count||0}</div><div class="lbl">Bearish</div></div>
    <div class="bias-cell neut"><div class="n">${cmd.neutral_count||0}</div><div class="lbl">Mixed / Neutral</div></div>
  `;

  // Top trades (from suggested_positioning)
  const trades = cmd.suggested_positioning || [];
  if (trades.length) {
    document.getElementById('trades-section').style.display = 'block';
    document.getElementById('trades-count').textContent = `${trades.length} expression${trades.length>1?'s':''}`;
    const tl = document.getElementById('trades-list');
    trades.forEach((t, i) => {
      const div = document.createElement('div');
      div.className = 'trade';
      div.innerHTML = `<span class="trade-rank">#${i+1}</span><div class="trade-body">${escapeHtml(t)}</div>`;
      tl.appendChild(div);
    });
  }

  // Theme heatmap
  const tg = document.getElementById('themes-grid');
  const themes = cmd.theme_clusters || [];
  document.getElementById('themes-count').textContent = `${themes.length} theme${themes.length>1?'s':''}`;
  themes.forEach(c => {
    const total = c.bullish + c.bearish + c.neutral + c.mixed + c.watchful;
    const pct = n => total ? (n/total*100).toFixed(0) : 0;
    let bar = '';
    if (c.bullish) bar += `<div style="width:${pct(c.bullish)}%;background:var(--green)">${c.bullish}</div>`;
    if (c.bearish) bar += `<div style="width:${pct(c.bearish)}%;background:var(--red)">${c.bearish}</div>`;
    if (c.mixed) bar += `<div style="width:${pct(c.mixed)}%;background:var(--yellow)">${c.mixed}</div>`;
    if (c.watchful) bar += `<div style="width:${pct(c.watchful)}%;background:var(--purple)">${c.watchful}</div>`;
    if (c.neutral) bar += `<div style="width:${pct(c.neutral)}%;background:var(--text-muted)">${c.neutral}</div>`;
    const assetsHtml = (c.top_assets||[]).map(a => `<span class="asset-chip">${escapeHtml(a)}</span>`).join('');
    const card = document.createElement('div');
    card.className = 'theme-card';
    card.innerHTML = `
      <div class="theme-name"><span>${escapeHtml(c.theme)}</span>
        <span style="font-size:11px;color:var(--text-dim)">${(c.avg_confidence*100).toFixed(0)}%</span></div>
      <div class="theme-bar">${bar}</div>
      <div class="theme-stats">${total} thes${total===1?'is':'es'} · dominant: ${c.dominant_direction}</div>
      <div class="theme-assets">${assetsHtml}</div>`;
    tg.appendChild(card);
  });

  // Theses
  const theses = cmd.theses || [];
  document.getElementById('theses-count').textContent = `${theses.length} active`;
  const tl = document.getElementById('theses-list');
  theses.forEach((t, i) => {
    const conf = Math.round((t.confidence||0)*100);
    const positioning = (t.implied_positioning||[]).map(p => `<div class="thesis-list-item">${escapeHtml(p)}</div>`).join('');
    const catalysts = (t.catalysts||[]).map(c => `<div class="thesis-list-item">${escapeHtml(c)}</div>`).join('');
    const risks = (t.risks||[]).map(r => `<div class="thesis-list-item">${escapeHtml(r)}</div>`).join('');
    const assets = (t.assets||[]).map(a => `<span class="asset-chip">${escapeHtml(a)}</span>`).join(' ');

    const el = document.createElement('div');
    el.className = 'thesis';
    el.innerHTML = `
      <div class="thesis-head" data-idx="${i}">
        <span class="dir-badge dir-${t.direction}">${t.direction}</span>
        <span class="thesis-theme">${escapeHtml(t.theme)}</span>
        <span class="thesis-text">${escapeHtml(t.thesis)}</span>
        <span class="thesis-conf">
          <span class="conf-bar"><div style="width:${conf}%"></div></span>
          ${conf}%
        </span>
      </div>
      <div class="thesis-body">
        <div class="thesis-meta">
          <span><b>Horizon:</b> ${escapeHtml(t.horizon||'—')}</span>
          <span><b>Status:</b> ${escapeHtml(t.status||'active')}</span>
          ${t.run_count && t.run_count > 1 ? `<span><b>Reaffirmed:</b> ${t.run_count}×</span>` : ''}
        </div>
        ${assets ? `<div class="thesis-section"><div class="thesis-section-label">Affected Assets</div>${assets}</div>` : ''}
        ${positioning ? `<div class="thesis-section"><div class="thesis-section-label">Implied Positioning</div>${positioning}</div>` : ''}
        ${catalysts ? `<div class="thesis-section"><div class="thesis-section-label">Catalysts</div>${catalysts}</div>` : ''}
        ${risks ? `<div class="thesis-section"><div class="thesis-section-label">Risks</div>${risks}</div>` : ''}
      </div>`;
    el.querySelector('.thesis-head').addEventListener('click', () => el.classList.toggle('open'));
    tl.appendChild(el);
  });

  // Risks
  const risks = (memo?.risks_to_watch) || [];
  if (risks.length) {
    document.getElementById('risks-section').style.display = 'block';
    document.getElementById('risks-count').textContent = `${risks.length}`;
    const rg = document.getElementById('risks-grid');
    risks.forEach(r => {
      const div = document.createElement('div');
      div.className = 'risk-card';
      div.textContent = r;
      rg.appendChild(div);
    });
  }
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

load();
</script>
</body>
</html>
"""
