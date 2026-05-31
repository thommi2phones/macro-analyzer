// /streams — who's talking about what, across the live sources.
//
// Four sections:
//   S1 — Animated theme scatter map (lifecycle × direction, 4-week PLAY)
//   S2 — Emerging concepts cards (novelty > 0.7 AND velocity > 0.4)
//   S3 — Source network graph (tier rings, echo-tie threads, drilldown)
//   S4 — Per-source feed with search, sort, and DrillSheet (Track A)

const { useState, useEffect, useRef, useCallback } = React;

// ---------------------------------------------------------------------------
// S1 — Theme map (animated scatter)
// ---------------------------------------------------------------------------

function _seed(str) {
  // Simple deterministic seeded random from a string id.
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(31, h) + str.charCodeAt(i) | 0;
  }
  // Return a 0..1 float
  return ((h >>> 0) % 1000) / 1000;
}

function ThemeMap({ themeMap }) {
  const [weekIndex, setWeekIndex] = useState(3);
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef(null);

  const W = 700, H = 320;
  const PAD = { top: 36, right: 24, bottom: 36, left: 24 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  // Direction → y band centre (0=top BULLISH, 1=MIXED, 2=BEARISH bottom)
  const dirY = (dir, jitter) => {
    const bands = { bullish: 0.18, mixed: 0.5, bearish: 0.82 };
    const base = bands[dir] || 0.5;
    return PAD.top + (base + (jitter - 0.5) * 0.12) * innerH;
  };

  // Bubble radius: scale mentions_by_week[weekIndex] to 3..20px
  const bubbleR = (theme) => {
    const maxMentions = Math.max(...themeMap.flatMap(t => t.mentions_by_week));
    const m = theme.mentions_by_week[weekIndex] || 0;
    return 3 + (m / (maxMentions || 1)) * 17;
  };

  // Bubble x: lifecycle (0=EMERGING left, 1=FADING right)
  const bubbleX = (theme) => PAD.left + theme.lifecycle * innerW;

  // Drift trail positions for each theme across all 4 weeks
  const trailPoints = (theme) => {
    return theme.mentions_by_week.map((_, wi) => {
      const jitter = _seed(theme.id);
      return {
        x: bubbleX(theme),
        y: dirY(theme.direction, jitter),
      };
    });
  };

  // Source-overlap threads: themes that share a source (only at weekIndex=3)
  const overlapThreads = () => {
    const threads = [];
    for (let i = 0; i < themeMap.length; i++) {
      for (let j = i + 1; j < themeMap.length; j++) {
        const a = themeMap[i], b = themeMap[j];
        const shared = (a.sources || []).filter(s => (b.sources || []).includes(s));
        if (shared.length > 0) {
          const ja = _seed(a.id), jb = _seed(b.id);
          threads.push({
            x1: bubbleX(a), y1: dirY(a.direction, ja),
            x2: bubbleX(b), y2: dirY(b.direction, jb),
            shared,
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
      if (wi >= 3) {
        clearInterval(timerRef.current);
        setPlaying(false);
      }
    }, 800);
  }, [playing]);

  useEffect(() => () => clearInterval(timerRef.current), []);

  const weekLabels = ["−4w", "−3w", "−2w", "NOW"];

  if (!themeMap || themeMap.length === 0) {
    return (
      <div className="theme-map-empty mono muted">
        no recurring themes mapped yet
      </div>
    );
  }

  return (
    <div className="theme-map">
      {/* Controls */}
      <div className="tm-controls">
        <button
          className={`btn-mini tm-play ${playing ? "active" : ""}`}
          onClick={handlePlay}
          title={playing ? "Pause" : "Play 4-week sweep"}
        >
          {playing ? "⏸ PAUSE" : "▶ PLAY"}
        </button>
        <input
          type="range"
          className="tm-scrubber"
          min={0} max={3} step={1}
          value={weekIndex}
          onChange={e => { clearInterval(timerRef.current); setPlaying(false); setWeekIndex(+e.target.value); }}
        />
        <span className="tm-week-label mono small">{weekLabels[weekIndex]}</span>
      </div>

      {/* SVG scatter */}
      <svg
        className="tm-svg"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Theme lifecycle scatter map"
      >
        {/* Background grid lines */}
        <line x1={PAD.left} y1={H/2} x2={W-PAD.right} y2={H/2}
          stroke="var(--line)" strokeWidth="1" strokeDasharray="4,4" opacity="0.5" />
        <line x1={W/2} y1={PAD.top} x2={W/2} y2={H-PAD.bottom}
          stroke="var(--line)" strokeWidth="1" strokeDasharray="4,4" opacity="0.3" />

        {/* Axis labels */}
        <text x={PAD.left + 4} y={H - 8} fontSize="9" fill="var(--accent)" fontFamily="var(--mono)" letterSpacing="0.14em" opacity="0.8">EMERGING</text>
        <text x={W - PAD.right - 4} y={H - 8} fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)" letterSpacing="0.14em" textAnchor="end" opacity="0.8">FADING</text>
        <text x={PAD.left + 4} y={PAD.top + 8} fontSize="9" fill="var(--green)" fontFamily="var(--mono)" letterSpacing="0.12em" opacity="0.7">BULLISH</text>
        <text x={PAD.left + 4} y={H - PAD.bottom - 6} fontSize="9" fill="var(--red)" fontFamily="var(--mono)" letterSpacing="0.12em" opacity="0.7">BEARISH</text>

        {/* Source-overlap threads at NOW */}
        {weekIndex === 3 && overlapThreads().map((t, i) => (
          <line key={i}
            x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
            stroke="var(--accent)" strokeWidth="0.8" strokeDasharray="3,4"
            opacity="0.25"
          />
        ))}

        {/* Drift trails */}
        {themeMap.map(theme => {
          const pts = trailPoints(theme);
          const ptStr = pts.map(p => `${p.x},${p.y}`).join(" ");
          return (
            <polyline key={theme.id + "-trail"}
              points={ptStr}
              fill="none"
              stroke="var(--text-mute-3)"
              strokeWidth="1"
              strokeDasharray="2,3"
              opacity="0.35"
            />
          );
        })}

        {/* Bubbles */}
        {themeMap.map(theme => {
          const jitter = _seed(theme.id);
          const cx = bubbleX(theme);
          const cy = dirY(theme.direction, jitter);
          const r = bubbleR(theme);
          const isEmerging = theme.age_days < 14;
          const dirClass = theme.direction === "bullish" ? "var(--green)"
            : theme.direction === "bearish" ? "var(--red)"
            : "var(--amber)";

          return (
            <g key={theme.id} className="tm-bubble-group">
              {/* Emerging dashed ring */}
              {isEmerging && (
                <circle cx={cx} cy={cy} r={r + 6}
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="1.5"
                  strokeDasharray="4,3"
                  opacity="0.8"
                />
              )}
              {/* Main bubble */}
              <circle cx={cx} cy={cy} r={r}
                fill={dirClass}
                opacity="0.18"
              />
              <circle cx={cx} cy={cy} r={r}
                fill="none"
                stroke={dirClass}
                strokeWidth="1.5"
                opacity="0.7"
              />
              {/* Label */}
              <text x={cx} y={cy - r - 4}
                fontSize="9" textAnchor="middle"
                fill="var(--text-mute)" fontFamily="var(--mono)"
                opacity="0.9"
              >
                {theme.label}
              </text>
              {/* Mention count badge */}
              <text x={cx} y={cy + 3}
                fontSize="8" textAnchor="middle"
                fill="var(--text)" fontFamily="var(--mono)"
                opacity="0.8"
              >
                {theme.mentions_by_week[weekIndex] || 0}
              </text>
            </g>
          );
        })}

        {/* Legend top-right */}
        <g transform={`translate(${W - PAD.right - 110}, ${PAD.top})`}>
          <circle cx="6" cy="6" r="5" fill="none" stroke="var(--green)" strokeWidth="1.5" opacity="0.7" />
          <text x="14" y="10" fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)">bullish</text>
          <circle cx="6" cy="22" r="5" fill="none" stroke="var(--amber)" strokeWidth="1.5" opacity="0.7" />
          <text x="14" y="26" fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)">mixed</text>
          <circle cx="6" cy="38" r="5" fill="none" stroke="var(--red)" strokeWidth="1.5" opacity="0.7" />
          <text x="14" y="42" fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)">bearish</text>
          <circle cx="6" cy="54" r="7" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="3,2" opacity="0.8" />
          <text x="16" y="58" fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)">emerging (&lt;14d)</text>
        </g>
      </svg>
    </div>
  );
}


