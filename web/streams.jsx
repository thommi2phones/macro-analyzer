// /streams — who's talking about what, across the live sources.
//
// Five sections:
//   S1 — Theme map (2D age × direction, bubble = share of attention)
//   S2 — Emerging concepts cards (novelty > 0.7 AND velocity > 0.4)
//   S3 — Source graph · echo ties (tier rings, co-citation threads)
//   S4 — Per-source feed (search + sort + DrillSheet)
//   S5 — Manual drops (latest /api/manual/inputs entries)

const { useState, useEffect, useRef, useCallback, useMemo } = React;

function _seed(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = Math.imul(31, h) + str.charCodeAt(i) | 0;
  return ((h >>> 0) % 1000) / 1000;
}

// ---------------------------------------------------------------------------
// S1 — Theme map
// ---------------------------------------------------------------------------

const _DIR_FILTERS = ["all", "bullish", "bearish", "mixed"];
const _DIR_COLOR = {
  bullish: "var(--green)",
  bearish: "var(--red)",
  mixed:   "var(--amber)",
};

function ThemeMap({ themeMap, onThemeClick }) {
  const [weekIndex, setWeekIndex] = useState(3);
  const [playing, setPlaying]     = useState(false);
  const [dirFilter, setDirFilter] = useState("all");
  const timerRef = useRef(null);

  const W = 1080, H = 520;
  const PAD = { top: 56, right: 56, bottom: 64, left: 132 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top  - PAD.bottom;

  const visibleThemes = useMemo(() => {
    if (dirFilter === "all") return themeMap;
    return themeMap.filter(t => t.direction === dirFilter);
  }, [themeMap, dirFilter]);

  // Bubble radius first, so layout can use it for collision avoidance.
  const maxMentions = Math.max(1, ...themeMap.flatMap(t => t.mentions_by_week || [0]));
  const totalNow = (themeMap.reduce((a, t) => a + (t.mentions_by_week?.[weekIndex] || 0), 0)) || 1;
  const bubbleR = t => {
    const m = t.mentions_by_week?.[weekIndex] || 0;
    return 20 + (m / maxMentions) * 30;
  };

  // Deterministic layout: within each direction band, sort by lifecycle and
  // spread evenly on Y. Then nudge X to enforce minimum spacing so adjacent
  // bubbles don't horizontally pile up in the FRESH zone.
  const layout = useMemo(() => {
    const BAND_RANGES = {
      bullish: [0.06, 0.36],
      mixed:   [0.42, 0.58],
      bearish: [0.64, 0.94],
    };
    const out = {};
    const byDir = { bullish: [], mixed: [], bearish: [] };
    visibleThemes.forEach(t => (byDir[t.direction] || byDir.mixed).push(t));
    Object.entries(byDir).forEach(([dir, arr]) => {
      const [t0, t1] = BAND_RANGES[dir] || BAND_RANGES.mixed;
      const sorted = arr.slice().sort((a, b) => a.lifecycle - b.lifecycle);
      // First pass — assign raw x from lifecycle + tiny jitter, y from band index.
      const items = sorted.map((t, i) => {
        const frac = sorted.length === 1 ? 0.5 : i / (sorted.length - 1);
        const yFrac = t0 + frac * (t1 - t0);
        const xJitter = (_seed(t.id + ":x") - 0.5) * 0.03;
        return {
          theme: t,
          x: PAD.left + Math.max(0, Math.min(1, t.lifecycle + xJitter)) * innerW,
          y: PAD.top + yFrac * innerH,
          bandIdx: i,
          bandCount: sorted.length,
          r: bubbleR(t),
        };
      });
      // Second pass — enforce min horizontal spacing between adjacent bubbles
      // (in band-sorted order). Generous gap so bubbles + their labels never
      // visually collide.
      const minGap = 36;
      for (let i = 1; i < items.length; i++) {
        const prev = items[i - 1];
        const cur  = items[i];
        const required = prev.r + cur.r + minGap;
        const actual   = cur.x - prev.x;
        if (actual < required) cur.x = prev.x + required;
      }
      // Clamp so right-edge bubbles stay inside the chart.
      const rightLimit = PAD.left + innerW - 8;
      for (let i = items.length - 1; i >= 0; i--) {
        if (items[i].x + items[i].r > rightLimit) {
          items[i].x = rightLimit - items[i].r;
          if (i > 0) {
            const required = items[i - 1].r + items[i].r + minGap;
            if (items[i].x - items[i - 1].x < required) {
              items[i - 1].x = items[i].x - required;
            }
          }
        }
      }
      items.forEach(it => {
        out[it.theme.id] = { x: it.x, y: it.y, bandIdx: it.bandIdx, bandCount: it.bandCount };
      });
    });
    return out;
  }, [visibleThemes, innerW, innerH, weekIndex, maxMentions]);
  const sharePct = t => {
    const m = t.mentions_by_week?.[weekIndex] || 0;
    return Math.round((m / totalNow) * 100);
  };

  // Threads between themes sharing ≥1 source (NOW frame only)
  const overlapThreads = () => {
    const threads = [];
    for (let i = 0; i < visibleThemes.length; i++) {
      for (let j = i + 1; j < visibleThemes.length; j++) {
        const a = visibleThemes[i], b = visibleThemes[j];
        const shared = (a.sources || []).filter(s => (b.sources || []).includes(s));
        if (shared.length > 0) {
          const pa = layout[a.id], pb = layout[b.id];
          if (!pa || !pb) continue;
          threads.push({
            x1: pa.x, y1: pa.y, x2: pb.x, y2: pb.y,
            shared: shared.length,
          });
        }
      }
    }
    return threads;
  };

  const handlePlay = useCallback(() => {
    if (playing) {
      clearInterval(timerRef.current);
      setPlaying(false);
      return;
    }
    setWeekIndex(0);
    setPlaying(true);
    let wi = 0;
    timerRef.current = setInterval(() => {
      wi += 1;
      setWeekIndex(wi);
      if (wi >= 3) { clearInterval(timerRef.current); setPlaying(false); }
    }, 800);
  }, [playing]);

  useEffect(() => () => clearInterval(timerRef.current), []);

  if (!themeMap || themeMap.length === 0) {
    return <div className="theme-map-empty mono muted">no recurring themes mapped yet</div>;
  }

  const threads = weekIndex === 3 ? overlapThreads() : [];

  return (
    <div className="tm-wrap">
      {/* Header row — subtitle + direction filter */}
      <div className="tm-header-row">
        <div className="tm-subtitle mono muted small">
          2D — age × direction · bubble size = share of attention
        </div>
        <div className="tm-dir-filter mono small">
          <span className="muted" style={{ marginRight: 8 }}>dir</span>
          {_DIR_FILTERS.map(d => (
            <button
              key={d}
              className={`filter-pill ${dirFilter === d ? "on" : ""}`}
              onClick={() => setDirFilter(d)}
            >{d}</button>
          ))}
        </div>
      </div>

      {/* Replay + scrubber */}
      <div className="tm-scrub-row">
        <button
          className={`btn-mini tm-play ${playing ? "active" : ""}`}
          onClick={handlePlay}
        >
          {playing ? "⏸ PAUSE" : "▶ REPLAY"}
        </button>
        <div className="tm-scrub-track">
          <span className="tm-scrub-label-left mono small muted">−4W</span>
          <input
            type="range"
            className="tm-scrubber"
            min={0} max={3} step={1}
            value={weekIndex}
            onChange={e => { clearInterval(timerRef.current); setPlaying(false); setWeekIndex(+e.target.value); }}
          />
          <span className="tm-scrub-label-mid mono small muted">NARRATIVE DRIFT</span>
          <span className="tm-scrub-label-right mono small muted">NOW</span>
        </div>
        <div className="tm-now-pill mono small">
          <div className="tm-now-label">NOW</div>
          <div className="tm-now-live muted">LIVE</div>
        </div>
      </div>
      <div className="tm-hint muted small">
        scrub or press play — emerging themes enter at the left and drift right as they age; the gold ring fades as a narrative matures.
      </div>

      {/* Chart + sidebar */}
      <div className="tm-chart-wrap">
        <svg
          className="tm-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Theme lifecycle scatter map"
        >
          {/* Outer chart frame */}
          <rect x={PAD.left} y={PAD.top} width={innerW} height={innerH}
                fill="none" stroke="var(--line)" strokeWidth="1" opacity="0.5" />

          {/* Quadrant dashed midlines */}
          <line x1={PAD.left} y1={PAD.top + innerH/2} x2={W - PAD.right} y2={PAD.top + innerH/2}
                stroke="var(--line)" strokeDasharray="3,4" opacity="0.35" />
          <line x1={PAD.left + innerW/2} y1={PAD.top} x2={PAD.left + innerW/2} y2={PAD.top + innerH}
                stroke="var(--line)" strokeDasharray="3,4" opacity="0.25" />

          {/* Quadrant labels */}
          <text x={PAD.left + 6} y={PAD.top + 12} fontSize="9" fill="var(--text-mute-3)"
                fontFamily="var(--mono)" letterSpacing="0.14em">↖ FRESH · BULL</text>
          <text x={W - PAD.right - 6} y={PAD.top + 12} fontSize="9" fill="var(--text-mute-3)"
                fontFamily="var(--mono)" letterSpacing="0.14em" textAnchor="end">EXTENDED · BULL ↗</text>
          <text x={PAD.left + 6} y={H - PAD.bottom - 6} fontSize="9" fill="var(--text-mute-3)"
                fontFamily="var(--mono)" letterSpacing="0.14em">↙ FRESH · BEAR</text>
          <text x={W - PAD.right - 6} y={H - PAD.bottom - 6} fontSize="9" fill="var(--text-mute-3)"
                fontFamily="var(--mono)" letterSpacing="0.14em" textAnchor="end">FADING · BEAR ↘</text>

          {/* Y axis labels (outside chart, left) */}
          <text x={PAD.left - 14} y={PAD.top + innerH * 0.18} fontSize="10"
                fill="var(--green)" fontFamily="var(--mono)" letterSpacing="0.16em"
                textAnchor="end">BULLISH ↑</text>
          <text x={PAD.left - 14} y={PAD.top + innerH * 0.50 + 3} fontSize="10"
                fill="var(--amber)" fontFamily="var(--mono)" letterSpacing="0.16em"
                textAnchor="end">MIXED</text>
          <text x={PAD.left - 14} y={PAD.top + innerH * 0.84} fontSize="10"
                fill="var(--red)" fontFamily="var(--mono)" letterSpacing="0.16em"
                textAnchor="end">↓ BEARISH</text>

          {/* Y axis title (rotated) */}
          <text x={22} y={PAD.top + innerH/2} fontSize="8.5"
                fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.22em"
                textAnchor="middle"
                transform={`rotate(-90, 22, ${PAD.top + innerH/2})`}>
            DIRECTION · consensus × tilt
          </text>

          {/* X axis labels (outside chart, bottom) */}
          <text x={PAD.left} y={H - 22} fontSize="10" fill="var(--accent)"
                fontFamily="var(--mono)" letterSpacing="0.16em">← EMERGING</text>
          <text x={W - PAD.right} y={H - 22} fontSize="10" fill="var(--text-mute-2)"
                fontFamily="var(--mono)" letterSpacing="0.16em" textAnchor="end">FADING →</text>
          <text x={PAD.left + innerW/2} y={H - 6} fontSize="8.5"
                fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.22em"
                textAnchor="middle">NARRATIVE LIFECYCLE · first-seen × velocity</text>

          {/* Co-citation threads */}
          {threads.map((t, i) => (
            <line key={i}
              x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
              stroke="var(--accent)" strokeWidth={0.8 + t.shared * 0.3}
              strokeDasharray="3,4" opacity="0.22"
            />
          ))}

          {/* Bubbles */}
          {visibleThemes.map(theme => {
            const p = layout[theme.id];
            if (!p) return null;
            const cx = p.x, cy = p.y;
            const r = bubbleR(theme);
            const isEmerging = theme.age_days < 14;
            const color = _DIR_COLOR[theme.direction] || "var(--amber)";
            const m = theme.mentions_by_week?.[weekIndex] || 0;
            const pct = sharePct(theme);

            // Alternate label position by band index to guarantee vertical
            // separation when bubbles in the same band are close horizontally.
            // Even index = above, odd = below. Top-of-band always goes below
            // and bottom-of-band always goes above (to avoid chart clipping).
            const atTop = p.bandIdx === 0;
            const atBottom = p.bandIdx === p.bandCount - 1 && p.bandCount > 1;
            let labelAbove;
            if (atTop) labelAbove = false;
            else if (atBottom) labelAbove = true;
            else labelAbove = p.bandIdx % 2 === 0;
            // Safety: don't push label off-chart.
            if (labelAbove && cy - r - 32 < PAD.top + 6) labelAbove = false;
            if (!labelAbove && cy + r + 34 > H - PAD.bottom - 6) labelAbove = true;
            const labelY = labelAbove ? cy - r - 20 : cy + r + 20;
            const metaY  = labelAbove ? cy - r - 6  : cy + r + 34;

            return (
              <g key={theme.id} className="tm-bubble-group"
                style={{ cursor: "pointer" }}
                onClick={() => onThemeClick && onThemeClick(theme)}>
                {isEmerging && (
                  <circle cx={cx} cy={cy} r={r + 6}
                    fill="none" stroke="var(--accent)" strokeWidth="1.5"
                    strokeDasharray="4,3" opacity="0.85" />
                )}
                {/* Invisible larger hit target so the label area is clickable too */}
                <circle cx={cx} cy={cy} r={r + 18}
                  fill="transparent" pointerEvents="all" />
                <circle cx={cx} cy={cy} r={r}
                  fill={color} opacity="0.14" pointerEvents="all" />
                <circle cx={cx} cy={cy} r={r}
                  fill="none" stroke={color} strokeWidth="1.5" opacity="0.95"
                  pointerEvents="all" />
                {/* Theme label */}
                <text x={cx} y={labelY} fontSize="13" textAnchor="middle"
                  fill="var(--text)" fontFamily="var(--serif)" fontStyle="italic"
                  paintOrder="stroke" stroke="var(--bg-card-2, #1a1a1a)" strokeWidth="4"
                  strokeLinejoin="round">
                  {theme.label}
                </text>
                {/* Items + share of attention */}
                <text x={cx} y={metaY} fontSize="10" textAnchor="middle"
                  fill={color} fontFamily="var(--mono)"
                  paintOrder="stroke" stroke="var(--bg-card-2, #1a1a1a)" strokeWidth="3.5"
                  strokeLinejoin="round">
                  {m} items · {pct}%
                </text>
              </g>
            );
          })}
        </svg>

        {/* Right sidebar */}
        <aside className="tm-sidebar">
          <div className="tm-sb-head mono">HOVER · CLICK A BUBBLE</div>
          <div className="tm-sb-meta mono small muted">
            {visibleThemes.length} themes mapped · drag-to-explore
          </div>
          <div className="tm-sb-legend">
            <div className="tm-leg-row"><span className="leg-dot" style={{ background: "var(--green)" }} />
              <span className="mono small"><b>bullish</b> · upper half</span></div>
            <div className="tm-leg-row"><span className="leg-dot" style={{ background: "var(--red)" }} />
              <span className="mono small"><b>bearish</b> · lower half</span></div>
            <div className="tm-leg-row"><span className="leg-dot" style={{ background: "var(--amber)" }} />
              <span className="mono small"><b>mixed</b> · middle band</span></div>
            <div className="tm-leg-row"><span className="leg-ring" />
              <span className="mono small">dashed ring = emerging</span></div>
            <div className="tm-leg-row tm-leg-thread">
              <span className="leg-thread" />
              <span className="mono small">threads connect themes sharing a source</span>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Theme detail panel (S1 drilldown content)
// ---------------------------------------------------------------------------

function ThemeDetailPanel({ t }) {
  const weeks = t.mentions_by_week || [];
  const total = weeks.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...weeks);
  const weekLabels = ["−4w", "−3w", "−2w", "NOW"];
  const dirColor = t.direction === "bullish" ? "var(--green)"
                 : t.direction === "bearish" ? "var(--red)" : "var(--amber)";

  return (
    <div className="source-detail">
      <div className="detail-section">
        <div className="detail-section-head mono">DIRECTION</div>
        <div className="mono" style={{ color: dirColor, fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase" }}>
          → {t.direction}
        </div>
      </div>

      <div className="detail-section">
        <div className="detail-section-head mono">MENTIONS · LAST 4 WEEKS</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 80, padding: "8px 4px 4px" }}>
          {weeks.map((m, i) => (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              <div className="mono small" style={{ color: "var(--text-mute)" }}>{m}</div>
              <div style={{
                width: "100%",
                height: `${(m / max) * 60 + 4}px`,
                background: dirColor,
                opacity: i === 3 ? 0.85 : 0.45,
              }} />
              <div className="mono" style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-mute-3)" }}>
                {weekLabels[i]}
              </div>
            </div>
          ))}
        </div>
        <div className="mono small muted" style={{ marginTop: 4 }}>
          {total} mentions total · {weeks[3] || 0} this week
        </div>
      </div>

      <div className="detail-row">
        <span className="detail-label mono">novelty</span>
        <span className="detail-val">{(t.novelty || 0).toFixed(2)}</span>
      </div>
      <div className="detail-row">
        <span className="detail-label mono">velocity</span>
        <span className="detail-val">{(t.velocity || 0).toFixed(2)}</span>
      </div>
      <div className="detail-row">
        <span className="detail-label mono">lifecycle</span>
        <span className="detail-val">
          {(t.lifecycle || 0) < 0.33 ? "emerging" : (t.lifecycle || 0) < 0.66 ? "extended" : "fading"}
          {" · "}{(t.lifecycle || 0).toFixed(2)}
        </span>
      </div>
      <div className="detail-row">
        <span className="detail-label mono">age</span>
        <span className="detail-val">{t.age_days || 0} days</span>
      </div>

      <div className="detail-section">
        <div className="detail-section-head mono">SOURCES CITING ({(t.sources || []).length})</div>
        <div className="cc-sources" style={{ marginTop: 6 }}>
          {(t.sources || []).map(s => (
            <span key={s} className="cc-src-chip">{s}</span>
          ))}
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// S2 — Emerging concepts cards (unchanged content; header polish in parent)
// ---------------------------------------------------------------------------

function ConceptsCards({ concepts }) {
  const NOVELTY_MIN = 0.7;
  const VELOCITY_MIN = 0.4;
  const filtered = (concepts || []).filter(
    c => (c.novelty || 0) > NOVELTY_MIN && (c.velocity || 0) > VELOCITY_MIN
  );
  if (filtered.length === 0) {
    return <div className="empty-state mono muted" style={{ padding: "1.5rem" }}>no high-novelty themes this week</div>;
  }
  return (
    <div className="concept-cards-grid">
      {filtered.map(c => (
        <article key={c.id} className="concept-card">
          <div className="cc-head">
            <div className="cc-head-left">
              <span className="cc-new-badge mono">NEW</span>
              <span className="cc-age mono muted small">· {c.age_days}D AGO</span>
            </div>
            <span className="cc-novelty mono small muted">
              NOVELTY <span className="cc-novelty-val">{Math.round(c.novelty * 100)}</span>
            </span>
          </div>
          <div className="cc-title">{c.title}</div>
          <p className="cc-synopsis muted small">{c.synopsis}</p>
          <div className="cc-stats">
            <div className="cc-stat">
              <div className="cc-stat-val mono pos">+{c.velocity.toFixed(2)}</div>
              <div className="cc-stat-lbl mono">VELOCITY</div>
            </div>
            <div className="cc-stat">
              <div className="cc-stat-val mono">{c.items_count}</div>
              <div className="cc-stat-lbl mono">ITEMS</div>
            </div>
            <div className="cc-stat">
              <div className="cc-stat-val mono">{c.sources_count}</div>
              <div className="cc-stat-lbl mono">SOURCES</div>
            </div>
          </div>
          <div className="cc-sources">
            {(c.source_names || []).map(n => <span key={n} className="cc-src-chip">{n}</span>)}
          </div>
        </article>
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------------
// S3 — Source graph · echo ties
// ---------------------------------------------------------------------------

// Cluster definitions: 3×3 thematic grid across the macro landscape.
// market_focus on each node is tokenised (comma/space/_/-/​/) and matched
// against `focuses` by exact token equality.
const _CLUSTERS = [
  // Top row
  { key: "macro",    label: "MACRO · RATES",        cx: 0.16, cy: 0.16, focuses: ["macro", "rates", "fed"] },
  { key: "equities", label: "EQUITIES · FACTORS",   cx: 0.50, cy: 0.16, focuses: ["equities", "factor", "factors", "sector", "sectors"] },
  { key: "tech",     label: "TECH · AI",            cx: 0.84, cy: 0.16, focuses: ["tech", "ai", "semis", "semiconductor"] },
  // Middle row
  { key: "energy",   label: "ENERGY · COMMODITIES", cx: 0.16, cy: 0.50, focuses: ["energy", "commodities", "oil", "uranium", "metals"] },
  { key: "realassets", label: "REAL ASSETS · GOLD", cx: 0.50, cy: 0.50, focuses: ["gold", "assets"] },
  { key: "crypto",   label: "CRYPTO · DIGITAL",     cx: 0.84, cy: 0.50, focuses: ["crypto", "btc", "eth", "digital", "onchain"] },
  // Bottom row
  { key: "credit",   label: "CREDIT · FIXED INCOME", cx: 0.16, cy: 0.84, focuses: ["credit", "fi", "income", "spreads", "bond"] },
  { key: "fx",       label: "FX · GEOPOLITICS",     cx: 0.50, cy: 0.84, focuses: ["fx", "geopolitics", "currency", "em", "dxy"] },
  { key: "social",   label: "NEWS · SOCIAL",        cx: 0.84, cy: 0.84, focuses: ["social", "news", "media", "twitter", "rss"] },
];

function _clusterFor(node) {
  const tokens = (node.market_focus || "").toLowerCase().split(/[,\s_/-]+/).filter(Boolean);
  for (const c of _CLUSTERS) {
    if (c.focuses.some(x => tokens.includes(x))) return c.key;
  }
  return "macro";
}

// Tier color ramp: green = best (T0 top trust → T1 primary) down through
// amber/orange/red as tier rank gets weaker.
function _tierColor(tier) {
  return tier === 0 ? "#7be0a4"                       // bright green — trusted KOL
       : tier === 1 ? "var(--green, #50b478)"         // green — primary, high-weight
       : tier === 2 ? "var(--amber, #d6b15a)"         // amber — trusted research
       : tier === 3 ? "#e08850"                       // orange — monitored
       :              "#c66060";                       // red — noise floor (T4)
}

function _tierRadius(tier, weight) {
  const base = tier === 0 ? 32 : tier === 1 ? 28 : tier === 2 ? 24 : tier === 3 ? 21 : 18;
  return Math.max(16, weight * base);
}

function SourceGraph({ sourceGraph, onNodeClick }) {
  const [hovered, setHovered] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const [tierOn, setTierOn] = useState({ 0: true, 1: true, 2: true, 3: true, 4: true });

  const allNodes = (sourceGraph && sourceGraph.nodes) || [];
  const allLinks = (sourceGraph && sourceGraph.links) || [];

  const W = 960, H = 720;
  const PAD = { top: 72, right: 48, bottom: 48, left: 48 };

  if (allNodes.length === 0) {
    return <div className="empty-state mono muted" style={{ padding: "1.5rem" }}>no sources connected yet</div>;
  }

  const nodes = allNodes.filter(n => tierOn[n.tier]);
  const visibleIds = new Set(nodes.map(n => n.id));
  const links = allLinks.filter(l => visibleIds.has(l.source) && visibleIds.has(l.target));

  // Layout: position nodes within cluster circles
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top  - PAD.bottom;
  const pos = {};
  const byCluster = {};
  nodes.forEach(n => {
    const k = _clusterFor(n);
    (byCluster[k] ||= []).push(n);
  });
  // Track per-cluster spread radius so we can place the header above the top
  // node, not on top of it.
  const clusterRadius = {};
  for (const c of _CLUSTERS) {
    const list = byCluster[c.key] || [];
    const baseX = PAD.left + c.cx * innerW;
    const baseY = PAD.top  + c.cy * innerH;
    const count = list.length;
    // Tighter spread per cluster — with 9 cells in the grid each gets less real estate.
    const radius = count <= 1 ? 0 : 42 + count * 8;
    clusterRadius[c.key] = radius;
    list.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(count, 1) + _seed(n.id) * 0.5;
      pos[n.id] = {
        x: baseX + Math.cos(angle) * radius,
        y: baseY + Math.sin(angle) * radius,
      };
    });
  }

  const adjSet = (id) => {
    const s = new Set();
    links.forEach(l => { if (l.source === id) s.add(l.target); if (l.target === id) s.add(l.source); });
    return s;
  };
  const isLinkHighlighted = (l) => hovered && (l.source === hovered || l.target === hovered);

  return (
    <div className="sg-wrap">
      {/* Header row — subtitle + tier toggles */}
      <div className="sg-header-row">
        <div className="sg-subtitle mono muted small">
          bubble = source · ring = tier · thread thickness = echo strength
        </div>
        <div className="sg-tier-filter mono small">
          {[0,1,2,3,4].map(t => (
            <button
              key={t}
              className={`sg-tier-dot ${tierOn[t] ? "on" : ""}`}
              onClick={() => setTierOn(s => ({ ...s, [t]: !s[t] }))}
              title={`Toggle T${t}`}
            >
              <span className="sg-tier-ring" style={{ borderColor: _tierColor(t) }} />
              <span>T{t}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="sg-chart-wrap">
        <svg
          className="sg-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Source network graph"
        >
          {/* Cluster category labels — sit above the top of the cluster's
              spread radius + max node ring + breathing room. Empty clusters
              render as ghosts so the user can see *which* themes have no
              source coverage yet. */}
          {_CLUSTERS.map(c => {
            const list = byCluster[c.key] || [];
            const baseX = PAD.left + c.cx * innerW;
            const baseY = PAD.top  + c.cy * innerH;
            if (list.length === 0) {
              return (
                <g key={c.key} className="sg-ghost-cluster" opacity="0.42">
                  <circle cx={baseX} cy={baseY} r="36"
                    fill="none" stroke="var(--text-mute-3)" strokeWidth="1"
                    strokeDasharray="3,4" />
                  <text x={baseX} y={baseY - 50} fontSize="10.5"
                    fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.22em"
                    textAnchor="middle">
                    {c.label}
                  </text>
                  <text x={baseX} y={baseY + 4} fontSize="9"
                    fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.16em"
                    textAnchor="middle">
                    NO COVERAGE
                  </text>
                </g>
              );
            }
            const maxR  = Math.max(...list.map(n => _tierRadius(n.tier, n.weight)));
            const labelY = baseY - (clusterRadius[c.key] || 0) - maxR - 14;
            return (
              <text key={c.key} x={baseX} y={labelY} fontSize="10.5"
                fill="var(--text-mute-2)" fontFamily="var(--mono)" letterSpacing="0.22em"
                textAnchor="middle" opacity="0.9">
                {c.label}
              </text>
            );
          })}

          {/* Echo-tie threads */}
          {links.map((l, i) => {
            const a = pos[l.source], b = pos[l.target];
            if (!a || !b) return null;
            const highlighted = isLinkHighlighted(l);
            const dimmed = hovered && !highlighted;
            return (
              <line key={i}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                className="sg-link"
                stroke={highlighted ? "var(--accent)" : _tierColor(2)}
                strokeWidth={l.strength * 2.4}
                opacity={dimmed ? 0.06 : (highlighted ? 0.9 : l.strength * 0.55)}
              />
            );
          })}

          {/* Nodes */}
          {nodes.map(n => {
            const p = pos[n.id];
            if (!p) return null;
            const r = _tierRadius(n.tier, n.weight);
            const color = _tierColor(n.tier);
            const isDashed = n.tier === 4;
            const adj = hovered ? adjSet(hovered) : new Set();
            const dimmed = hovered && hovered !== n.id && !adj.has(n.id);
            const labelText = n.name.length > 20 ? n.name.slice(0, 19) + "…" : n.name;

            return (
              <g key={n.id}
                className="sg-node"
                style={{ cursor: "pointer", opacity: dimmed ? 0.3 : 1 }}
                onMouseEnter={() => { setHovered(n.id); setTooltip({ n, px: p.x, py: p.y }); }}
                onMouseLeave={() => { setHovered(null); setTooltip(null); }}
                onClick={() => onNodeClick && onNodeClick(n)}
              >
                <circle cx={p.x} cy={p.y} r={r}
                  fill={color} opacity={n.tier === 0 ? 0.18 : 0.12} />
                <circle cx={p.x} cy={p.y} r={r}
                  fill="none" stroke={color}
                  strokeWidth={n.tier === 0 ? 3 : n.tier === 1 ? 2.4 : n.tier === 2 ? 2 : 1.6}
                  strokeDasharray={isDashed ? "4,3" : "none"}
                  opacity="0.95"
                  style={n.tier === 0 ? { filter: `drop-shadow(0 0 4px ${color})` } : undefined} />
                {/* Tier label inside the ring */}
                <text x={p.x} y={p.y + 3} fontSize="11" textAnchor="middle"
                  fill={color} fontFamily="var(--mono)" letterSpacing="0.12em"
                  fontWeight="600" opacity="0.95">
                  T{n.tier}
                </text>
                {/* Source name BELOW the ring with halo */}
                <text x={p.x} y={p.y + r + 14} fontSize="11" textAnchor="middle"
                  fill="var(--text)" fontFamily="var(--mono)"
                  paintOrder="stroke" stroke="var(--bg-card-2, #1a1a1a)" strokeWidth="3.5"
                  strokeLinejoin="round">
                  {labelText}
                </text>
                {/* Weight further below */}
                <text x={p.x} y={p.y + r + 27} fontSize="9" textAnchor="middle"
                  fill="var(--text-mute-2)" fontFamily="var(--mono)"
                  paintOrder="stroke" stroke="var(--bg-card-2, #1a1a1a)" strokeWidth="3"
                  strokeLinejoin="round">
                  w {(n.weight || 0).toFixed(2)}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Right sidebar */}
        <aside className="sg-sidebar">
          <div className="sg-sb-head mono">HOVER A BUBBLE</div>
          <div className="sg-sb-meta mono small muted">
            {nodes.length} sources · {links.length} echo ties
          </div>
          <div className="sg-sb-legend">
            <div className="sg-leg-row">
              <span className="sg-leg-ring" style={{ borderColor: _tierColor(0), boxShadow: `0 0 6px ${_tierColor(0)}66` }} />
              <span className="mono small"><b>T0</b> · trusted KOL</span>
            </div>
            <div className="sg-leg-row">
              <span className="sg-leg-ring" style={{ borderColor: _tierColor(1) }} />
              <span className="mono small"><b>T1</b> · primary, high-weight</span>
            </div>
            <div className="sg-leg-row">
              <span className="sg-leg-ring" style={{ borderColor: _tierColor(2) }} />
              <span className="mono small"><b>T2</b> · trusted research</span>
            </div>
            <div className="sg-leg-row">
              <span className="sg-leg-ring" style={{ borderColor: _tierColor(3) }} />
              <span className="mono small"><b>T3</b> · monitored</span>
            </div>
            <div className="sg-leg-row">
              <span className="sg-leg-ring" style={{ borderColor: _tierColor(4), borderStyle: "dashed" }} />
              <span className="mono small"><b>T4</b> · noise floor</span>
            </div>
            <div className="sg-leg-row sg-leg-thread-row">
              <span className="sg-leg-thread" />
              <span className="mono small">thread = recurring co-citation</span>
            </div>
          </div>
        </aside>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div className="sg-tooltip" style={{
          left: Math.min(tooltip.px + 14, W - 140) + "px",
          top:  Math.max(tooltip.py - 40, 8) + "px",
        }}>
          <div className="sg-tt-name">{tooltip.n.name}</div>
          <div className="mono small muted">T{tooltip.n.tier} · w {tooltip.n.weight.toFixed(2)}</div>
          <div className="mono small muted">{tooltip.n.market_focus}</div>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// S5 — Manual drops (KOL contributions captured via /04 inbox)
// ---------------------------------------------------------------------------

function ManualDrops() {
  const [drops, setDrops]   = useState(null);
  const [error, setError]   = useState(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/manual/inputs")
      .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
      .then(d => { if (alive) setDrops(d.inputs || d || []); })
      .catch(e => { if (alive) setError(String(e.message || e)); });
    return () => { alive = false; };
  }, []);

  if (error) {
    return <div className="empty-state mono muted" style={{ padding: "1rem" }}>
      manual feed unavailable · {error}
    </div>;
  }
  if (drops === null) {
    return <div className="empty-state mono muted" style={{ padding: "1rem" }}>loading recent drops…</div>;
  }
  if (drops.length === 0) {
    return <div className="empty-state mono muted" style={{ padding: "1rem" }}>
      no manual drops yet · capture one at <a href="#/04 inbox">/04 inbox</a>
    </div>;
  }

  const recent = drops.slice(0, 12);

  const sideClass = s => (s === "long" || s === "bull" || s === "bullish") ? "pos"
                      : (s === "short" || s === "bear" || s === "bearish") ? "neg"
                      : "";

  return (
    <div className="manual-drops-grid">
      {recent.map(d => {
        const meta = d.user_metadata || d.metadata || {};
        const author = d.author_display || d.author_id || meta.author || "—";
        const channel = d.channel || meta.channel || "";
        const ticker = (meta.ticker || d.ticker || "").toUpperCase();
        const side = (meta.side || d.side || "").toLowerCase();
        const conv = meta.conviction || d.conviction;
        const tf = meta.timeframe || d.timeframe;
        const note = meta.note || d.note || d.text || "";
        const ts = d.chart_date || d.created_at || d.timestamp || "";
        const pending = (d.tags_json && d.tags_json.pending_vision) || d.pending_vision;

        return (
          <article key={d.id || d.document_id || (author + ts)} className="manual-drop-card">
            <div className="md-head">
              <div className="md-author-wrap">
                <span className="md-author">{author}</span>
                {channel && <span className="md-channel mono small muted">· {channel}</span>}
              </div>
              <div className="md-time mono small muted">{ts}</div>
            </div>
            <div className="md-row">
              {ticker && <span className="md-ticker mono">{ticker}</span>}
              {side && <span className={`md-side mono small ${sideClass(side)}`}>{side}</span>}
              {tf && <span className="md-tf mono small muted">{tf}</span>}
              {conv != null && (
                <span className="md-conv mono small" title="conviction 1–5">
                  conv {conv}/5
                </span>
              )}
              {pending && <span className="md-pending mono small">⏳ vision pending</span>}
            </div>
            {note && <p className="md-note small">{note}</p>}
          </article>
        );
      })}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Main Streams component
// ---------------------------------------------------------------------------

function Streams() {
  const D = window.MA_DATA;
  // Live payload (themeMap/concepts/sourceGraph) comes from desk_data via
  // /api/desk under the `streams` key — see dashboard/streams_builders.py.
  // data.mock.js still provides bySource (S4) and asOf/topVoices for the
  // header. desk_data omits the live `streams` key entirely when the DB
  // has no signals/authors yet, so dev-mode falls through to the mock's
  // streams block (S1/S2/S3 included) per the Object.assign merge in
  // data.mock.js.
  const s = D.streams || { topVoices: [], bySource: [], summary: "" };

  const [openSrc, setOpenSrc]         = useState(null);
  const [openTheme, setOpenTheme]     = useState(null);
  const [themeFilter, setThemeFilter] = useState("ALL");
  const [sortBy, setSortBy]           = useState("weight");
  const [srcQ, setSrcQ]               = useState("");
  const [openFeedSrc, setOpenFeedSrc] = useState(null);

  const allThemes = Array.from(new Set(
    (s.bySource || []).flatMap(x => x.themes || [])
  )).sort();

  let sources = (s.bySource || []).slice();
  if (themeFilter !== "ALL") sources = sources.filter(x => (x.themes || []).includes(themeFilter));
  if (srcQ.trim()) {
    const q = srcQ.toLowerCase();
    sources = sources.filter(x =>
      x.name.toLowerCase().includes(q) ||
      (x.kind || "").toLowerCase().includes(q) ||
      (x.themes || []).some(t => t.toLowerCase().includes(q))
    );
  }
  sources.sort((a, b) => {
    if (sortBy === "weight")    return (b.weight || 0) - (a.weight || 0);
    if (sortBy === "attrib")    return (b.attrib30d || 0) - (a.attrib30d || 0);
    if (sortBy === "items")     return (b.items7d || 0) - (a.items7d || 0);
    if (sortBy === "freshness") {
      const order = { fresh: 0, "1d": 1, stale: 2 };
      return (order[a.freshness] ?? 3) - (order[b.freshness] ?? 3);
    }
    return 0;
  });

  return (
    <div className="streams-view">

      {/* ── S1 Theme map ────────────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S1</span>
            <span>Theme map</span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 6, paddingBottom: 14 }}>
          <ThemeMap themeMap={s.themeMap || []} onThemeClick={t => setOpenTheme(t)} />
        </div>
      </section>

      {/* ── S2 Emerging concepts ────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S2</span>
            <span>Emerging concepts</span>
            <span className="block-sub">new this week · high velocity · low item count</span>
          </div>
          <div className="cc-header-criteria mono small muted">
            novelty &gt; 0.7 · velocity &gt; 0.4
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 14 }}>
          <ConceptsCards concepts={s.concepts || []} />
        </div>
      </section>

      {/* ── S3 Source graph ─────────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S3</span>
            <span>Source graph · echo ties</span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 6, paddingBottom: 14 }}>
          <SourceGraph
            sourceGraph={s.sourceGraph || { nodes: [], links: [] }}
            onNodeClick={n => setOpenSrc(n)}
          />
        </div>
      </section>

      {/* ── S4 Per-source feed ──────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S4</span>
            <span>Per-source feed</span>
            <span className="block-sub">
              {sources.length} of {(s.bySource || []).length} · sorted by {sortBy}
              {srcQ.trim() ? ` · filtered "${srcQ}"` : ""}
            </span>
          </div>
          <div className="block-actions">
            <input className="src-search" placeholder="search sources…"
              value={srcQ} onChange={e => setSrcQ(e.target.value)} />
            <div className="filter-pill-row">
              <button className={`filter-pill ${themeFilter === "ALL" ? "on" : ""}`}
                onClick={() => setThemeFilter("ALL")}>ALL</button>
              {allThemes.map(t => (
                <button key={t} className={`filter-pill ${themeFilter === t ? "on" : ""}`}
                  onClick={() => setThemeFilter(t)}>{t}</button>
              ))}
            </div>
            <div className="filter-pill-row">
              {[["weight","weight"],["attrib","attribution"],["items","activity"],["freshness","freshness"]].map(([k, lbl]) => (
                <button key={k} className={`filter-pill ${sortBy === k ? "on" : ""}`}
                  onClick={() => setSortBy(k)}>{lbl}</button>
              ))}
            </div>
          </div>
        </header>
        {sources.length === 0 ? (
          <div className="empty-state mono muted" style={{ padding: "1rem" }}>
            no sources match · clear search or adjust filters
          </div>
        ) : (
          <div className="streams-list">
            {sources.map(src => (
              <article key={src.name}
                className={`stream-row freshness-${src.freshness} stream-row-clickable`}
                onClick={() => setOpenFeedSrc(src)}>
                <div className="stream-head">
                  <div className="stream-meta-left">
                    <span className="stream-name">{src.name}</span>
                    <span className="stream-kind muted small">{src.kind}</span>
                  </div>
                  <div className="stream-meta-right">
                    <span className="mono small">w {(src.weight || 0).toFixed(2)}</span>
                    <span className={`mono small ${(src.attrib30d || 0) >= 0 ? "pos" : "neg"}`}>
                      {(src.attrib30d || 0) >= 0 ? "+" : ""}${((src.attrib30d || 0) / 1000).toFixed(1)}k 30d
                    </span>
                    <span className={`fresh-chip fresh-${src.freshness}`}>{src.freshness}</span>
                    <span className="mono small muted">{src.items7d} items 7d</span>
                    <span className="stream-drill-hint muted small">→</span>
                  </div>
                </div>
                <div className="stream-title">{src.latestTitle}</div>
                <p className="stream-snippet">{src.latestSnippet}</p>
                <div className="stream-foot">
                  <div className="tag-row">
                    {(src.themes || []).map(t => <span key={t} className="tag-chip">{t}</span>)}
                  </div>
                  <span className={`stream-dir mono small dir-${(src.direction || "").replace(/\s+/g, "-")}`}>
                    → {src.direction}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* ── S5 Manual drops ─────────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S5</span>
            <span>Manual drops</span>
            <span className="block-sub">
              KOL captures from /04 inbox · same weighting as published sources, slightly higher per selectivity
            </span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 12 }}>
          <ManualDrops />
        </div>
      </section>

      {/* S1 theme drilldown */}
      <DrillSheet open={!!openTheme} onClose={() => setOpenTheme(null)}
        title={openTheme ? openTheme.label : ""}
        subtitle={openTheme ? `${openTheme.direction} · ${openTheme.age_days}d old` : ""}>
        {openTheme && <ThemeDetailPanel t={openTheme} />}
      </DrillSheet>

      {/* S3 source node drilldown */}
      <DrillSheet open={!!openSrc} onClose={() => setOpenSrc(null)}
        title={openSrc ? openSrc.name : ""}
        subtitle={openSrc ? `T${openSrc.tier} · ${openSrc.market_focus}` : ""}>
        {openSrc && <SourceDetailPanel s={openSrc} />}
      </DrillSheet>

      {/* S4 per-source feed drilldown */}
      <DrillSheet open={!!openFeedSrc} onClose={() => setOpenFeedSrc(null)}
        title={openFeedSrc ? openFeedSrc.name : ""}
        subtitle={openFeedSrc ? openFeedSrc.kind : ""}>
        {openFeedSrc && <SourceDetailPanel s={openFeedSrc} />}
      </DrillSheet>
    </div>
  );
}

Object.assign(window, { Streams });
