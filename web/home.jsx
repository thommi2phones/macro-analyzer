// /home — macro dashboard homepage.
//
// Top-of-desk overview: framework regime + macro indicators (compact) +
// a grid of asset categories (monetary, indices, crypto, commodities)
// each showing 4–6 tickers with price, day change, and sentiment. This
// is the macro-context landing page — positioning trades come after.

function Home({ onNav }) {
  const D = window.MA_DATA || {};
  const home = D.macroHome || { categories: [] };
  const regime = D.regime || null;

  return (
    <div className="home-view">
      {regime && <RegimeTape regime={regime} />}
      {regime && <RegimeTimelineChart regime={regime} />}
      {regime && regime.indicators && (
        <MacroIndicatorStrip ind={regime.indicators} />
      )}

      <div className="home-meta mono small muted">
        Macro tape · updated {home.asOf || "—"}
      </div>

      <div className="home-cats">
        {home.categories.map(cat => (
          <HomeCategory key={cat.key} cat={cat} onNav={onNav} />
        ))}
      </div>
    </div>
  );
}

// Regime timeline chart — horizontal band over the last N days of the
// confidence trace, with the trace overlaid as a line. Regime periods
// are inferred from `regime.transitions` (each entry is a change point).
function RegimeTimelineChart({ regime }) {
  const trace = regime.confidenceTrace || [];
  const n = trace.length;
  if (!n) return null;

  // Detect stub data: backend seeds confidenceTrace as [confidence]*84 until
  // a daily regime-snapshot table is wired up. If variance is ~0, don't
  // draw a misleading flat line — surface the pipeline gap instead.
  const traceMin = Math.min.apply(null, trace);
  const traceMax = Math.max.apply(null, trace);
  const traceIsStub = (traceMax - traceMin) < 0.02;

  if (traceIsStub) {
    return (
      <section className="block home-timeline">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">RG</span>
            <span>Regime timeline · last 90d</span>
            <span className="block-sub">
              current: <b>{regime.framework?.label || "—"}</b> · {Math.round((regime.framework?.confidence || 0) * 100)}% confidence
            </span>
          </div>
        </header>
        <div className="home-timeline-pending mono small muted">
          regime history not yet persisted — backend emits a flat confidence trace and one
          stub transition until a daily regime-snapshot writer lands (see
          <code> desk_data.build_regime_section</code>). The current framework read above is live;
          the 90-day chart will appear once daily snapshots accumulate.
        </div>
        {regime.transitions && regime.transitions.length > 0 && (
          <div className="home-timeline-transitions mono small muted">
            latest transition on record:&nbsp;
            <b>{regime.transitions[regime.transitions.length - 1].date}</b>
            {" · "}
            {regime.transitions[regime.transitions.length - 1].from}
            {" → "}
            {regime.transitions[regime.transitions.length - 1].to}
          </div>
        )}
      </section>
    );
  }

  const W = 900, H = 130;
  const padL = 8, padR = 8, padT = 28, padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  // Build regime periods: transitions give change points; treat the
  // pre-first-transition period as `transitions[0].from` and the tail
  // as the current framework label.
  const trans = (regime.transitions || []).slice();
  const currentLabel = regime.framework?.label || "—";
  const segments = [];
  if (!trans.length) {
    segments.push({ startIdx: 0, endIdx: n - 1, label: currentLabel });
  } else {
    // Space transition indices evenly across the trace as a proxy — the
    // real dates aren't tied to trace indices, so we render "approximate
    // segmentation" and label it as such in the axis strip.
    const anchors = trans.map((_, i) => Math.round(((i + 1) / (trans.length + 1)) * n));
    let cursor = 0;
    trans.forEach((t, i) => {
      const end = anchors[i];
      segments.push({ startIdx: cursor, endIdx: end, label: t.from });
      cursor = end;
    });
    segments.push({ startIdx: cursor, endIdx: n - 1, label: currentLabel });
  }

  const colorFor = (label) => {
    const s = (label || "").toLowerCase();
    if (s.includes("commodity")) return "var(--gold, #b0862f)";
    if (s.includes("dovish") || s.includes("liquidity")) return "var(--blue, #2b5ce6)";
    if (s.includes("risk-off") || s.includes("contraction")) return "var(--red, #cf5346)";
    if (s.includes("transitional") || s.includes("chop")) return "var(--text-mute-2, #8d897c)";
    return "var(--text-mute, #5f5c52)";
  };

  const pathD = trace.map((v, i) => {
    const x = padL + (i / (n - 1)) * plotW;
    const y = padT + (1 - v) * plotH;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  // Current confidence — the last data point
  const currentConf = trace[n - 1];

  return (
    <section className="block home-timeline">
      <header className="block-head">
        <div className="block-title">
          <span className="block-num mono">RG</span>
          <span>Regime timeline · last 90d</span>
          <span className="block-sub">
            confidence trace overlaid on approximate regime segmentation ·
            {" "}{segments.length} regime{segments.length === 1 ? "" : "s"} · now
            {" "}<b>{Math.round(currentConf * 100)}%</b>
          </span>
        </div>
      </header>
      <div className="home-timeline-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="home-timeline-svg">
          {/* Regime bands (background) */}
          {segments.map((seg, i) => {
            const x = padL + (seg.startIdx / (n - 1)) * plotW;
            const w = ((seg.endIdx - seg.startIdx) / (n - 1)) * plotW;
            const c = colorFor(seg.label);
            return (
              <g key={i}>
                <rect x={x} y={padT} width={Math.max(1, w)} height={plotH} fill={c} opacity="0.14" />
                <line x1={x} y1={padT} x2={x} y2={padT + plotH} stroke="var(--line-2)" strokeWidth="1" />
                <text x={x + 6} y={padT + 14} fontFamily="var(--mono)" fontSize="10.5" fill={c} fontWeight="600" style={{ letterSpacing: "0.04em" }}>
                  {seg.label.toUpperCase()}
                </text>
              </g>
            );
          })}
          {/* Confidence trace */}
          <path d={pathD} fill="none" stroke="var(--accent, #b0862f)" strokeWidth="1.75" strokeLinejoin="round" />
          {/* Endpoint dot */}
          {(() => {
            const x = padL + plotW;
            const y = padT + (1 - currentConf) * plotH;
            return <circle cx={x} cy={y} r="3.5" fill="var(--accent, #b0862f)" />;
          })()}
          {/* Y-axis ticks (0 / 50 / 100) */}
          {[0, 0.5, 1].map(v => {
            const y = padT + (1 - v) * plotH;
            return (
              <g key={v}>
                <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--line-soft)" strokeDasharray="2 3" />
                <text x={W - padR - 4} y={y - 3} fontFamily="var(--mono)" fontSize="9" fill="var(--text-mute-2)" textAnchor="end">
                  {Math.round(v * 100)}%
                </text>
              </g>
            );
          })}
          {/* X-axis: start / today */}
          <text x={padL} y={H - 6} fontFamily="var(--mono)" fontSize="10" fill="var(--text-mute-2)">−90d</text>
          <text x={W - padR} y={H - 6} fontFamily="var(--mono)" fontSize="10" fill="var(--text-mute-2)" textAnchor="end">now</text>
        </svg>
      </div>
      {regime.transitions && regime.transitions.length > 0 && (
        <div className="home-timeline-transitions mono small muted">
          {regime.transitions.map((t, i) => (
            <span key={i}>
              <b>{t.date}</b> · {t.from} → {t.to}
              {i < regime.transitions.length - 1 ? "   ·   " : ""}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function HomeCategory({ cat, onNav }) {
  return (
    <section className="block home-cat-block">
      <header className="block-head">
        <div className="block-title">
          <span className="block-num mono">{cat.key.slice(0, 2).toUpperCase()}</span>
          <span>{cat.label}</span>
          <span className="block-sub">{cat.blurb}</span>
        </div>
      </header>
      <div className="home-cat-grid">
        {(cat.assets || []).map(a => (
          <HomeAssetCard key={a.asset} a={a} />
        ))}
      </div>
    </section>
  );
}

function HomeAssetCard({ a }) {
  const chg = a.chgPct || 0;
  const chg30 = a.chg30dPct || 0;
  const dir = chg > 0 ? "pos" : chg < 0 ? "neg" : "muted";
  const dir30 = chg30 > 0 ? "pos" : chg30 < 0 ? "neg" : "muted";
  const sentimentClass = `home-sent home-sent-${a.sentiment || "neutral"}`;
  const isRate = (a.unit || "") === "%";
  const isPct = (a.unit || "") === "%" || (a.unit || "") === "z";
  const valStr = isRate
    ? `${a.value.toFixed(2)}%`
    : (a.unit ? `${_fmtValue(a.value)}${a.unit}` : _fmtValue(a.value));
  return (
    <div className="home-card">
      <div className="home-card-head">
        <span className="home-card-ticker mono">{a.asset}</span>
        <span className={sentimentClass}>{a.sentiment || "neutral"}</span>
      </div>
      <div className="home-card-name">{a.name}</div>
      <div className="home-card-val mono">{valStr}</div>
      <div className="home-card-chg mono">
        <span className={`home-chg ${dir}`}>{chg >= 0 ? "+" : ""}{chg.toFixed(isPct ? 3 : 2)}%</span>
        <span className="home-chg-sep muted">·</span>
        <span className={`home-chg-30 ${dir30}`}>30d {chg30 >= 0 ? "+" : ""}{chg30.toFixed(1)}%</span>
      </div>
      {a.note && <div className="home-card-note">{a.note}</div>}
    </div>
  );
}

function _fmtValue(v) {
  if (v == null) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (Math.abs(n) >= 10000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (Math.abs(n) >= 100)   return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (Math.abs(n) >= 10)    return n.toFixed(2);
  return n.toFixed(3);
}

Object.assign(window, { Home });
