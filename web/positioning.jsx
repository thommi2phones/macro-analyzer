// /positioning — trader desk view.

const { useState: useStateP, useMemo: useMemoP } = React;

function Positioning({ onOpenReasoning, onOpenTradeForm, onAdvanceToConcept }) {
  const D = window.MA_DATA;
  const [filter, setFilter] = useStateP("ALL");
  const [tierFilter, setTierFilter] = useStateP("ALL");
  const [regimeFilter, setRegimeFilter] = useStateP("ALL");
  const [wlQ, setWlQ] = useStateP("");
  const [sortBy, setSortBy] = useStateP("score");
  const [sortDir, setSortDir] = useStateP("desc");
  const [, force] = useStateP(0);
  const rerender = () => force(n => n + 1);

  // Map of asset → active concept id so the watchlist row can show
  // "marked" instead of the "advance" button after a click. Recomputed
  // on every render so concept retirement on /concepts is reflected here.
  const activeConceptByAsset = useMemoP(() => {
    const m = {};
    for (const c of (D.concepts || [])) {
      if (c.status === "active") m[c.asset] = c.id;
    }
    return m;
  }, [D.concepts && D.concepts.length, sortBy, sortDir, filter]);

  const advanceToConcept = (row) => {
    if (activeConceptByAsset[row.asset]) {
      // Already marked — just navigate.
      if (onAdvanceToConcept) onAdvanceToConcept();
      return;
    }
    const id = `concept-${Date.now().toString(36)}`;
    D.concepts = (D.concepts || []).concat([{
      id,
      asset: row.asset,
      source: "watchlist_manual",
      status: "active",
      suggestedBySystem: false,
      suggestionReason: null,
      scoreAtMark: row.score,
      tierAtMark: row.tier,
      sideAtMark: row.side,
      thesis: "",
      markedAt: new Date().toISOString().slice(0, 16).replace("T", " "),
      tradePlanId: null,
    }]);
    rerender();
    if (onAdvanceToConcept) onAdvanceToConcept();
  };

  // ── Watchlist filtering + sorting ────────────────────────────
  const watchlist = useMemoP(() => {
    let rows = D.watchlist.slice();
    if (filter === "ACTIONABLE") rows = rows.filter(r => r.score >= 70);
    if (filter === "T1") rows = rows.filter(r => r.tier === 1);
    if (filter === "LONG") rows = rows.filter(r => r.side === "LONG");
    if (filter === "SHORT") rows = rows.filter(r => r.side === "SHORT");
    if (tierFilter !== "ALL") rows = rows.filter(r => String(r.tier) === tierFilter.replace("T", ""));
    if (regimeFilter !== "ALL") rows = rows.filter(r => r.regime === regimeFilter);
    if (wlQ.trim()) {
      const q = wlQ.toLowerCase();
      rows = rows.filter(r =>
        r.asset.toLowerCase().includes(q) ||
        (r.name || "").toLowerCase().includes(q) ||
        (r.assetClass || "").toLowerCase().includes(q)
      );
    }
    rows.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      if (typeof av === "number") return sortDir === "desc" ? bv - av : av - bv;
      return sortDir === "desc" ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    });
    return rows;
  }, [filter, tierFilter, regimeFilter, wlQ, sortBy, sortDir]);

  const sortToggle = (col) => () => {
    if (sortBy === col) setSortDir(sortDir === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortDir("desc"); }
  };

  return (
    <div className="positioning-view">

      {/* ── Regime tape (sticky) ─────────────────────────── */}
      <RegimeTape regime={D.regime} />

      {/* ── Macro indicator tiles ────────────────────────── */}
      {D.regime.indicators && <MacroIndicatorStrip ind={D.regime.indicators} />}

      {/* ── Data-freshness strip ─────────────────────────── */}
      {D.dataHealth && D.dataHealth.sources && D.dataHealth.sources.length > 0 && (
        <DataFreshnessStrip dh={D.dataHealth} />
      )}

      {/* KPI strip rendered by app shell — single source of truth */}

      {/* ── Live signals (direct from extractors, last 72h) ─ */}
      {Array.isArray(D.liveSignals) && D.liveSignals.length > 0 && (
        <LiveSignalsPanel signals={D.liveSignals} />
      )}

      {/* ── Hero signals ────────────────────────────────── */}
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">01</span>
            <span>Hero signals</span>
            <span className="block-sub">today's highest-conviction setups · click for reasoning trail</span>
          </div>
          <div className="block-actions">
            <span className="dot-live"></span>
            <span className="block-meta mono">refreshed 08:14:22 · next 08:29</span>
          </div>
        </header>
        <div className="hero-grid hero-grid-4">
          {D.heroSignals.slice(0, 4).map(s => (
            <SetupCard key={s.id} s={s} onOpen={onOpenReasoning} />
          ))}
        </div>
      </section>

      {/* ── Watchlist (active trades + log moved to /live) ─ */}
      <section>
        <div className="block">
          <header className="block-head">
            <div className="block-title">
              <span className="block-num mono">02</span>
              <span>Watchlist · scored</span>
              <span className="block-sub">
                {watchlist.length} of {D.watchlist.length}
                {(filter !== "ALL" || tierFilter !== "ALL" || regimeFilter !== "ALL" || wlQ.trim()) ? " · filtered" : ""}
                {" · sort "}{sortBy} {sortDir === "desc" ? "↓" : "↑"}
              </span>
            </div>
            <div className="block-actions wl-actions">
              <input className="src-search" placeholder="search ticker / name…"
                     value={wlQ} onChange={e => setWlQ(e.target.value)} />
              <div className="filter-pill-row" title="side / posture">
                {["ALL","ACTIONABLE","LONG","SHORT"].map(f => (
                  <button key={f} className={`filter-pill ${filter === f ? "on" : ""}`}
                          onClick={() => setFilter(f)}>{f}</button>
                ))}
              </div>
              <div className="filter-pill-row" title="tier">
                {["ALL","T1","T2","T3","T4"].map(f => (
                  <button key={f} className={`filter-pill ${tierFilter === f ? "on" : ""}`}
                          onClick={() => setTierFilter(f)}>{f}</button>
                ))}
              </div>
              <div className="filter-pill-row" title="regime fit">
                {[["ALL","regime: all"],["fit","fit"],["mix","mixed"],["off","off"]].map(([k, lbl]) => (
                  <button key={k} className={`filter-pill ${regimeFilter === k ? "on" : ""}`}
                          onClick={() => setRegimeFilter(k)}>{lbl}</button>
                ))}
              </div>
            </div>
          </header>
          <table className="wl-table">
            <thead>
              <tr>
                <th onClick={sortToggle("asset")} className="sortable">ASSET {sortBy === "asset" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("side")} className="sortable">SIDE {sortBy === "side" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("score")} className="sortable num">
                  SCORE {sortBy === "score" && (sortDir === "desc" ? "↓" : "↑")}
                </th>
                <th onClick={sortToggle("dScore")} className="sortable num">Δ 1D {sortBy === "dScore" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("tier")} className="sortable">TIER {sortBy === "tier" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("regime")} className="sortable">REGIME {sortBy === "regime" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("tech")} className="sortable num">TECH {sortBy === "tech" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("vol")} className="sortable num">VOL {sortBy === "vol" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("rr")} className="sortable num">R/R {sortBy === "rr" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th onClick={sortToggle("last")} className="sortable num">LAST {sortBy === "last" && (sortDir === "desc" ? "↓" : "↑")}</th>
                <th>FUNNEL</th>
              </tr>
            </thead>
            <tbody>
              {watchlist.map(r => {
                const marked = activeConceptByAsset[r.asset];
                return (
                <tr key={r.asset} className={`tier-row tier-${r.tier}`}>
                  <td className="mono asset-cell">{r.asset}</td>
                  <td><SideLabel side={r.side} /></td>
                  <td className="num">
                    <span className={`wl-score tier-${r.tier}`}>{r.score}</span>
                  </td>
                  <td className={`num ${r.dScore > 0 ? "pos" : r.dScore < 0 ? "neg" : "muted"}`}>
                    {r.dScore > 0 ? "+" : ""}{r.dScore}
                  </td>
                  <td><span className={`tier-dot tier-${r.tier}`}></span><span className="tier-num mono">T{r.tier}</span></td>
                  <td>
                    <span className={`reg-fit reg-${r.regime}`}>
                      {r.regime === "fit" ? "● fit" : r.regime === "mix" ? "◐ mixed" : "○ off"}
                    </span>
                  </td>
                  <td className="num">{r.tech}</td>
                  <td className="num">{r.vol}</td>
                  <td className="num">{r.rr.toFixed(2)}</td>
                  <td className="num muted">{r.last}</td>
                  <td>
                    {marked
                      ? <span className="status-chip status-active">● marked</span>
                      : <button className="btn-ghost xs" onClick={() => advanceToConcept(r)}>
                          advance →
                        </button>}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>

      </section>

    </div>
  );
}

// ── Macro indicator strip ──────────────────────────────────────
const _QUADRANT_COLOR = {
  boom:        "var(--gold)",
  goldilocks:  "var(--green)",
  stagflation: "var(--gold)",
  deflation:   "var(--red)",
  transitional:"var(--text-dim)",
};
const _FCI_COLOR = { tightening: "var(--red)", neutral: "var(--text-dim)", easing: "var(--green)" };
const _EPU_COLOR  = { elevated: "var(--red)", moderate: "var(--text-dim)", low: "var(--green)" };
const _COT_COLOR  = {
  extreme_long:  "var(--green)",
  elevated:      "var(--gold)",
  neutral:       "var(--text-dim)",
  suppressed:    "var(--gold)",
  extreme_short: "var(--red)",
};

function MacroIndicatorStrip({ ind }) {
  return (
    <div className="indicator-strip">
      <div className="ind-tile">
        <div className="ind-label">REGIME QUADRANT</div>
        <div className="ind-value" style={{ color: _QUADRANT_COLOR[ind.quadrant] || "var(--text)" }}>
          {(ind.quadrant || "—").toUpperCase()}
        </div>
        <div className="ind-sub">
          {ind.growthSignal} growth · {ind.inflationSignal} inflation ·{" "}
          <span className="mono">{ind.quadrantConf ? Math.round(ind.quadrantConf * 100) + "%" : "—"}</span> conf
        </div>
      </div>
      <div className="ind-tile">
        <div className="ind-label">FIN. CONDITIONS</div>
        <div className="ind-value" style={{ color: _FCI_COLOR[ind.fciLabel] || "var(--text)" }}>
          {(ind.fciLabel || "—").toUpperCase()}
        </div>
        <div className="ind-sub">
          FCI <span className="mono">{ind.fciScore != null ? (ind.fciScore >= 0 ? "+" : "") + ind.fciScore.toFixed(3) : "—"}</span>
        </div>
      </div>
      <div className="ind-tile">
        <div className="ind-label">GEO / POLICY RISK</div>
        <div className="ind-value" style={{ color: _EPU_COLOR[ind.epuLevel] || "var(--text)" }}>
          {(ind.epuLevel || "—").toUpperCase()}
        </div>
        <div className="ind-sub">
          EPU <span className="mono">{ind.epuComposite != null ? ind.epuComposite.toFixed(0) : "—"}</span>
          {ind.epuDriver ? <span className="muted"> · {ind.epuDriver.replace("EPU", "")}</span> : null}
        </div>
      </div>
      <div className="ind-tile">
        <div className="ind-label">COT POSITIONING</div>
        <div className="ind-value" style={{ color: _COT_COLOR[ind.cotTopSignal] || "var(--text-dim)" }}>
          {ind.cotTopSignal ? ind.cotTopSignal.replace(/_/g, " ").toUpperCase() : "—"}
        </div>
        <div className="ind-sub">
          <span className="mono">{ind.cotExtremesCount != null ? ind.cotExtremesCount : "—"}</span> extreme{ind.cotExtremesCount !== 1 ? "s" : ""}
          {ind.cotTopMarket ? <span className="muted"> · {ind.cotTopMarket}</span> : null}
          {ind.cotTopNetPctOi != null ? <span className="muted"> {ind.cotTopNetPctOi >= 0 ? "+" : ""}{ind.cotTopNetPctOi.toFixed(1)}%</span> : null}
        </div>
      </div>
    </div>
  );
}

// ── Regime tape ────────────────────────────────────────────────
function RegimeTape({ regime }) {
  const f = regime.framework, t = regime.thesis;
  const color = f.slug === "commodity_led_inflation" ? "var(--gold)"
              : f.slug === "dovish_liquidity_wave" ? "var(--accent)"
              : f.slug === "risk_off_contraction" ? "var(--red)"
              : "var(--text-dim)";
  return (
    <section className="regime-tape">
      <div className="rt-left">
        <div className="rt-kind">FRAMEWORK REGIME</div>
        <div className="rt-name">
          <span className="rt-dot" style={{ background: color }}></span>
          {f.label}
        </div>
        <div className="rt-meta">
          <span>active {f.sinceDays}d</span>
          <span className="sep">·</span>
          <span>bias <b>{f.bias.replace(/_/g, " ")}</b></span>
          <span className="sep">·</span>
          <span>size mod <b className="mono">×{f.sizingModifier.toFixed(2)}</b></span>
          <span className="sep">·</span>
          <span>score mod <b className="mono">{f.scoreModifier > 0 ? "+" : ""}{f.scoreModifier}</b></span>
        </div>
      </div>

      <div className="rt-mid">
        <div className="rt-kind">THESIS · {t.version} · {t.author}</div>
        <div className="rt-thesis">{t.narrative}</div>
        <div className="rt-meta muted">last revised {t.lastRevised}</div>
      </div>

      <div className="rt-right">
        <div className="rt-conf">
          <div className="rt-conf-label">CONFIDENCE 90D</div>
          <div className="rt-conf-row">
            <span className="rt-conf-num mono gold">{Math.round(f.confidence * 100)}<span className="muted">%</span></span>
            <Sparkline data={regime.confidenceTrace} width={140} height={36} color={color} />
          </div>
          <div className="rt-tx muted mono">
            {regime.transitions[regime.transitions.length - 1].date} ·
            {" "}{regime.transitions[regime.transitions.length - 1].from} → {regime.transitions[regime.transitions.length - 1].to}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Active trades ──────────────────────────────────────────────
function ActiveTradesPanel({ trades }) {
  return (
    <div className="block">
      <header className="block-head sm">
        <div className="block-title">
          <span className="block-num mono">03</span>
          <span>Active trades</span>
          <span className="block-sub">{trades.length} open · refreshed 5min</span>
        </div>
      </header>
      <div className="trades-list">
        {trades.map(t => {
          const distToStop = t.side === "LONG"
            ? ((t.entry - t.stop) / t.entry) * 100
            : ((t.stop - t.entry) / t.entry) * 100;
          const scoreD = t.scoreNow - t.scoreAtOpen;
          return (
            <div key={t.id} className={`trade-row status-${t.status}`}>
              <div className="tr-asset">
                <div className="tr-asset-name mono">{t.asset}</div>
                <SideLabel side={t.side} />
              </div>
              <div className="tr-levels">
                <div className="tr-l">
                  <span className="tr-l-lbl">entry</span>
                  <span className="mono">{t.entry < 1000 ? t.entry.toFixed(2) : t.entry.toLocaleString()}</span>
                </div>
                <div className="tr-l">
                  <span className="tr-l-lbl">stop</span>
                  <span className="mono">{t.stop < 1000 ? t.stop.toFixed(2) : t.stop.toLocaleString()}</span>
                </div>
                <div className="tr-l">
                  <span className="tr-l-lbl">target</span>
                  <span className="mono">{t.target < 1000 ? t.target.toFixed(2) : t.target.toLocaleString()}</span>
                </div>
              </div>
              <div className="tr-score">
                <span className="tr-l-lbl">score</span>
                <div>
                  <span className="mono muted">{t.scoreAtOpen}→</span>
                  <span className="mono">{t.scoreNow}</span>
                  <span className={`mono ${scoreD > 0 ? "pos" : scoreD < 0 ? "neg" : "muted"}`}>
                    {" "}{scoreD > 0 ? "+" : ""}{scoreD}
                  </span>
                </div>
              </div>
              <div className="tr-pnl">
                <PnL usd={t.pnlUsd} pct={t.pnlPct} size="sm" />
                <span className="tr-age muted mono">{t.ageDays}d</span>
              </div>
              <div className="tr-status">
                {t.status === "near_invalidation" && <span className="tr-warn">⚠ near stop</span>}
                {t.status === "watch" && <span className="tr-warn warn">◌ watch</span>}
                {t.status === "running" && <span className="tr-ok">● running</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Trade log inline form ──────────────────────────────────────
function TradeLogPanel({ onSubmit }) {
  const [tab, setTab] = useStateP("log");
  const [asset, setAsset] = useStateP("URA");
  const [entry, setEntry] = useStateP("");
  const [stop, setStop] = useStateP("");
  const [size, setSize] = useStateP("");
  const [submitted, setSubmitted] = useStateP(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    setSubmitted(true);
    setTimeout(() => setSubmitted(false), 1800);
  };

  return (
    <div className="block">
      <header className="block-head sm">
        <div className="block-title">
          <span className="block-num mono">04</span>
          <span>Trade log</span>
          <span className="block-sub">manual entry · one-tap fast</span>
        </div>
        <div className="tab-row">
          <button className={`tab ${tab === "log" ? "on" : ""}`} onClick={() => setTab("log")}>Log entry</button>
          <button className={`tab ${tab === "close" ? "on" : ""}`} onClick={() => setTab("close")}>Close trade</button>
        </div>
      </header>
      <form className="log-form" onSubmit={handleSubmit}>
        {tab === "log" ? (
          <>
            <div className="form-row">
              <label>
                <span className="form-lbl">ASSET</span>
                <input className="form-input mono" value={asset} onChange={e => setAsset(e.target.value.toUpperCase())} placeholder="URA" />
              </label>
              <label>
                <span className="form-lbl">SIDE</span>
                <div className="seg">
                  <button type="button" className="seg-on">LONG</button>
                  <button type="button">SHORT</button>
                </div>
              </label>
            </div>
            <div className="form-row">
              <label>
                <span className="form-lbl">ENTRY</span>
                <input className="form-input mono" value={entry} onChange={e => setEntry(e.target.value)} placeholder="41.20" inputMode="decimal" />
              </label>
              <label>
                <span className="form-lbl">STOP</span>
                <input className="form-input mono" value={stop} onChange={e => setStop(e.target.value)} placeholder="39.40" inputMode="decimal" />
              </label>
              <label>
                <span className="form-lbl">SIZE $</span>
                <input className="form-input mono" value={size} onChange={e => setSize(e.target.value)} placeholder="32000" inputMode="decimal" />
              </label>
            </div>
            <div className="form-row">
              <label className="grow">
                <span className="form-lbl">LINK SETUP (optional)</span>
                <select className="form-input">
                  <option>sig-ura-2605 · URA · 88</option>
                  <option>sig-gld-2605 · GLD · 84</option>
                  <option>sig-xop-2605 · XOP · 78</option>
                  <option>(none)</option>
                </select>
              </label>
            </div>
          </>
        ) : (
          <>
            <div className="form-row">
              <label className="grow">
                <span className="form-lbl">CLOSE WHICH TRADE</span>
                <select className="form-input">
                  <option>t-2026-019 · URA · +6.42%</option>
                  <option>t-2026-018 · GLD · +2.75%</option>
                  <option>t-2026-017 · XOP · +1.81%</option>
                </select>
              </label>
              <label>
                <span className="form-lbl">EXIT</span>
                <input className="form-input mono" placeholder="42.10" inputMode="decimal" />
              </label>
            </div>
            <div className="form-row">
              <label>
                <span className="form-lbl">WAS IT THE THESIS?</span>
                <div className="seg seg-3">
                  <button type="button" className="seg-on">YES</button>
                  <button type="button">PARTIAL</button>
                  <button type="button">NO</button>
                </div>
              </label>
            </div>
            <div className="form-row">
              <label className="grow">
                <span className="form-lbl">LESSON · ONE LINE</span>
                <input className="form-input" placeholder="Held through 50DMA wobble — paid off." />
              </label>
            </div>
          </>
        )}
        <div className="form-actions">
          <button type="submit" className="btn-primary">{tab === "log" ? "Log trade ↵" : "Close & log lesson ↵"}</button>
          {submitted && <span className="form-ok">✓ logged · brain weights updating</span>}
        </div>
      </form>
    </div>
  );
}

// ── Data freshness strip ────────────────────────────────────────────────
// One chip per input/output source showing green/yellow/red based on
// how long since the last update. Lets the operator spot a stalled
// pipeline at a glance — no more silent-zero dashboards.
function DataFreshnessStrip({ dh }) {
  const sources = dh.sources || [];
  function fmtAge(min) {
    if (min == null) return "—";
    if (min < 60) return `${Math.round(min)}m`;
    if (min < 24 * 60) return `${Math.round(min / 60)}h`;
    return `${Math.round(min / (60 * 24))}d`;
  }
  const colorFor = {
    green: { bg: "rgba(60,160,80,0.15)", fg: "#7dd87d", dot: "#4caf50" },
    yellow: { bg: "rgba(200,160,40,0.18)", fg: "#e0c060", dot: "#e0a020" },
    red: { bg: "rgba(200,80,80,0.18)", fg: "#e07070", dot: "#cc3030" },
  };
  return (
    <div className="data-freshness-strip" style={{
      display: "flex", flexWrap: "wrap", gap: 8,
      padding: "8px 14px", marginBottom: 12,
      fontSize: 11, fontFamily: "monospace",
      borderTop: "1px solid #222", borderBottom: "1px solid #222",
    }}>
      <span style={{ color: "#888", marginRight: 8 }}>SOURCES ·</span>
      {sources.map(s => {
        const c = colorFor[s.status] || colorFor.red;
        return (
          <span key={s.key} title={s.last_ts || "never"}
                style={{
                  background: c.bg, color: c.fg,
                  padding: "2px 8px", borderRadius: 3,
                  display: "inline-flex", alignItems: "center", gap: 5,
                }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%",
              background: c.dot, display: "inline-block",
            }} />
            {s.label}
            <span style={{ opacity: 0.7 }}>
              · {fmtAge(s.minutes_since)}
              {s.docs_today > 0 ? ` · ${s.docs_today} today` : ""}
            </span>
          </span>
        );
      })}
    </div>
  );
}

// ── Live signals panel ──────────────────────────────────────────────────
// Reads directly from the signals table — visible BEFORE a scoring pass
// rolls them into trade_scores. So the positioning desk surfaces real
// extracted intelligence within seconds of ingestion.
function LiveSignalsPanel({ signals }) {
  function fmtAge(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      const m = (Date.now() - d.getTime()) / 60000;
      if (m < 60) return `${Math.round(m)}m`;
      if (m < 24 * 60) return `${Math.round(m / 60)}h`;
      return `${Math.round(m / (60 * 24))}d`;
    } catch (e) { return "—"; }
  }
  const sideKind = (side) => {
    const s = (side || "").toUpperCase();
    if (s === "LONG" || s === "ADD") return "long";
    if (s === "SHORT" || s === "HEDGE") return "short";
    if (s === "EXIT" || s === "TRIM") return "trim";
    return "watch";
  };
  return (
    <section className="block live-signals-block">
      <header className="block-head">
        <div className="block-title">
          <span className="block-num mono">01a</span>
          <span>Live signals</span>
          <span className="block-sub">
            top {signals.length} extracted in the last 72h ·
            direct from manual / insider / vision / LLM extractors
          </span>
        </div>
      </header>
      <div className="live-signals-grid">
        {signals.map(s => (
          <div key={s.signal_id} className={`live-signal-card side-${sideKind(s.side)}`}>
            <div className="ls-head">
              <span className="ls-ticker">{s.ticker}</span>
              <span className={`ls-side ls-side-${sideKind(s.side)} mono`}>
                {s.side} · conv {s.conviction != null ? s.conviction.toFixed(1) : "—"}
              </span>
            </div>
            <div className="ls-meta mono">
              {[
                s.extractor_name,
                s.source_channel || s.source_slug,
                s.horizon,
                s.catalyst_type,
                fmtAge(s.extracted_at) + " ago",
              ].filter(Boolean).join(" · ")}
            </div>
            {s.thesis_summary && (
              <div className="ls-thesis">{s.thesis_summary}</div>
            )}
            {(s.stop_loss != null || s.target_1 != null) && (
              <div className="ls-levels mono">
                {s.stop_loss != null && <>stop {s.stop_loss}</>}
                {s.stop_loss != null && s.target_1 != null && " · "}
                {s.target_1 != null && <>tgt {s.target_1}</>}
                {s.target_2 != null && <> / {s.target_2}</>}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

Object.assign(window, { Positioning, RegimeTape, DataFreshnessStrip, LiveSignalsPanel });
