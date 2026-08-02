// /streams — who's talking about what, across the live sources.
//
// Five sections:
//   S1 — Theme map (2D age × direction, bubble = share of attention)
//   S2 — Emerging concepts cards (novelty > 0.7 AND velocity > 0.4)
//   S3 — Source graph · echo ties (tier rings, co-citation threads)
//   S4 — Per-source feed (search + sort + DrillSheet)
//   S5 — Manual drops (latest /api/manual/inputs entries)
//   S7 — Deep Analysis (long-form dossiers from web/deep/ + manifest.json)

const { useState, useEffect, useRef, useCallback, useMemo } = React;

function _seed(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = Math.imul(31, h) + str.charCodeAt(i) | 0;
  return ((h >>> 0) % 1000) / 1000;
}

// ---------------------------------------------------------------------------
// usePanZoom — wheel-to-zoom + drag-to-pan for SVG content. Returns a viewport
// {transform, handlers, reset, scale} you spread onto an <svg> + apply the
// transform string to a wrapping <g>. Wheel zoom anchors at the cursor so the
// point under the mouse stays stationary.
// ---------------------------------------------------------------------------
function usePanZoom(svgRef, { minScale = 0.4, maxScale = 6 } = {}) {
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const dragRef = useRef(null);

  const _toSvgPoint = (clientX, clientY) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    // Map screen px → viewBox units. preserveAspectRatio=xMidYMid meet
    // means we letterbox; recompute the effective scale from the actual
    // box dimensions vs viewBox.
    const vb = svg.viewBox.baseVal;
    const sx = vb.width  / rect.width;
    const sy = vb.height / rect.height;
    const s  = Math.max(sx, sy);
    const offsetX = (rect.width  * s - vb.width)  / 2;
    const offsetY = (rect.height * s - vb.height) / 2;
    return {
      x: (clientX - rect.left) * s - offsetX,
      y: (clientY - rect.top)  * s - offsetY,
    };
  };

  const onWheel = useCallback((e) => {
    e.preventDefault();
    const p = _toSvgPoint(e.clientX, e.clientY);
    setView(v => {
      const factor = Math.exp(-e.deltaY * 0.0015);
      const k = Math.max(minScale, Math.min(maxScale, v.k * factor));
      // Anchor zoom at cursor: keep the world point (p) under the same screen pixel.
      // screen_world = (world - x) / k  →  fix p_screen by adjusting x,y after k change.
      const x = p.x - (p.x - v.x) * (k / v.k);
      const y = p.y - (p.y - v.y) * (k / v.k);
      return { x, y, k };
    });
  }, [minScale, maxScale]);

  const onMouseDown = useCallback((e) => {
    // Only start a pan on background drags (not on bubbles/links etc).
    // Bubbles call stopPropagation via their own click handlers, so the
    // mousedown still reaches here for the background — but we whitelist
    // by checking that the target is the svg itself or a non-interactive
    // chrome element (rect/line/text). Cursor button must be primary.
    if (e.button !== 0) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "circle" || tag === "g" || e.target.closest("g.tm-bubble-group") || e.target.closest("g.sg-node")) {
      // Allow drag from inside the chart background too — but if the user is
      // about to click a bubble, the click event will still fire (we set a
      // tiny threshold below).
    }
    dragRef.current = { startX: e.clientX, startY: e.clientY, baseX: view.x, baseY: view.y, moved: false };
  }, [view.x, view.y]);

  const onMouseMove = useCallback((e) => {
    const d = dragRef.current;
    if (!d) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const s  = Math.max(vb.width / rect.width, vb.height / rect.height);
    const dx = (e.clientX - d.startX) * s;
    const dy = (e.clientY - d.startY) * s;
    if (!d.moved && Math.hypot(dx, dy) > 3) d.moved = true;
    setView(v => ({ ...v, x: d.baseX + dx, y: d.baseY + dy }));
  }, []);

  const onMouseUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  // Suppress click events that follow a real drag — so panning doesn't open
  // a DrillSheet by accident.
  const onClickCapture = useCallback((e) => {
    if (dragRef.current && dragRef.current.moved) {
      e.stopPropagation();
      e.preventDefault();
    }
  }, []);

  const reset = useCallback(() => setView({ x: 0, y: 0, k: 1 }), []);

  // Attach wheel as non-passive so preventDefault works (React's onWheel is passive).
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const handler = (e) => onWheel(e);
    svg.addEventListener("wheel", handler, { passive: false });
    return () => svg.removeEventListener("wheel", handler);
  }, [onWheel]);

  // Document-level mouse-up so releases outside the svg still end the drag.
  useEffect(() => {
    const up = () => { dragRef.current = null; };
    document.addEventListener("mouseup", up);
    return () => document.removeEventListener("mouseup", up);
  }, []);

  return {
    transform: `translate(${view.x} ${view.y}) scale(${view.k})`,
    scale: view.k,
    handlers: { onMouseDown, onMouseMove, onMouseUp, onClickCapture },
    reset,
  };
}