// ---------------------------------------------------------------------------
// S2 — Emerging concepts cards
// ---------------------------------------------------------------------------

function ConceptsCards({ concepts }) {
  const NOVELTY_MIN = 0.7;
  const VELOCITY_MIN = 0.4;

  const filtered = (concepts || []).filter(
    c => (c.novelty || 0) > NOVELTY_MIN && (c.velocity || 0) > VELOCITY_MIN
  );

  if (filtered.length === 0) {
    return (
      <div className="empty-state mono muted" style={{ padding: "1.5rem" }}>
        no high-novelty themes this week
      </div>
    );
  }

  return (
    <div className="concept-cards-grid">
      {filtered.map(c => (
        <article key={c.id} className="concept-card">
          <div className="cc-head">
            <span className="cc-new-badge mono">NEW</span>
            <span className="cc-age mono muted small">{c.age_days}d ago</span>
          </div>
          <div className="cc-scores">
            <div className="cc-score-block">
              <div className="cc-score-lbl mono">NOVELTY</div>
              <div className="cc-score-val mono gold">{Math.round(c.novelty * 100)}</div>
            </div>
            <div className="cc-score-block">
              <div className="cc-score-lbl mono">VELOCITY</div>
              <div className="cc-score-val mono">{Math.round(c.velocity * 100)}</div>
            </div>
          </div>
          <div className="cc-title">{c.title}</div>
          <p className="cc-synopsis muted small">{c.synopsis}</p>
          <div className="cc-meta mono small muted">
            <span>{c.items_count} items</span>
            <span>·</span>
            <span>{c.sources_count} sources</span>
          </div>
          <div className="cc-sources">
            {(c.source_names || []).map(n => (
              <span key={n} className="cc-src-chip">{n}</span>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------------
// S3 — Source network graph
// ---------------------------------------------------------------------------

// Static positions grouped by market_focus cluster.
// macro cluster: left; energy cluster: right; social/news cluster: bottom.
const _CLUSTER_POSITIONS = {
  macro:  { cx: 0.22, cy: 0.42 },
  energy: { cx: 0.76, cy: 0.38 },
  social: { cx: 0.48, cy: 0.78 },
};

// Spread nodes within a cluster
function _clusterPos(nodes, W, H, PAD) {
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const clusterCounts = {};
  const clusterIdx = {};

  nodes.forEach(n => {
    const c = n.market_focus in _CLUSTER_POSITIONS ? n.market_focus : "macro";
    clusterCounts[c] = (clusterCounts[c] || 0) + 1;
    clusterIdx[n.id] = clusterIdx[n.id] ?? { c, i: (clusterCounts[c] || 1) - 1 };
  });

  // Re-derive actual positions
  const clusterPos = {};
  nodes.forEach(n => {
    const focusKey = n.market_focus in _CLUSTER_POSITIONS ? n.market_focus : "macro";
    const base = _CLUSTER_POSITIONS[focusKey];
    const count = clusterCounts[focusKey] || 1;
    // Find index of this node in its cluster
    const sameCluster = nodes.filter(x =>
      (x.market_focus in _CLUSTER_POSITIONS ? x.market_focus : "macro") === focusKey
    );
    const idx = sameCluster.indexOf(n);
    // Spread in a small circle around cluster centre
    const angle = (2 * Math.PI * idx) / Math.max(count, 1);
    const radius = count > 1 ? 0.12 : 0;
    clusterPos[n.id] = {
      x: PAD.left + (base.cx + Math.cos(angle) * radius) * innerW,
      y: PAD.top  + (base.cy + Math.sin(angle) * radius) * innerH,
    };
  });
  return clusterPos;
}

function _tierColor(tier) {
  return tier === 1 ? "#d6b15a"
       : tier === 2 ? "#50b478"
       : tier === 3 ? "#e0a030"
       : "#666";
}

function _tierRadius(tier, weight) {
  const base = tier === 1 ? 28 : tier === 2 ? 22 : tier === 3 ? 18 : 14;
  return Math.max(8, weight * base);
}

function SourceGraph({ sourceGraph, onNodeClick }) {
  const [hovered, setHovered] = useState(null);
  const [tooltip, setTooltip] = useState(null);

  const nodes = (sourceGraph && sourceGraph.nodes) || [];
  const links = (sourceGraph && sourceGraph.links) || [];

  const W = 700, H = 340;
  const PAD = { top: 32, right: 24, bottom: 32, left: 24 };

  if (nodes.length === 0) {
    return (
      <div className="empty-state mono muted" style={{ padding: "1.5rem" }}>
        no sources connected yet
      </div>
    );
  }

  const pos = _clusterPos(nodes, W, H, PAD);

  // Build adjacency for hover highlight
  const adjSet = (nodeId) => {
    const adj = new Set();
    links.forEach(l => {
      if (l.source === nodeId) adj.add(l.target);
      if (l.target === nodeId) adj.add(l.source);
    });
    return adj;
  };

  const isLinkHighlighted = (link) => {
    if (!hovered) return false;
    return link.source === hovered || link.target === hovered;
  };

  return (
    <div className="source-graph" style={{ position: "relative" }}>
      <svg
        className="sg-svg"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Source network graph"
      >
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
              stroke="var(--accent)"
              strokeWidth={l.strength * 2}
              opacity={dimmed ? 0.05 : (highlighted ? 0.8 : l.strength * 0.55)}
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

          return (
            <g key={n.id}
              className="sg-node"
              style={{ cursor: "pointer", opacity: dimmed ? 0.3 : 1 }}
              onMouseEnter={() => { setHovered(n.id); setTooltip({ n, px: p.x, py: p.y }); }}
              onMouseLeave={() => { setHovered(null); setTooltip(null); }}
              onClick={() => onNodeClick && onNodeClick(n)}
            >
              {/* Inner fill */}
              <circle cx={p.x} cy={p.y} r={r * 0.72}
                fill={color} opacity="0.12"
              />
              {/* Tier ring */}
              <circle cx={p.x} cy={p.y} r={r}
                fill="none"
                stroke={color}
                strokeWidth={n.tier === 1 ? 2.5 : n.tier === 2 ? 2 : 1.5}
                strokeDasharray={isDashed ? "4,3" : "none"}
                opacity="0.85"
              />
              {/* Tier label */}
              <text x={p.x} y={p.y - r - 4}
                fontSize="8" textAnchor="middle"
                fill={color} fontFamily="var(--mono)"
                letterSpacing="0.1em"
                opacity="0.9"
              >
                T{n.tier}
              </text>
              {/* Source name */}
              <text x={p.x} y={p.y + 3}
                fontSize="8" textAnchor="middle"
                fill="var(--text-mute)" fontFamily="var(--mono)"
              >
                {n.name.length > 10 ? n.name.slice(0, 10) + "…" : n.name}
              </text>
              {/* Weight */}
              <text x={p.x} y={p.y + r + 11}
                fontSize="8" textAnchor="middle"
                fill="var(--text-mute-3)" fontFamily="var(--mono)"
              >
                {n.weight.toFixed(2)}
              </text>
            </g>
          );
        })}

        {/* Legend */}
        <g transform={`translate(${W - 130}, ${PAD.top})`}>
          {[1,2,3,4].map((t, i) => (
            <g key={t} transform={`translate(0, ${i * 16})`}>
              <circle cx="7" cy="7" r="6" fill="none"
                stroke={_tierColor(t)} strokeWidth={t === 1 ? 2 : 1.5}
                strokeDasharray={t === 4 ? "3,2" : "none"}
                opacity="0.85" />
              <text x="18" y="11" fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)">
                T{t} {t === 1 ? "gold" : t === 2 ? "green" : t === 3 ? "amber" : "muted"}
              </text>
            </g>
          ))}
          <g transform="translate(0, 68)">
            <line x1="0" y1="7" x2="14" y2="7" stroke="var(--accent)" strokeWidth="1.5" opacity="0.7" />
            <text x="18" y="11" fontSize="9" fill="var(--text-mute-2)" fontFamily="var(--mono)">co-citation</text>
          </g>
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div className="sg-tooltip" style={{
          left: Math.min(tooltip.px + 14, W - 140) + "px",
          top:  Math.max(tooltip.py - 40, 8) + "px",
        }}>
          <div className="sg-tt-name">{tooltip.n.name}</div>
          <div className="mono small muted">
            T{tooltip.n.tier} · w {tooltip.n.weight.toFixed(2)}
          </div>
          <div className="mono small muted">
            {tooltip.n.market_focus}
          </div>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Main Streams component
// ---------------------------------------------------------------------------

function Streams() {
  const D = window.MA_DATA;
  const s = D.streams || { topVoices: [], bySource: [], summary: "" };

  // S3 node drilldown state
  const [openSrc, setOpenSrc] = React.useState(null);

  // S4 state (Track A — per-source feed)
  const [themeFilter, setThemeFilter] = React.useState("ALL");
  const [sortBy, setSortBy]           = React.useState("weight");
  const [srcQ, setSrcQ]               = React.useState("");
  const [openFeedSrc, setOpenFeedSrc] = React.useState(null);

  const allThemes = Array.from(new Set(
    (s.bySource || []).flatMap(x => x.themes || [])
  )).sort();

  let sources = (s.bySource || []).slice();
  if (themeFilter !== "ALL") {
    sources = sources.filter(x => (x.themes || []).includes(themeFilter));
  }
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
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S1</span>
            <span>Theme map</span>
            <span className="block-sub">
              lifecycle × direction · 4-week sweep · {(s.themeMap || []).length} themes
            </span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 12, paddingBottom: 16 }}>
          <ThemeMap themeMap={s.themeMap || []} />
        </div>
      </section>

      {/* ── S2 Emerging concepts ────────────────────────────────────── */}
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S2</span>
            <span>Emerging concepts</span>
            <span className="block-sub">
              novelty &gt; 70 · velocity &gt; 40 · highest-conviction new themes
            </span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 14 }}>
          <ConceptsCards concepts={s.concepts || []} />
        </div>
      </section>

      {/* ── S3 Source network graph ─────────────────────────────────── */}
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S3</span>
            <span>Source network</span>
            <span className="block-sub">
              echo ties · co-citation strength · click node to drill
            </span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 12, paddingBottom: 16 }}>
          <SourceGraph
            sourceGraph={s.sourceGraph || { nodes: [], links: [] }}
            onNodeClick={n => setOpenSrc(n)}
          />
        </div>
      </section>

      {/* ── S4 Per-source feed (Track A, renumbered) ────────────────── */}
      <section className="block">
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
            <input
              className="src-search"
              placeholder="search sources…"
              value={srcQ}
              onChange={e => setSrcQ(e.target.value)}
            />
            <div className="filter-pill-row">
              <button
                className={`filter-pill ${themeFilter === "ALL" ? "on" : ""}`}
                onClick={() => setThemeFilter("ALL")}
              >ALL</button>
              {allThemes.map(t => (
                <button
                  key={t}
                  className={`filter-pill ${themeFilter === t ? "on" : ""}`}
                  onClick={() => setThemeFilter(t)}
                >{t}</button>
              ))}
            </div>
            <div className="filter-pill-row">
              {[["weight","weight"],["attrib","attribution"],["items","activity"],["freshness","freshness"]].map(([k, lbl]) => (
                <button
                  key={k}
                  className={`filter-pill ${sortBy === k ? "on" : ""}`}
                  onClick={() => setSortBy(k)}
                >{lbl}</button>
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
              <article
                key={src.name}
                className={`stream-row freshness-${src.freshness} stream-row-clickable`}
                onClick={() => setOpenFeedSrc(src)}
              >
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
                    {(src.themes || []).map(t => (
                      <span key={t} className="tag-chip">{t}</span>
                    ))}
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

      {/* S3 source node drilldown */}
      <DrillSheet
        open={!!openSrc}
        onClose={() => setOpenSrc(null)}
        title={openSrc ? openSrc.name : ""}
        subtitle={openSrc ? `T${openSrc.tier} · ${openSrc.market_focus}` : ""}
      >
        {openSrc && <SourceDetailPanel s={openSrc} />}
      </DrillSheet>

      {/* S4 per-source feed drilldown */}
      <DrillSheet
        open={!!openFeedSrc}
        onClose={() => setOpenFeedSrc(null)}
        title={openFeedSrc ? openFeedSrc.name : ""}
        subtitle={openFeedSrc ? openFeedSrc.kind : ""}
      >
        {openFeedSrc && <SourceDetailPanel s={openFeedSrc} />}
      </DrillSheet>
    </div>
  );
}

Object.assign(window, { Streams });
