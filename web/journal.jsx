// /journal — review desk view.

// ─── 7-question framework: locked enum sets (mirror brief + backend) ───
const THESIS_VALIDITY_OPTS = [
  { value: "fully_right",                 label: "Fully right" },
  { value: "right_outcome_wrong_reason",  label: "Right outcome · wrong reason" },
  { value: "right_thesis_wrong_outcome",  label: "Right thesis · wrong outcome" },
  { value: "fully_wrong",                 label: "Fully wrong" },
];
const HINDSIGHT_OPTS = [
  { value: "over",  label: "Scored too high" },
  { value: "right", label: "About right" },
  { value: "under", label: "Scored too low" },
];
const SURPRISE_OPTS = [
  { value: "macro",         label: "Macro" },
  { value: "sector",        label: "Sector" },
  { value: "liquidity",     label: "Liquidity" },
  { value: "idiosyncratic", label: "Idiosyncratic" },
  { value: "none",          label: "No surprise" },
];
const RETAKE_OPTS = [
  { value: "yes",      label: "Yes, same way" },
  { value: "modified", label: "Yes, modified" },
  { value: "no",       label: "No" },
];
const EXEC_LIKERT_LABELS = ["bad", "", "ok", "", "great"];

function Journal() {
  const D = window.MA_DATA;
  const [scope, setScope] = React.useState("30d");

  // Pending reviews: local list so submit removes optimistically.
  const [pending, setPending] = React.useState(() => D.pendingReviews || []);
  const [reviewing, setReviewing] = React.useState(null);
  // Lessons library: prepend submitted ones locally for dev demo.
  const [lessons, setLessons] = React.useState(() => D.lessonsLibrary || []);

  const onReviewSubmitted = (trade, payload) => {
    setPending(prev => prev.filter(t => t.trade_id !== trade.trade_id));
    setLessons(prev => [
      {
        trade_id: trade.trade_id,
        ticker: trade.ticker,
        completedAt: new Date().toISOString(),
        pnlPct: trade.pnlPct,
        thesisValidity: payload.thesis_validity,
        lesson: payload.lesson,
        executionScores: payload.execution_scores,
        surpriseFactor: payload.surprise_factor,
        wouldRetake: payload.would_retake,
        sourcesCredited: payload.sources_credited,
      },
      ...prev,
    ]);
  };

  const closed = D.closedTrades;
  const wins = closed.filter(t => t.pnlPct > 0).length;
  const winRate = (wins / closed.length) * 100;
  const avgPnl = closed.reduce((s, t) => s + t.pnlPct, 0) / closed.length;
  const grossPos = closed.filter(t => t.pnlPct > 0).reduce((s, t) => s + t.pnlPct, 0);
  const grossNeg = Math.abs(closed.filter(t => t.pnlPct < 0).reduce((s, t) => s + t.pnlPct, 0));
  const profitFactor = grossNeg > 0 ? grossPos / grossNeg : 0;

  return (
    <div className="journal-view">
      <PendingReviewsStrip pending={pending} onPick={setReviewing} />
      <ReviewModal
        trade={reviewing}
        onClose={() => setReviewing(null)}
        onSubmitted={onReviewSubmitted}
      />
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">J1</span>
            <span>Process scorecard · {D.processScorecard.days}d</span>
            <span className="block-sub">was the process clean — independent of outcome</span>
          </div>
          <div className="block-actions">
            <div className="filter-pill-row">
              {["7d","30d","90d","ALL"].map(s => (
                <button key={s} className={`filter-pill ${scope === s ? "on" : ""}`} onClick={() => setScope(s)}>{s}</button>
              ))}
            </div>
          </div>
        </header>
        <div className="ps-grid">
          <div className="ps-hero">
            <div className="ps-num mono gold">{D.processScorecard.score}</div>
            <div className="ps-num-lbl">PROCESS SCORE</div>
            <div className="ps-num-sub mono">+4 vs prior 30d</div>
          </div>
          <div className="ps-bars">
            {D.processScorecard.metrics.map(m => (
              <SubScoreBar key={m.label} label={m.label} score={m.value} max={m.of}
                           color={m.value >= 90 ? "green" : m.value >= 75 ? "amber" : "red"} />
            ))}
          </div>
          <div className="ps-aggs">
            <div className="ps-agg">
              <div className="ps-agg-lbl">WIN RATE</div>
              <div className="ps-agg-val mono">{winRate.toFixed(0)}%</div>
              <div className="ps-agg-sub muted">{wins} / {closed.length}</div>
            </div>
            <div className="ps-agg">
              <div className="ps-agg-lbl">AVG P&amp;L / TRADE</div>
              <div className={`ps-agg-val mono ${avgPnl >= 0 ? "pos" : "neg"}`}>{avgPnl >= 0 ? "+" : ""}{avgPnl.toFixed(2)}%</div>
            </div>
            <div className="ps-agg">
              <div className="ps-agg-lbl">PROFIT FACTOR</div>
              <div className="ps-agg-val mono">{profitFactor.toFixed(2)}</div>
            </div>
            <div className="ps-agg">
              <div className="ps-agg-lbl">SCORE↔OUTCOME ρ</div>
              <div className="ps-agg-val mono gold">+0.61</div>
              <div className="ps-agg-sub muted">framework predictive</div>
            </div>
          </div>
        </div>
      </section>

      <section className="two-col-7030">
        {/* Closed trades */}
        <div className="block">
          <header className="block-head sm">
            <div className="block-title">
              <span className="block-num mono">J2</span>
              <span>Closed trades</span>
              <span className="block-sub">last 10 · sorted by date</span>
            </div>
          </header>
          <table className="wl-table journal-table">
            <thead>
              <tr>
                <th>ASSET</th>
                <th>SIDE</th>
                <th className="num">P&amp;L</th>
                <th className="num">HOLD</th>
                <th className="num">SCORE@ENTRY</th>
                <th>REGIME@ENTRY</th>
                <th>THESIS?</th>
                <th>PLAN</th>
                <th>LESSON</th>
              </tr>
            </thead>
            <tbody>
              {closed.map(t => (
                <tr key={t.id}>
                  <td className="mono asset-cell">{t.asset}</td>
                  <td><SideLabel side={t.side} /></td>
                  <td className={`num ${t.pnlPct >= 0 ? "pos" : "neg"}`}>
                    {t.pnlPct >= 0 ? "+" : ""}{t.pnlPct.toFixed(2)}%
                  </td>
                  <td className="num muted">{t.holdDays}d</td>
                  <td className="num">
                    <span className={`wl-score tier-${t.scoreEntry >= 85 ? 1 : t.scoreEntry >= 70 ? 2 : 3}`}>
                      {t.scoreEntry}
                    </span>
                  </td>
                  <td className="muted small">{t.regimeEntry}</td>
                  <td>
                    <span className={`thesis-tag thesis-${t.thesis}`}>
                      {t.thesis === "yes" ? "✓ yes" : t.thesis === "no" ? "✕ no" : "◐ partial"}
                    </span>
                  </td>
                  <td>
                    <span className={`plan-tag ${t.planClean ? "clean" : "dirty"}`}>
                      {t.planClean ? "clean" : "dirty"}
                    </span>
                  </td>
                  <td className="lesson-cell">{t.lesson}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Missed trades */}
        <div className="block">
          <header className="block-head sm">
            <div className="block-title">
              <span className="block-num mono">J3</span>
              <span>Missed</span>
              <span className="block-sub">setups not taken</span>
            </div>
          </header>
          <div className="missed-list">
            {D.missedTrades.map(m => (
              <div key={m.asset} className="missed-row">
                <div className="missed-head">
                  <span className="mono asset-cell">{m.asset}</span>
                  <span className="wl-score tier-2">{m.scoreAtTime}</span>
                </div>
                <div className="missed-meta">
                  <span className={`missed-tag reason-${m.reason}`}>{m.reason.replace(/_/g, " ")}</span>
                  {m.validReal
                    ? <span className="missed-tag valid">valid in real time</span>
                    : <span className="missed-tag invalid muted">hindsight only</span>}
                </div>
                <div className="missed-lesson">{m.lesson}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="two-col-6040">
        {/* Source attribution leaderboard */}
        <div className="block">
          <header className="block-head sm">
            <div className="block-title">
              <span className="block-num mono">J4</span>
              <span>Source attribution · 30d</span>
              <span className="block-sub">which sources are earning their weight</span>
            </div>
          </header>
          <table className="wl-table">
            <thead>
              <tr>
                <th>SOURCE</th>
                <th className="num">WEIGHT</th>
                <th className="num">Δ 30D</th>
                <th className="num">ATTRIB</th>
                <th className="num">TRADES</th>
                <th>TAGS</th>
              </tr>
            </thead>
            <tbody>
              {D.sourceLeaderboard.map(s => (
                <tr key={s.name}>
                  <td className="src-name">{s.name}</td>
                  <td className="num mono"><WeightBar w={s.weight} /></td>
                  <td className={`num mono ${s.dWeight > 0 ? "pos" : s.dWeight < 0 ? "neg" : "muted"}`}>
                    {s.dWeight > 0 ? "+" : ""}{s.dWeight.toFixed(2)}
                  </td>
                  <td className={`num ${s.attribUsd >= 0 ? "pos" : "neg"}`}>
                    {s.attribUsd >= 0 ? "+" : ""}${(s.attribUsd / 1000).toFixed(2)}k
                  </td>
                  <td className="num muted">{s.trades}</td>
                  <td>
                    {s.tags.map(t => <span key={t} className="tag-chip">{t}</span>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Thesis change log */}
        <div className="block">
          <header className="block-head sm">
            <div className="block-title">
              <span className="block-num mono">J5</span>
              <span>Thesis change log</span>
              <span className="block-sub">when the worldview shifted</span>
            </div>
          </header>
          <div className="changelog">
            {D.thesisChangelog.map((c, i) => (
              <div key={c.date} className="cl-row">
                <div className="cl-track">
                  <div className="cl-dot" style={{ background: i === 0 ? "var(--gold)" : "var(--text-mute-2)" }}></div>
                  {i < D.thesisChangelog.length - 1 && <div className="cl-line"></div>}
                </div>
                <div className="cl-body">
                  <div className="cl-head-row">
                    <span className="cl-date mono">{c.date}</span>
                    <span className="cl-vers mono">{c.from} → {c.to}</span>
                  </div>
                  <div className="cl-title">{c.title}</div>
                  <div className="cl-summary">{c.summary}</div>
                  {c.regimes.length > 0 && (
                    <div className="cl-regimes">
                      {c.regimes.map(r => (
                        <span key={r} className={`cl-regime ${r.startsWith("+") ? "added" : "removed"}`}>
                          {r}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <LessonsLibraryPanel lessons={lessons} />
    </div>
  );
}

// ─── J0 strip: pending reviews queue at top of /journal ────────────────
function PendingReviewsStrip({ pending, onPick }) {
  if (!pending || pending.length === 0) return null;
  return (
    <section className="block pending-reviews-strip">
      <header className="block-head sm">
        <div className="block-title">
          <span className="block-num mono amber">J0</span>
          <span>Pending reviews</span>
          <span className="block-sub">
            {pending.length === 1
              ? "1 closed trade waiting — review in under 60s"
              : `${pending.length} closed trades waiting — review in under 60s`}
          </span>
        </div>
        <div className="pending-badge mono">{pending.length}</div>
      </header>
      <div className="pending-chips-row">
        {pending.map(t => (
          <button
            key={t.trade_id}
            className={`pending-chip ${t.pnlPct >= 0 ? "win" : "loss"}`}
            onClick={() => onPick(t)}
          >
            <span className="pc-asset mono">{t.ticker}</span>
            <span className="pc-side"><SideLabel side={t.side} /></span>
            <span className={`pc-pnl mono ${t.pnlPct >= 0 ? "pos" : "neg"}`}>
              {t.pnlPct >= 0 ? "+" : ""}{t.pnlPct.toFixed(2)}%
            </span>
            <span className="pc-cta">review →</span>
          </button>
        ))}
      </div>
    </section>
  );
}

// ─── Review modal (wraps DrillSheet) — the 7-question framework ────────
function ReviewModal({ trade, onClose, onSubmitted }) {
  const open = !!trade;
  const tradeId = trade?.trade_id;
  const draftKey = tradeId ? `review_draft_${tradeId}` : null;

  const candidateSources = trade?.candidateSources || [];

  const initial = React.useMemo(() => ({
    thesis_validity: null,
    sources_credited: [],
    execution_scores: { entry: null, stop: null, sizing: null, exit: null },
    setup_score_hindsight: null,
    surprise_factor: [],
    surprise_note: "",
    lesson: "",
    would_retake: null,
    free_form_notes: "",
  }), []);

  const [form, setForm] = React.useState(initial);
  const [showNotes, setShowNotes] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(null);

  // Load draft / reset on trade change.
  React.useEffect(() => {
    if (!open || !draftKey) return;
    setError(null);
    setSubmitting(false);
    try {
      const raw = localStorage.getItem(draftKey);
      if (raw) {
        setForm({ ...initial, ...JSON.parse(raw) });
        return;
      }
    } catch (e) { /* corrupt draft — fall through */ }
    setForm(initial);
    setShowNotes(false);
  }, [open, draftKey, initial]);

  // Autosave draft on every change.
  React.useEffect(() => {
    if (!open || !draftKey) return;
    try { localStorage.setItem(draftKey, JSON.stringify(form)); }
    catch (e) { /* quota exceeded — silent */ }
  }, [form, open, draftKey]);

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
  const setExec = (k, v) =>
    setForm(prev => ({ ...prev, execution_scores: { ...prev.execution_scores, [k]: v } }));

  const validate = () => {
    if (!form.thesis_validity) return "Pick a thesis-validity option (Q1).";
    const e = form.execution_scores;
    for (const k of ["entry", "stop", "sizing", "exit"]) {
      if (!e[k]) return `Score every execution dimension (Q3 · ${k}).`;
    }
    if (!form.setup_score_hindsight) return "Pick a hindsight call (Q4).";
    if (!form.lesson.trim()) return "Write a one-line lesson (Q6).";
    if (!form.would_retake) return "Pick a retake answer (Q7).";
    return null;
  };

  const onSubmit = async () => {
    const err = validate();
    if (err) { setError(err); return; }
    setError(null);
    setSubmitting(true);
    const payload = {
      thesis_validity: form.thesis_validity,
      sources_credited: form.sources_credited,
      execution_scores: form.execution_scores,
      setup_score_hindsight: form.setup_score_hindsight,
      surprise_factor: form.surprise_factor,
      surprise_note: form.surprise_note.trim() || null,
      lesson: form.lesson.trim(),
      would_retake: form.would_retake,
      free_form_notes: form.free_form_notes.trim() || null,
    };
    try {
      const r = await fetch(`/api/reviews/${tradeId}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      // Dev mode: backend may not know the mock trade. Treat 404 as "ok,
      // demo-only" so dogfooding the SPA still flows. 422 is a real bug.
      if (!r.ok && r.status !== 404) {
        const body = await r.text();
        throw new Error(`HTTP ${r.status} — ${body.slice(0, 200)}`);
      }
    } catch (e) {
      // network down → still proceed for demo, but surface in console
      console.warn("review POST failed; proceeding locally", e);
    }
    try { localStorage.removeItem(draftKey); } catch (e) { /* ignore */ }
    setSubmitting(false);
    onSubmitted(trade, payload);
    onClose();
  };

  return (
    <DrillSheet
      open={open}
      onClose={onClose}
      title={trade ? `Review ${trade.ticker}` : "Review"}
      subtitle={trade
        ? `${trade.side} · ${trade.pnlPct >= 0 ? "+" : ""}${trade.pnlPct?.toFixed(2)}% · ${trade.holdDays}d · score@entry ${trade.scoreEntry}`
        : ""}
    >
      {trade && (
        <div className="review-form">
          <ReviewSection n="Q1" label="Was the thesis correct?">
            <EnumPicker
              value={form.thesis_validity}
              onChange={(v) => set("thesis_validity", v)}
              options={THESIS_VALIDITY_OPTS}
            />
          </ReviewSection>

          <ReviewSection
            n="Q2"
            label="Which sources actually drove this trade?"
            hint={candidateSources.length
              ? "Selected at entry — uncheck what didn't deliver"
              : "Multi-select all that mattered"}
          >
            {candidateSources.length > 0 ? (
              <MultiPicker
                values={form.sources_credited}
                onChange={(v) => set("sources_credited", v)}
                options={candidateSources.map(s => ({ value: s, label: s }))}
              />
            ) : (
              <input
                className="rv-text"
                placeholder="comma-separated source ids"
                value={(form.sources_credited || []).join(", ")}
                onChange={(e) => set(
                  "sources_credited",
                  e.target.value.split(",").map(s => s.trim()).filter(Boolean),
                )}
              />
            )}
          </ReviewSection>

          <ReviewSection n="Q3" label="Execution quality">
            <div className="exec-grid">
              {["entry", "stop", "sizing", "exit"].map(k => (
                <div key={k} className="exec-row">
                  <div className="exec-lbl">{k.toUpperCase()}</div>
                  <Likert
                    value={form.execution_scores[k]}
                    onChange={(v) => setExec(k, v)}
                    min={1}
                    max={5}
                    labels={EXEC_LIKERT_LABELS}
                  />
                </div>
              ))}
            </div>
          </ReviewSection>

          <ReviewSection n="Q4" label="Setup score in hindsight">
            <EnumPicker
              value={form.setup_score_hindsight}
              onChange={(v) => set("setup_score_hindsight", v)}
              options={HINDSIGHT_OPTS}
            />
          </ReviewSection>

          <ReviewSection n="Q5" label="Surprise factor">
            <MultiPicker
              values={form.surprise_factor}
              onChange={(v) => set("surprise_factor", v)}
              options={SURPRISE_OPTS}
            />
            <input
              className="rv-text mt8"
              placeholder="One-line note (optional)"
              value={form.surprise_note}
              onChange={(e) => set("surprise_note", e.target.value)}
              maxLength={200}
            />
          </ReviewSection>

          <ReviewSection
            n="Q6"
            label="One-line lesson"
            hint={`${form.lesson.length}/200`}
          >
            <input
              className="rv-text"
              placeholder="What's the take-away?"
              value={form.lesson}
              onChange={(e) => set("lesson", e.target.value.slice(0, 200))}
              maxLength={200}
            />
          </ReviewSection>

          <ReviewSection n="Q7" label="Would you take this trade again?">
            <EnumPicker
              value={form.would_retake}
              onChange={(v) => set("would_retake", v)}
              options={RETAKE_OPTS}
            />
          </ReviewSection>

          <div className="rv-notes-toggle">
            <button
              type="button"
              className="btn-mini"
              onClick={() => setShowNotes(v => !v)}
            >
              {showNotes ? "− Hide notes" : "+ Add notes"}
            </button>
          </div>
          {showNotes && (
            <textarea
              className="rv-textarea"
              placeholder="Free-form notes (optional)"
              value={form.free_form_notes}
              onChange={(e) => set("free_form_notes", e.target.value)}
              rows={4}
            />
          )}

          {error && <div className="rv-error">{error}</div>}

          <div className="rv-submit-row">
            <button className="btn-secondary" onClick={onClose} disabled={submitting}>Cancel</button>
            <button className="btn-primary" onClick={onSubmit} disabled={submitting}>
              {submitting ? "Submitting…" : "Submit review"}
            </button>
          </div>
        </div>
      )}
    </DrillSheet>
  );
}

function ReviewSection({ n, label, hint, children }) {
  return (
    <div className="rv-section">
      <div className="rv-head">
        <span className="rv-num mono">{n}</span>
        <span className="rv-label">{label}</span>
        {hint && <span className="rv-hint mono">{hint}</span>}
      </div>
      <div className="rv-body">{children}</div>
    </div>
  );
}

// ─── J6: lessons library ───────────────────────────────────────────────
function LessonsLibraryPanel({ lessons }) {
  const [tickerQ, setTickerQ] = React.useState("");
  const [thesisFilter, setThesisFilter] = React.useState("all");
  const [expanded, setExpanded] = React.useState(null);

  const filtered = (lessons || []).filter(l => {
    if (thesisFilter !== "all" && l.thesisValidity !== thesisFilter) return false;
    if (tickerQ && !l.ticker.toUpperCase().includes(tickerQ.toUpperCase())) return false;
    return true;
  });

  const filterPills = [
    { value: "all", label: "all" },
    ...THESIS_VALIDITY_OPTS.map(o => ({ value: o.value, label: o.label.split("·")[0].trim().toLowerCase() })),
  ];

  return (
    <section className="block">
      <header className="block-head sm">
        <div className="block-title">
          <span className="block-num mono">J6</span>
          <span>Lessons library</span>
          <span className="block-sub">searchable across reviewed trades · {filtered.length}/{(lessons || []).length}</span>
        </div>
      </header>
      <div className="lessons-controls">
        <input
          className="rv-text lessons-search"
          placeholder="filter by ticker…"
          value={tickerQ}
          onChange={(e) => setTickerQ(e.target.value)}
        />
        <div className="enum-picker">
          {filterPills.map(p => (
            <button
              key={p.value}
              type="button"
              className={`enum-chip ${thesisFilter === p.value ? "on" : ""}`}
              onClick={() => setThesisFilter(p.value)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="lessons-list">
        {filtered.length === 0 && (
          <div className="lessons-empty muted">No lessons match.</div>
        )}
        {filtered.map(l => {
          const isOpen = expanded === l.trade_id;
          return (
            <div key={l.trade_id} className="lesson-row">
              <div
                className="lesson-head"
                onClick={() => setExpanded(isOpen ? null : l.trade_id)}
              >
                <span className="mono asset-cell">{l.ticker}</span>
                <span className={`num mono ${l.pnlPct >= 0 ? "pos" : "neg"}`}>
                  {l.pnlPct >= 0 ? "+" : ""}{l.pnlPct.toFixed(2)}%
                </span>
                <span className={`thesis-pill thesis-${l.thesisValidity}`}>
                  {(THESIS_VALIDITY_OPTS.find(o => o.value === l.thesisValidity) || {}).label || l.thesisValidity}
                </span>
                <span className="lesson-text">{l.lesson}</span>
                <span className="lesson-toggle mono">{isOpen ? "−" : "+"}</span>
              </div>
              {isOpen && (
                <div className="lesson-detail">
                  <div className="ld-row">
                    <span className="ld-lbl">EXECUTION</span>
                    <span className="mono">
                      entry {l.executionScores.entry} · stop {l.executionScores.stop} ·
                      sizing {l.executionScores.sizing} · exit {l.executionScores.exit}
                    </span>
                  </div>
                  <div className="ld-row">
                    <span className="ld-lbl">SURPRISE</span>
                    <span>
                      {l.surpriseFactor && l.surpriseFactor.length
                        ? l.surpriseFactor.join(", ")
                        : <span className="muted">none</span>}
                    </span>
                  </div>
                  <div className="ld-row">
                    <span className="ld-lbl">RETAKE</span>
                    <span>{l.wouldRetake}</span>
                  </div>
                  <div className="ld-row">
                    <span className="ld-lbl">SOURCES</span>
                    <span>
                      {(l.sourcesCredited || []).map(s =>
                        <span key={s} className="tag-chip">{s}</span>
                      )}
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function WeightBar({ w }) {
  return (
    <div className="weight-bar-cell">
      <div className="wb-track">
        <div className="wb-fill" style={{ width: `${w * 100}%` }}></div>
      </div>
      <span className="wb-num mono">{w.toFixed(2)}</span>
    </div>
  );
}

Object.assign(window, { Journal, PendingReviewsStrip, ReviewModal, LessonsLibraryPanel });