// Reusable zoom controls overlay — sits in the chart's top-right.
function ZoomControls({ scale, onZoomIn, onZoomOut, onReset, style }) {
  return (
    <div className="zoom-controls mono small" style={style}>
      <button className="btn-mini" onClick={onZoomOut} title="zoom out">−</button>
      <span className="zoom-scale muted" title="current zoom">{(scale || 1).toFixed(2)}×</span>
      <button className="btn-mini" onClick={onZoomIn} title="zoom in">+</button>
      <button className="btn-mini" onClick={onReset} title="reset view">⤧</button>
    </div>
  );
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

// Lifecycle thresholds for the fading-tail treatment.
// Themes with lifecycle in (FADE_START, FADE_ROLLUP] render at reduced
// opacity so they recede visually. Themes with lifecycle > FADE_ROLLUP get
// collapsed into a single "fading cluster" pseudo-bubble per direction band
// (click to expand into the underlying themes).
const _FADE_START   = 0.85;
const _FADE_ROLLUP  = 0.90;
const _FADED_OPACITY = 0.40;

// Per-direction cap on individually-rendered themes. Anything past this
// (by total mention count, smallest first) folds into a "minor themes"
// pseudo-bubble that sits at the band's lifecycle midpoint. Without this
// the mixed band gets 10+ overlapping 3-mention themes and the chart is
// unreadable. Cluster expands on click just like the fading one.
const _MAX_PER_BAND = 5;

// Read a theme's weekly mention count at a fractional week position,
// linearly interpolating between the two bracketing integer weeks. Lets the
// scrubber slide smoothly between the discrete weekly buckets instead of
// snapping. Out-of-range positions clamp to the endpoints.
function _weekVal(t, wi) {
  const buckets = t.mentions_by_week || [];
  if (buckets.length === 0) return 0;
  const clamped = Math.max(0, Math.min(buckets.length - 1, wi));
  const lo = Math.floor(clamped);
  const hi = Math.min(buckets.length - 1, lo + 1);
  const frac = clamped - lo;
  return (buckets[lo] || 0) * (1 - frac) + (buckets[hi] || 0) * frac;
}

// Mirror of the backend _compute_lifecycle but evaluated at an ARBITRARY
// week position wi — i.e. "if week wi were NOW, how extended is this
// theme?" This is what makes bubbles glide horizontally as the scrubber
// moves: at wi = 5, we ask "as of week 5 what was recent vs trailing peak?"
// Constants match the Python side.
const _LC_RECENT   = 2;
const _LC_TRAILING = 12;
const _LC_CURVE    = 1.7;
function _lifecycleAt(t, wi) {
  const buckets = t.mentions_by_week || [];
  if (buckets.length === 0) return t.lifecycle ?? 0.5;
  // If the frame is a cluster pseudo-bubble (e.g. fading rollup at 0.95),
  // its lifecycle is a fixed position anchor — don't recompute.
  if (t._cluster) return t.lifecycle;
  // Sample lifecycle at floor(wi) and ceil(wi), then lerp so the X drift
  // is as smooth as the R drift.
  const evalAt = (idx) => {
    const end = Math.max(1, idx + 1);           // exclusive end (integer)
    const recentStart   = Math.max(0, end - _LC_RECENT);
    const trailingStart = Math.max(0, end - _LC_TRAILING);
    let rSum = 0, rN = 0;
    for (let i = recentStart; i < end; i++) { rSum += buckets[i] || 0; rN++; }
    let peak = 1;
    for (let i = trailingStart; i < end; i++) peak = Math.max(peak, buckets[i] || 0);
    const recentMean = rN ? rSum / rN : 0;
    const ratio = Math.min(1, recentMean / peak);
    const raw = 1 - ratio;
    return Math.max(0, Math.min(1, Math.pow(raw, _LC_CURVE)));
  };
  const clamped = Math.max(0, Math.min(buckets.length - 1, wi));
  const lo = Math.floor(clamped);
  const hi = Math.min(buckets.length - 1, lo + 1);
  const frac = clamped - lo;
  return evalAt(lo) * (1 - frac) + evalAt(hi) * frac;
}

// Window presets for the narrative-drift scrubber. Each is capped by the
// actual bucket length the payload carries (backend emits up to 26 weeks).
const _WINDOW_PRESETS = [
  { key: "4w",  label: "4W",  weeks: 4  },
  { key: "12w", label: "12W", weeks: 12 },
  { key: "26w", label: "6M",  weeks: 26 },
];
const _SPEED_PRESETS = [
  { key: "0.1", label: "0.1×", mult: 0.1 },
  { key: "0.25",label: "0.25×",mult: 0.25},
  { key: "0.5", label: "0.5×", mult: 0.5 },
  { key: "1",   label: "1×",   mult: 1   },
  { key: "2",   label: "2×",   mult: 2   },
  { key: "4",   label: "4×",   mult: 4   },
];

// 1 day = 1/7 week — step size for the day-nudge buttons.
const _DAY_STEP = 1 / 7;

function ThemeMap({ themeMap, onThemeClick }) {
  // Full bucket length from the payload. Backend emits up to 26 weekly
  // buckets (oldest→newest, last = NOW); older data just carries zeros.
  const totalBuckets = Math.max(
    1,
    ...(themeMap || []).map(t => (t.mentions_by_week || []).length)
  );
  const [windowWeeks, setWindowWeeks] = useState(4);
  const [speedMult, setSpeedMult]     = useState(1);
  // weekIndex is a FLOAT position in [scrubStart, totalBuckets-1] so the
  // scrubber slides smoothly between weekly buckets instead of snapping.
  const [weekIndex, setWeekIndex] = useState(totalBuckets - 1);
  const [playing, setPlaying]     = useState(false);
  const [dirFilter, setDirFilter] = useState("all");
  // Clamp the requested window to what the payload actually has.
  const effWeeks   = Math.min(windowWeeks, totalBuckets);
  const scrubStart = totalBuckets - effWeeks;
  const scrubEnd   = totalBuckets - 1;
  // If the user shrinks the window past the current scrub position, snap
  // to the new left edge.
  useEffect(() => {
    if (weekIndex < scrubStart) setWeekIndex(scrubStart);
    if (weekIndex > scrubEnd) setWeekIndex(scrubEnd);
  }, [scrubStart, scrubEnd]);
  // Per-direction expansion state for the fading-cluster roll-up bubbles.
  const [expanded, setExpanded]   = useState({ bullish: false, mixed: false, bearish: false });
  // Per-direction expansion state for the minor-theme rollup (tail by mentions).
  const [expandedMinor, setExpandedMinor] = useState({ bullish: false, mixed: false, bearish: false });
  const timerRef = useRef(null);
  const svgRef = useRef(null);
  const pz = usePanZoom(svgRef);

  const W = 1080, H = 520;
  const PAD = { top: 56, right: 56, bottom: 64, left: 132 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top  - PAD.bottom;

  // Apply the direction filter, then split each direction into:
  //  (a) live  — top-N by mentions, rendered individually
  //  (b) minor — tail past the cap, folded into one cluster per direction
  //              at the band's lifecycle midpoint
  //  (c) fading — lifecycle > FADE_ROLLUP, folded into another cluster at
  //               the right edge
  // Each cluster is a pseudo-theme with id `__<kind>_<dir>` that expands
  // on click into its members.
  const _mentionTotal = (t) => (t.mentions_by_week || []).reduce((a, b) => a + b, 0);
  const _makeCluster = (kind, dir, members, lifecycle) => {
    const sumWeeks = [0, 0, 0, 0];
    const allSources = new Set();
    let maxAge = 0;
    members.forEach(m => {
      (m.mentions_by_week || []).forEach((v, i) => { sumWeeks[i] += v; });
      (m.sources || []).forEach(s => allSources.add(s));
      maxAge = Math.max(maxAge, m.age_days || 0);
    });
    return {
      id: `__${kind}_${dir}`,
      label: `${members.length} ${kind} themes`,
      direction: dir,
      lifecycle,
      novelty: 0,
      velocity: 0,
      age_days: maxAge,
      mentions_by_week: sumWeeks,
      sources: [...allSources],
      _cluster: true,
      _clusterKind: kind,
      _members: members,
    };
  };

  const { renderThemes, fadingByDir, minorByDir } = useMemo(() => {
    const filtered = dirFilter === "all"
      ? themeMap
      : themeMap.filter(t => t.direction === dirFilter);
    const byDir = { bullish: [], mixed: [], bearish: [] };
    filtered.forEach(t => (byDir[t.direction] || byDir.mixed).push(t));

    const fading = { bullish: [], mixed: [], bearish: [] };
    const minor  = { bullish: [], mixed: [], bearish: [] };
    const out = [];

    Object.entries(byDir).forEach(([dir, arr]) => {
      // Step 1: split off fading themes
      const remaining = [];
      arr.forEach(t => {
        if ((t.lifecycle || 0) > _FADE_ROLLUP) fading[dir].push(t);
        else remaining.push(t);
      });
      // Step 2: from what's left, keep top-N by mentions; rest are minor.
      remaining.sort((a, b) => _mentionTotal(b) - _mentionTotal(a));
      const live = remaining.slice(0, _MAX_PER_BAND);
      minor[dir] = remaining.slice(_MAX_PER_BAND);
      out.push(...live);
    });

    // Expanding a cluster reveals its members, but NEVER all of them — a
    // 146-member expansion blows up the O(n²) thread pass and crashes the
    // tab. Cap the reveal; spill the remainder back into a residual cluster
    // the user can keep paging.
    const EXPAND_CAP = 24;
    const expandInto = (members, kind, dir, lifecycle) => {
      const sorted = members.slice().sort((a, b) => _mentionTotal(b) - _mentionTotal(a));
      out.push(...sorted.slice(0, EXPAND_CAP));
      if (sorted.length > EXPAND_CAP) {
        out.push(_makeCluster(kind, dir, sorted.slice(EXPAND_CAP), lifecycle));
      }
    };

    // Append minor cluster pseudos (at lifecycle 0.55 — middle of the chart).
    Object.entries(minor).forEach(([dir, members]) => {
      if (members.length === 0) return;
      if (expandedMinor[dir]) { expandInto(members, "minor", dir, 0.55); return; }
      out.push(_makeCluster("minor", dir, members, 0.55));
    });
    // Append fading cluster pseudos (at lifecycle 0.95 — right edge).
    Object.entries(fading).forEach(([dir, members]) => {
      if (members.length === 0) return;
      if (expanded[dir]) { expandInto(members, "fading", dir, 0.95); return; }
      out.push(_makeCluster("fading", dir, members, 0.95));
    });
    return { renderThemes: out, fadingByDir: fading, minorByDir: minor };
  }, [themeMap, dirFilter, expanded, expandedMinor]);

  const visibleThemes = renderThemes;

  // Bubble radius first, so layout can use it for collision avoidance.
  const maxMentions = Math.max(1, ...themeMap.flatMap(t => t.mentions_by_week || [0]));
  const totalNow = (themeMap.reduce((a, t) => a + _weekVal(t, weekIndex), 0)) || 1;
  const bubbleR = t => {
    const m = _weekVal(t, weekIndex);
    return 20 + (m / maxMentions) * 30;
  };

  // Deterministic layout: within each direction band, sort by lifecycle and
  // spread evenly on Y. Then nudge X to enforce minimum spacing so adjacent
  // bubbles don't horizontally pile up in the FRESH zone.
  const layout = useMemo(() => {
    // Mixed gets the widest vertical band because it tends to carry the
    // most themes (the directional bands are end-states; mixed is the
    // default for noisy/contested narratives).
    const BAND_RANGES = {
      bullish: [0.04, 0.28],
      mixed:   [0.34, 0.72],
      bearish: [0.78, 0.96],
    };
    const out = {};
    const byDir = { bullish: [], mixed: [], bearish: [] };
    visibleThemes.forEach(t => (byDir[t.direction] || byDir.mixed).push(t));
    Object.entries(byDir).forEach(([dir, arr]) => {
      const [t0, t1] = BAND_RANGES[dir] || BAND_RANGES.mixed;
      // Lifecycle is evaluated AT the scrubber's current weekIndex so
      // bubbles drift horizontally as time advances — a name that was
      // fresh two months ago drifts right as it fades, then may drop off.
      const lcOf = (t) => _lifecycleAt(t, weekIndex);
      const sorted = arr.slice().sort((a, b) => lcOf(a) - lcOf(b));
      // First pass — assign raw x from lifecycle + tiny jitter, y from band index.
      const items = sorted.map((t, i) => {
        const frac = sorted.length === 1 ? 0.5 : i / (sorted.length - 1);
        const yFrac = t0 + frac * (t1 - t0);
        const xJitter = (_seed(t.id + ":x") - 0.5) * 0.03;
        const lc = lcOf(t);
        return {
          theme: t,
          x: PAD.left + Math.max(0, Math.min(1, lc + xJitter)) * innerW,
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
    const m = _weekVal(t, weekIndex);
    return Math.round((m / totalNow) * 100);
  };

  // Threads between themes sharing ≥1 source (NOW frame only).
  // Hard-bounded: the pairing is O(n²) and cluster pseudo-bubbles aggregate
  // every member's sources, so without limits a large map renders tens of
  // thousands of <line>s and crashes the tab. We (1) skip cluster bubbles
  // entirely (their threads are meaningless aggregates), (2) bail if there
  // are too many real bubbles, and (3) keep only the strongest threads.
  const _MAX_THREAD_NODES = 40;
  const _MAX_THREADS = 80;
  const overlapThreads = () => {
    const reals = visibleThemes.filter(t => !t._cluster);
    if (reals.length > _MAX_THREAD_NODES) return [];  // too dense to be legible
    const threads = [];
    for (let i = 0; i < reals.length; i++) {
      for (let j = i + 1; j < reals.length; j++) {
        const a = reals[i], b = reals[j];
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
    // Keep only the strongest co-citations if we're over budget.
    threads.sort((a, b) => b.shared - a.shared);
    return threads.slice(0, _MAX_THREADS);
  };

  // Play sweeps the visible window from left edge → NOW with rAF-driven
  // fractional steps so bubbles glide between weekly buckets instead of
  // jumping. Base cadence is ~0.6s per week; speedMult scales it.
  const handlePlay = useCallback(() => {
    if (playing) {
      cancelAnimationFrame(timerRef.current);
      setPlaying(false);
      return;
    }
    setWeekIndex(scrubStart);
    setPlaying(true);
    const start = performance.now();
    const BASE_MS_PER_WEEK = 600;
    const duration = Math.max(200, (effWeeks * BASE_MS_PER_WEEK) / speedMult);
    const tick = (t) => {
      const p = Math.min(1, (t - start) / duration);
      const wi = scrubStart + p * (scrubEnd - scrubStart);
      setWeekIndex(wi);
      if (p >= 1) { setPlaying(false); return; }
      timerRef.current = requestAnimationFrame(tick);
    };
    timerRef.current = requestAnimationFrame(tick);
  }, [playing, scrubStart, scrubEnd, effWeeks, speedMult]);

  useEffect(() => () => cancelAnimationFrame(timerRef.current), []);

  if (!themeMap || themeMap.length === 0) {
    return <div className="theme-map-empty mono muted">no recurring themes mapped yet</div>;
  }

  const threads = weekIndex >= scrubEnd - 0.05 ? overlapThreads() : [];
  const leftLabel = `−${effWeeks}W`;

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

      {/* Window + speed selectors */}
      <div className="tm-header-row" style={{ marginTop: 4 }}>
        <div className="tm-dir-filter mono small">
          <span className="muted" style={{ marginRight: 8 }}>window</span>
          {_WINDOW_PRESETS.filter(w => w.weeks <= totalBuckets).map(w => (
            <button
              key={w.key}
              className={`filter-pill ${windowWeeks === w.weeks ? "on" : ""}`}
              onClick={() => setWindowWeeks(w.weeks)}
            >{w.label}</button>
          ))}
        </div>
        <div className="tm-dir-filter mono small">
          <span className="muted" style={{ marginRight: 8 }}>speed</span>
          {_SPEED_PRESETS.map(s => (
            <button
              key={s.key}
              className={`filter-pill ${speedMult === s.mult ? "on" : ""}`}
              onClick={() => setSpeedMult(s.mult)}
            >{s.label}</button>
          ))}
        </div>
      </div>

      {/* Replay + scrubber + day-nudge */}
      <div className="tm-scrub-row">
        <button
          className={`btn-mini tm-play ${playing ? "active" : ""}`}
          onClick={handlePlay}
        >
          {playing ? "⏸ PAUSE" : "▶ REPLAY"}
        </button>
        <button
          className="btn-mini"
          title="step back 1 day"
          onClick={() => {
            cancelAnimationFrame(timerRef.current); setPlaying(false);
            setWeekIndex(Math.max(scrubStart, weekIndex - _DAY_STEP));
          }}
        >◀ 1d</button>
        <button
          className="btn-mini"
          title="step forward 1 day"
          onClick={() => {
            cancelAnimationFrame(timerRef.current); setPlaying(false);
            setWeekIndex(Math.min(scrubEnd, weekIndex + _DAY_STEP));
          }}
        >1d ▶</button>
        <div className="tm-scrub-track">
          <span className="tm-scrub-label-left mono small muted">{leftLabel}</span>
          <input
            type="range"
            className="tm-scrubber"
            min={scrubStart} max={scrubEnd} step={_DAY_STEP}
            value={weekIndex}
            onChange={e => { cancelAnimationFrame(timerRef.current); setPlaying(false); setWeekIndex(+e.target.value); }}
          />
          <span className="tm-scrub-label-mid mono small muted">
            {(() => {
              const daysAgo = Math.round((scrubEnd - weekIndex) * 7);
              return daysAgo <= 0 ? "NOW" : `−${daysAgo}d`;
            })()}
          </span>
          <span className="tm-scrub-label-right mono small muted">NOW</span>
        </div>
        <div className="tm-now-pill mono small">
          <div className="tm-now-label">NOW</div>
          <div className="tm-now-live muted">LIVE</div>
        </div>
      </div>
      <div className="tm-hint muted small">
        scrub, use ◀ 1d / 1d ▶ for day-by-day, or press play — emerging themes enter at the left and drift right as they age; the gold ring fades as a narrative matures.
      </div>

      {/* Chart + sidebar */}
      <div className="tm-chart-wrap" style={{ position: "relative" }}>
        <ZoomControls
          scale={pz.scale}
          onZoomIn={() => { svgRef.current?.dispatchEvent(new WheelEvent("wheel", { deltaY: -200, clientX: svgRef.current.getBoundingClientRect().left + svgRef.current.getBoundingClientRect().width/2, clientY: svgRef.current.getBoundingClientRect().top + svgRef.current.getBoundingClientRect().height/2, bubbles: true })); }}
          onZoomOut={() => { svgRef.current?.dispatchEvent(new WheelEvent("wheel", { deltaY: 200, clientX: svgRef.current.getBoundingClientRect().left + svgRef.current.getBoundingClientRect().width/2, clientY: svgRef.current.getBoundingClientRect().top + svgRef.current.getBoundingClientRect().height/2, bubbles: true })); }}
          onReset={pz.reset}
          style={{ position: "absolute", top: 8, left: 8, zIndex: 5 }}
        />
        <svg
          ref={svgRef}
          className="tm-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Theme lifecycle scatter map"
          style={{ cursor: "grab", touchAction: "none" }}
          {...pz.handlers}
        >
        <g transform={pz.transform}>
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
            const isEmerging = theme.age_days < 14 && !theme._cluster;
            const isCluster = !!theme._cluster;
            // Fade individual bubbles whose lifecycle is in the dying band
            // (between FADE_START and FADE_ROLLUP). Cluster bubbles render at
            // their own muted opacity below.
            const isFading = !isCluster && (theme.lifecycle || 0) > _FADE_START;
            const color = isCluster
              ? "var(--text-mute-3)"
              : (_DIR_COLOR[theme.direction] || "var(--amber)");
            const bubbleOpacity = isCluster
              ? 0.55
              : (isFading ? _FADED_OPACITY : 0.95);
            const fillOpacity = isCluster
              ? 0.06
              : (isFading ? 0.06 : 0.14);
            const m = _weekVal(theme, weekIndex);
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

            const onClick = () => {
              if (isCluster) {
                const setter = theme._clusterKind === "minor" ? setExpandedMinor : setExpanded;
                setter(e => ({ ...e, [theme.direction]: !e[theme.direction] }));
                return;
              }
              if (onThemeClick) onThemeClick(theme);
            };

            return (
              <g key={theme.id} className="tm-bubble-group"
                style={{ cursor: "pointer", opacity: isFading && !isCluster ? 0.75 : 1 }}
                onClick={onClick}>
                {isEmerging && (
                  <circle cx={cx} cy={cy} r={r + 6}
                    fill="none" stroke="var(--accent)" strokeWidth="1.5"
                    strokeDasharray="4,3" opacity="0.85" />
                )}
                {/* Invisible larger hit target so the label area is clickable too */}
                <circle cx={cx} cy={cy} r={r + 18}
                  fill="transparent" pointerEvents="all" />
                <circle cx={cx} cy={cy} r={r}
                  fill={color} opacity={fillOpacity} pointerEvents="all" />
                <circle cx={cx} cy={cy} r={r}
                  fill="none" stroke={color}
                  strokeWidth={isCluster ? 1.25 : 1.5}
                  strokeDasharray={isCluster ? "4,3" : undefined}
                  opacity={bubbleOpacity}
                  pointerEvents="all" />
                {/* Theme label */}
                <text x={cx} y={labelY} fontSize={isCluster ? 12 : 13} textAnchor="middle"
                  fill={isCluster ? "var(--text-mute-2)" : "var(--text)"}
                  fontFamily="var(--mono)"
                  fontStyle={isCluster ? "normal" : "italic"}
                  paintOrder="stroke" stroke="var(--bg-card-2, #1a1a1a)" strokeWidth="4"
                  strokeLinejoin="round"
                  opacity={isFading && !isCluster ? 0.75 : 1}>
                  {isCluster ? theme.label : theme.label}
                </text>
                {/* Items + share of attention (or "click to expand" hint on cluster) */}
                <text x={cx} y={metaY} fontSize="10" textAnchor="middle"
                  fill={color} fontFamily="var(--mono)"
                  paintOrder="stroke" stroke="var(--bg-card-2, #1a1a1a)" strokeWidth="3.5"
                  strokeLinejoin="round"
                  opacity={isFading && !isCluster ? 0.75 : 1}>
                  {isCluster ? "click to expand" : `${m} items · ${pct}%`}
                </text>
              </g>
            );
          })}
          {/* Per-direction "collapse" affordance when a cluster is expanded.
              Both fading (right edge, lifecycle≈0.95) and minor (middle,
              lifecycle≈0.55) get one. */}
          {["bullish", "mixed", "bearish"].flatMap(dir => {
            const yFrac = dir === "bullish" ? 0.16 : dir === "mixed" ? 0.53 : 0.87;
            const y = PAD.top + yFrac * innerH;
            const chips = [];
            if (expanded[dir] && (fadingByDir[dir] || []).length > 0) {
              const x = PAD.left + innerW - 60;
              chips.push(
                <g key={`collapse_fading_${dir}`} style={{ cursor: "pointer" }}
                  onClick={() => setExpanded(e => ({ ...e, [dir]: false }))}>
                  <rect x={x - 50} y={y - 9} width={100} height={18} rx={3}
                    fill="var(--bg-card-2, #1a1a1a)" stroke="var(--text-mute-3)"
                    strokeWidth="0.8" opacity="0.85" />
                  <text x={x} y={y + 4} fontSize="9" textAnchor="middle"
                    fill="var(--text-mute-2)" fontFamily="var(--mono)"
                    letterSpacing="0.14em">⤺ HIDE FADING</text>
                </g>
              );
            }
            if (expandedMinor[dir] && (minorByDir[dir] || []).length > 0) {
              const x = PAD.left + innerW * 0.55;
              chips.push(
                <g key={`collapse_minor_${dir}`} style={{ cursor: "pointer" }}
                  onClick={() => setExpandedMinor(e => ({ ...e, [dir]: false }))}>
                  <rect x={x - 48} y={y - 9} width={96} height={18} rx={3}
                    fill="var(--bg-card-2, #1a1a1a)" stroke="var(--text-mute-3)"
                    strokeWidth="0.8" opacity="0.85" />
                  <text x={x} y={y + 4} fontSize="9" textAnchor="middle"
                    fill="var(--text-mute-2)" fontFamily="var(--mono)"
                    letterSpacing="0.14em">⤺ HIDE MINOR</text>
                </g>
              );
            }
            return chips;
          })}
        </g>
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
  const impact = t.market_impact || t.direction;
  const dirColor = impact === "bullish" ? "var(--green)"
                 : impact === "bearish" ? "var(--red)" : "var(--amber)";
  const isMacro = t.theme_kind === "macro_factor";
  // a-pole states (risk-on → bullish impact) vs b-pole (risk-off → bearish).
  const BULL_STATES = new Set(["dovish", "cooling", "receding", "de-escalating"]);
  const BEAR_STATES = new Set(["hawkish", "rising", "elevated", "escalating"]);
  const stateColor = st => BULL_STATES.has(st) ? "var(--green)"
                         : BEAR_STATES.has(st) ? "var(--red)" : "var(--amber)";

  return (
    <div className="source-detail">
      {isMacro ? (
        <>
          {t.primary_data && t.primary_data.current && (
            <div className="detail-section">
              <div className="detail-section-head mono">CURRENT FED POLICY · <span className="muted">FRED · primary</span></div>
              <div className="mono" style={{ color: "var(--text-primary)", fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase" }}>
                → {t.primary_data.current.level.toFixed(2)}% TARGET · {t.primary_data.current.action}
              </div>
              <div className="mono small muted" style={{ marginTop: 4 }}>
                last move {t.primary_data.current.last_change_bps > 0 ? "+" : ""}{t.primary_data.current.last_change_bps}bps
                {t.primary_data.current.last_change_date ? ` on ${t.primary_data.current.last_change_date}` : ""}
                {" · "}held {t.primary_data.current.days_held}d
              </div>
            </div>
          )}
          <div className="detail-section">
            <div className="detail-section-head mono">{t.primary_data ? "EXPECTED FED POLICY" : (t.factor_axis || "stance").toUpperCase()}</div>
            {t.primary_data && t.primary_data.expected_market && (
              <div style={{ marginBottom: 10 }}>
                <div className="mono" style={{ color: stateColor(t.primary_data.expected_market.market_lean), fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase" }}>
                  → market: {t.primary_data.expected_market.market_lean}
                </div>
                <div className="mono small muted" style={{ marginTop: 4 }}>
                  2Y {t.primary_data.expected_market.two_year.toFixed(2)}% vs {t.primary_data.expected_market.effective.toFixed(2)}% eff
                  {" · "}{t.primary_data.expected_market.spread_bps > 0 ? "+" : ""}{t.primary_data.expected_market.spread_bps}bps → {t.primary_data.expected_market.market_impact}
                </div>
              </div>
            )}
            <div className="mono" style={{ color: t.primary_data ? "var(--text-secondary)" : "var(--text-primary)", fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase" }}>
              → {t.primary_data ? "commentary: " : ""}{t.factor_state || "neutral"}
            </div>
            <div className="mono small muted" style={{ marginTop: 4 }}>
              {t.primary_data
                ? `sentiment lean from ${(t.sources || []).length} secondary sources — opinion, not policy`
                : `implied broad-risk read of a ${t.factor_state || "neutral"} ${t.factor_axis || "factor"} → ${impact}`}
            </div>
          </div>
          {t.factor_tally && (
            <div className="detail-section">
              <div className="detail-section-head mono">
                INPUTS · {Object.values(t.factor_tally).reduce((a, b) => a + b, 0)} reads
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "6px 0 10px" }}>
                {Object.entries(t.factor_tally).map(([st, n]) => (
                  <span key={st} className="mono small" style={{
                    color: stateColor(st), border: "1px solid var(--border)",
                    borderRadius: 4, padding: "2px 8px", opacity: n ? 1 : 0.4,
                  }}>{st} · {n}</span>
                ))}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(t.factor_inputs || []).length === 0 && (
                  <div className="mono small muted">no cue-matched documents · read is from balanced/absent signals</div>
                )}
                {(t.factor_inputs || []).map((row, i) => (
                  <div key={i} style={{ borderLeft: `2px solid ${stateColor(row.state)}`, paddingLeft: 8 }}>
                    <div className="mono small">
                      <span className="muted">{row.date}</span>
                      {" · "}<span style={{ color: "var(--text-primary)" }}>{row.source}</span>
                      {" · "}<span style={{ color: stateColor(row.state), textTransform: "uppercase" }}>{row.state}</span>
                      {row.cue && <span className="muted"> · “{row.cue}”</span>}
                    </div>
                    {row.snippet && (
                      <div className="mono muted" style={{ fontSize: 11, marginTop: 2, lineHeight: 1.5 }}>
                        {row.snippet}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : t.primary_data && t.primary_data.market ? (
        <>
          <div className="detail-section">
            <div className="detail-section-head mono">
              {t.primary_data.market.asset} MARKET · <span className="muted">PRICE · PRIMARY</span>
            </div>
            <div className="mono" style={{
              color: t.primary_data.market.impact === "bullish" ? "var(--green)"
                   : t.primary_data.market.impact === "bearish" ? "var(--red)" : "var(--amber)",
              fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase",
            }}>
              → ${Math.round(t.primary_data.market.price).toLocaleString()} · {t.primary_data.market.trend}
            </div>
            <div className="mono small muted" style={{ marginTop: 4 }}>
              {t.primary_data.market.chg_7d != null && `7d ${t.primary_data.market.chg_7d > 0 ? "+" : ""}${t.primary_data.market.chg_7d}%`}
              {t.primary_data.market.chg_30d != null && ` · 30d ${t.primary_data.market.chg_30d > 0 ? "+" : ""}${t.primary_data.market.chg_30d}%`}
              {t.primary_data.market.vs_ema50 != null && ` · vs 50d ${t.primary_data.market.vs_ema50 > 0 ? "+" : ""}${t.primary_data.market.vs_ema50}%`}
              {t.primary_data.market.vs_ema200 != null && ` · vs 200d ${t.primary_data.market.vs_ema200 > 0 ? "+" : ""}${t.primary_data.market.vs_ema200}%`}
            </div>
            {t.primary_data.risk_appetite && (
              <div className="mono small muted" style={{ marginTop: 4 }}>
                ETH/BTC {t.primary_data.risk_appetite.eth_btc_chg_30d > 0 ? "+" : ""}{t.primary_data.risk_appetite.eth_btc_chg_30d}% 30d · {t.primary_data.risk_appetite.lean}
              </div>
            )}
          </div>
          <div className="detail-section">
            <div className="detail-section-head mono">POSITIONING · <span className="muted">KOL sentiment</span></div>
            <div className="mono" style={{ color: dirColor, fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase" }}>
              → {t.direction}
            </div>
            <div className="mono small muted" style={{ marginTop: 4 }}>
              what {(t.sources || []).length} tracked sources lean — opinion vs the tape above
            </div>
          </div>
        </>
      ) : (
        <div className="detail-section">
          <div className="detail-section-head mono">DIRECTION</div>
          <div className="mono" style={{ color: dirColor, fontSize: 14, letterSpacing: "0.12em", textTransform: "uppercase" }}>
            → {t.direction}
          </div>
        </div>
      )}

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
  const svgRef = useRef(null);
  const pz = usePanZoom(svgRef);

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

  // Layout: each cluster gets a rectangular sub-region of the 3×3 grid.
  // Inside the sub-region, top-N nodes (sorted by tier asc, weight desc)
  // pack into a grid; the rest fold into one "+M more" overflow marker
  // anchored at the cluster center. This replaces the prior polar/ring
  // layout, which produced unreadable concentric rings once any cluster
  // grew past ~10 nodes.
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top  - PAD.bottom;
  const SG_CAP_PER_CLUSTER = 12;
  const pos = {};
  const overflow = {}; // cluster key → count of nodes hidden
  const byCluster = {};
  nodes.forEach(n => {
    const k = _clusterFor(n);
    (byCluster[k] ||= []).push(n);
  });
  // Cell metrics for the 3×3 cluster grid. Each cluster's bounding box is
  // (cellW × cellH), centered on (baseX, baseY). Leave a margin so labels
  // and edge nodes don't bleed into neighbouring clusters.
  const cellW = innerW / 3, cellH = innerH / 3;
  const cellPad = 22;
  // Per-cluster bounding box (for "show N more" badge + header placement).
  const clusterBox = {};
  for (const c of _CLUSTERS) {
    const list = (byCluster[c.key] || []).slice().sort((a, b) => {
      if (a.tier !== b.tier) return a.tier - b.tier;
      return (b.weight || 0) - (a.weight || 0);
    });
    const baseX = PAD.left + c.cx * innerW;
    const baseY = PAD.top  + c.cy * innerH;
    const boxW = cellW - cellPad * 2;
    const boxH = cellH - cellPad * 2 - 18; // reserve top strip for the label
    const visible = list.slice(0, SG_CAP_PER_CLUSTER);
    overflow[c.key] = Math.max(0, list.length - visible.length);
    clusterBox[c.key] = { baseX, baseY, boxW, boxH, count: list.length };
    if (visible.length === 0) continue;
    const cols = Math.min(visible.length, Math.ceil(Math.sqrt(visible.length * (boxW / boxH))));
    const rows = Math.ceil(visible.length / cols);
    const stepX = boxW / Math.max(cols, 1);
    const stepY = boxH / Math.max(rows, 1);
    const originX = baseX - boxW / 2 + stepX / 2;
    const originY = baseY - boxH / 2 + stepY / 2 + 6;
    visible.forEach((n, i) => {
      const row = Math.floor(i / cols);
      const col = i % cols;
      pos[n.id] = { x: originX + col * stepX, y: originY + row * stepY };
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

      <div className="sg-chart-wrap" style={{ position: "relative" }}>
        <ZoomControls
          scale={pz.scale}
          onZoomIn={() => { svgRef.current?.dispatchEvent(new WheelEvent("wheel", { deltaY: -200, clientX: svgRef.current.getBoundingClientRect().left + svgRef.current.getBoundingClientRect().width/2, clientY: svgRef.current.getBoundingClientRect().top + svgRef.current.getBoundingClientRect().height/2, bubbles: true })); }}
          onZoomOut={() => { svgRef.current?.dispatchEvent(new WheelEvent("wheel", { deltaY: 200, clientX: svgRef.current.getBoundingClientRect().left + svgRef.current.getBoundingClientRect().width/2, clientY: svgRef.current.getBoundingClientRect().top + svgRef.current.getBoundingClientRect().height/2, bubbles: true })); }}
          onReset={pz.reset}
          style={{ position: "absolute", top: 8, left: 8, zIndex: 5 }}
        />
        <svg
          ref={svgRef}
          className="sg-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Source network graph"
          style={{ cursor: "grab", touchAction: "none" }}
          {...pz.handlers}
        >
        <g transform={pz.transform}>
          {/* Cluster category labels — sit above the top of the cluster's
              spread radius + max node ring + breathing room. Empty clusters
              render as ghosts so the user can see *which* themes have no
              source coverage yet. */}
          {_CLUSTERS.map(c => {
            const box = clusterBox[c.key];
            const baseX = box.baseX;
            const baseY = box.baseY;
            // Cluster bounding rectangle so the user can read the grid as
            // a partition of the chart instead of a soup of bubbles.
            const rectX = baseX - box.boxW / 2 - 4;
            const rectY = baseY - box.boxH / 2 - 4;
            if (box.count === 0) {
              return (
                <g key={c.key} className="sg-ghost-cluster" opacity="0.42">
                  <rect x={rectX} y={rectY} width={box.boxW + 8} height={box.boxH + 8} rx={4}
                    fill="none" stroke="var(--text-mute-3)" strokeWidth="1"
                    strokeDasharray="3,4" />
                  <text x={baseX} y={baseY - 4} fontSize="10.5"
                    fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.22em"
                    textAnchor="middle">
                    {c.label}
                  </text>
                  <text x={baseX} y={baseY + 14} fontSize="9"
                    fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.16em"
                    textAnchor="middle">
                    NO COVERAGE
                  </text>
                </g>
              );
            }
            const more = overflow[c.key] || 0;
            return (
              <g key={c.key}>
                {/* Faint bounding box delineating the cluster's region */}
                <rect x={rectX} y={rectY} width={box.boxW + 8} height={box.boxH + 8} rx={4}
                  fill="none" stroke="var(--border, #333)" strokeWidth="0.6"
                  opacity="0.35" />
                <text x={baseX} y={rectY - 4} fontSize="10.5"
                  fill="var(--text-mute-2)" fontFamily="var(--mono)" letterSpacing="0.22em"
                  textAnchor="middle" opacity="0.9">
                  {c.label}
                  {box.count > SG_CAP_PER_CLUSTER ? ` · top ${SG_CAP_PER_CLUSTER} of ${box.count}` : ""}
                </text>
                {more > 0 && (
                  <text x={baseX} y={rectY + box.boxH + 18} fontSize="9"
                    fill="var(--text-mute-3)" fontFamily="var(--mono)" letterSpacing="0.16em"
                    textAnchor="middle" opacity="0.85">
                    +{more} MORE
                  </text>
                )}
              </g>
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
        </g>
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
// S7 — Deep Analysis. Long-form dossiers (self-contained HTML / PDF / links)
// dropped into web/deep/ and indexed by web/deep/manifest.json. Cards only;
// the dossier itself opens in a new tab.
// ---------------------------------------------------------------------------
function DeepAnalysis() {
  const [reports, setReports] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch("deep/manifest.json")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(j => setReports(j.reports || []))
      .catch(e => setErr(String(e.message || e)));
  }, []);

  if (err) return <div className="muted small" style={{ padding: 16 }}>deep/manifest.json unavailable — {err}</div>;
  if (!reports) return <div className="muted small" style={{ padding: 16 }}>loading…</div>;
  if (!reports.length) return (
    <div className="muted small" style={{ padding: 16 }}>
      No dossiers yet. Drop the report file in <span className="mono">web/deep/</span> and add an entry to <span className="mono">manifest.json</span>.
    </div>
  );

  return (
    <div className="deep-grid">
      {reports.map(r => <DeepCard key={r.id} r={r} />)}
    </div>
  );
}

function _deepCallClass(call) {
  const c = (call || "").toUpperCase();
  if (c.includes("SHORT") || c.includes("BUST")) return "deep-call-bear";
  if (c.includes("LONG") || c.includes("BUYING") || c.includes("PLAYED OUT")) return "deep-call-bull";
  return "deep-call-neutral";
}

function DeepTable({ t }) {
  return (
    <div className="deep-tbl-wrap">
      <div className="deep-tbl-title mono">{t.title}</div>
      {t.note && <div className="deep-tbl-note muted small">{t.note}</div>}
      <table className="deep-tbl">
        <thead><tr>{t.headers.map(h => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>
          {t.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className={
                  j === 0 ? "deep-tbl-lead"
                  : t.headers[j] === "Call" ? `mono ${_deepCallClass(cell)}`
                  : t.headers[j] === "Read" ? `mono ${_deepCallClass(cell.includes("Worse") ? "SHORT" : cell.includes("better") || cell.includes("Less restrictive") ? "LONG" : "")}`
                  : ""
                }>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeepCard({ r }) {
  const [open, setOpen] = useState(false);
  const hasDetail = (r.tables || []).length || (r.watchlists || []).length;

  return (
    <article className="deep-card">
      <div className="mono muted small">
        {r.date}{r.updated && r.updated !== r.date ? ` · rev ${r.updated}` : ""}
      </div>
      <h3 className="deep-card-title">{r.title}</h3>
      {r.verdict && <div className="deep-card-verdict mono">{r.verdict}</div>}
      {r.summary && <p className="deep-card-summary">{r.summary}</p>}

      {/* Projections — the headline payload, always visible */}
      {(r.projections || []).length > 0 && (
        <div className="deep-tbl-wrap">
          <div className="deep-tbl-title mono">Projections — 12 months, and why</div>
          <table className="deep-tbl deep-proj">
            <thead><tr><th>Prob.</th><th>Scenario</th><th>Target</th><th>Why</th></tr></thead>
            <tbody>
              {r.projections.map((p, i) => (
                <tr key={i}>
                  <td className="deep-proj-prob mono">{p.prob}</td>
                  <td className="deep-tbl-lead">{p.name}</td>
                  <td className="mono">{p.target}</td>
                  <td className="deep-proj-why">{p.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="deep-card-tags">
        {(r.tags || []).map(t => <span key={t} className="deep-tag mono">{t}</span>)}
      </div>

      <div className="deep-card-actions">
        {r.html && <a className="deep-btn" href={`deep/${r.html}`} target="_blank" rel="noopener">Open dossier ↗</a>}
        {r.link && <a className="deep-btn" href={r.link} target="_blank" rel="noopener">{r.link_label || "Open ↗"}</a>}
        {r.pdf && <a className="deep-btn deep-btn-ghost" href={`deep/${r.pdf}`} target="_blank" rel="noopener" title={r.pdf_note || ""}>PDF</a>}
        {hasDetail && (
          <button className="deep-btn deep-btn-ghost" onClick={() => setOpen(o => !o)}>
            {open ? "Hide detail ▴" : "Full detail ▾"}
          </button>
        )}
      </div>

      {open && (
        <div className="deep-detail">
          {(r.tables || []).map((t, i) => <DeepTable key={i} t={t} />)}
          {(r.watchlists || []).length > 0 && (
            <div className="deep-watch-grid">
              {r.watchlists.map((w, i) => (
                <div key={i} className={`deep-watch deep-watch-${w.tone || "neutral"}`}>
                  <div className="deep-tbl-title mono">{w.title}</div>
                  <ul className="deep-watch-list">
                    {w.items.map((it, j) => <li key={j}>{it}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
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
  const [tab, setTab]                 = useState("themes");

  const TABS = [
    { key: "themes",   num: "S1",  label: "Themes",   sub: "sectors · macro narratives · regimes" },
    { key: "assets",   num: "S1b", label: "Assets",   sub: "per-ticker chatter · same lifecycle × direction frame" },
    { key: "trusted",  num: "S6",  label: "Trusted",  sub: "conviction picks · T0/T1 authors" },
    { key: "concepts", num: "S2",  label: "Concepts", sub: "new this week · high velocity · low item count" },
    { key: "graph",    num: "S3",  label: "Graph",    sub: "source graph · echo ties" },
    { key: "feed",     num: "S4",  label: "Feed",     sub: "per-source feed" },
    { key: "manual",   num: "S5",  label: "Manual",   sub: "KOL captures from /04 inbox" },
    { key: "deep",     num: "S7",  label: "Deep",     sub: "long-form dossiers · deep-set analysis" },
  ];
  const activeTab = TABS.find(t => t.key === tab) || TABS[0];

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

      {/* ── Tab bar ─────────────────────────────────────────────────── */}
      <div className="streams-tabs" role="tablist">
        {TABS.map(t => (
          <button key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`streams-tab ${tab === t.key ? "on" : ""}`}
            onClick={() => setTab(t.key)}>
            <span className="streams-tab-num mono">{t.num}</span>
            <span className="streams-tab-label">{t.label}</span>
          </button>
        ))}
      </div>
      <div className="streams-tab-sub mono muted small">
        {activeTab.sub}
      </div>

      {/* ── S1 Themes ───────────────────────────────────────────────── */}
      {tab === "themes" && (
        <section className="block block-quiet">
          <div className="block-body" style={{ paddingTop: 14, paddingBottom: 14 }}>
            <ThemeMap themeMap={s.themeMap || []} onThemeClick={t => setOpenTheme(t)} />
          </div>
        </section>
      )}

      {/* ── S1b Assets ──────────────────────────────────────────────── */}
      {tab === "assets" && (
        <section className="block block-quiet">
          <div className="block-body" style={{ paddingTop: 14, paddingBottom: 14 }}>
            <ThemeMap themeMap={s.assetMap || []} onThemeClick={t => setOpenTheme(t)} />
          </div>
        </section>
      )}

      {/* ── S6 Trusted sources (rendered from inbox.jsx global) ─────── */}
      {tab === "trusted" && (
        window.TrustedSourceThemes
          ? React.createElement(window.TrustedSourceThemes)
          : <div className="empty-state mono muted" style={{ padding: "1rem" }}>Trusted-sources panel not loaded.</div>
      )}

      {/* ── S2 Emerging concepts ────────────────────────────────────── */}
      {tab === "concepts" && (
        <section className="block block-quiet">
          <header className="block-head">
            <div className="cc-header-criteria mono small muted">
              novelty &gt; 0.7 · velocity &gt; 0.4
            </div>
          </header>
          <div className="block-body" style={{ paddingTop: 14 }}>
            <ConceptsCards concepts={s.concepts || []} />
          </div>
        </section>
      )}

      {/* ── S3 Source graph ─────────────────────────────────────────── */}
      {tab === "graph" && (
        <section className="block block-quiet">
          <div className="block-body" style={{ paddingTop: 14, paddingBottom: 14 }}>
            <SourceGraph
              sourceGraph={s.sourceGraph || { nodes: [], links: [] }}
              onNodeClick={n => setOpenSrc(n)}
            />
          </div>
        </section>
      )}

      {/* ── S4 Per-source feed ──────────────────────────────────────── */}
      {tab === "feed" && (
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
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
      )}

      {/* ── S5 Manual drops ─────────────────────────────────────────── */}
      {tab === "manual" && (
        <section className="block block-quiet">
          <div className="block-body" style={{ paddingTop: 12 }}>
            <ManualDrops />
          </div>
        </section>
      )}

      {/* ── S7 Deep Analysis dossiers ───────────────────────────────── */}
      {tab === "deep" && (
        <section className="block block-quiet">
          <div className="block-body" style={{ paddingTop: 12 }}>
            <DeepAnalysis />
          </div>
        </section>
      )}

      {/* S1 theme drilldown */}
      <DrillSheet open={!!openTheme} onClose={() => setOpenTheme(null)}
        title={openTheme ? openTheme.label : ""}
        subtitle={openTheme ? `${
          openTheme.primary_data && openTheme.primary_data.current
            ? `${openTheme.primary_data.current.level.toFixed(2)}% · ${openTheme.primary_data.current.action}${openTheme.primary_data.expected_market ? ` · mkt ${openTheme.primary_data.expected_market.market_lean}` : ""}`
            : openTheme.primary_data && openTheme.primary_data.market
            ? `${openTheme.primary_data.market.asset} $${Math.round(openTheme.primary_data.market.price).toLocaleString()} · ${openTheme.primary_data.market.trend}`
            : openTheme.theme_kind === "macro_factor"
              ? `${openTheme.factor_state || "neutral"} → ${openTheme.market_impact || "mixed"}`
              : openTheme.direction
        } · ${openTheme.age_days}d old` : ""}>
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
