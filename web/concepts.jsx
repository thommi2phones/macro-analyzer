// /concepts — step ② of the funnel.
//
// Three stacked sections: suggested (system-proposed promotions from
// the watchlist), active (marked concepts awaiting decision), history
// (promoted + retired). Marking from a suggestion or from the
// watchlist on /positioning creates an active concept row; promoting
// jumps to /identify with a draft plan seeded from the concept.

function Concepts({ onPromote }) {
  const D = window.MA_DATA;
  const [, force] = React.useState(0);
  const rerender = () => force(n => n + 1);
  const [showHistory, setShowHistory] = React.useState(false);
  const [openSug, setOpenSug] = React.useState(null);

  const concepts = D.concepts || [];
  const suggestions = D.conceptSuggestions || [];
  const active = concepts.filter(c => c.status === "active");
  const history = concepts.filter(c => c.status !== "active");

  // Optimistic local mutations of MA_DATA. The mock-first SPA keeps
  // the snapshot in memory; a real API call to /api/funnel/concepts
  // can be added in parallel without changing the shape rendered here.
  const markConcept = (sug) => {
    const id = `concept-${Date.now().toString(36)}`;
    D.concepts = (D.concepts || []).concat([{
      id,
      asset: sug.asset,
      source: "watchlist_auto",
      status: "active",
      suggestedBySystem: true,
      suggestionReason: sug.reason,
      scoreAtMark: sug.score,
      tierAtMark: sug.tier,
      sideAtMark: sug.side,
      thesis: "",
      markedAt: new Date().toISOString().slice(0, 16).replace("T", " "),
      tradePlanId: null,
    }]);
    D.conceptSuggestions = suggestions.filter(s => s.asset !== sug.asset);
    rerender();
  };

  const updateThesis = (id, text) => {
    const c = D.concepts.find(x => x.id === id);
    if (c) { c.thesis = text; rerender(); }
  };

  const retireConcept = (id) => {
    const c = D.concepts.find(x => x.id === id);
    if (c) {
      c.status = "retired";
      c.retiredAt = new Date().toISOString().slice(0, 16).replace("T", " ");
      rerender();
    }
  };

  const promoteConcept = (c) => {
    const planId = `plan-${Date.now().toString(36)}`;
    D.plans = (D.plans || []).concat([{
      id: planId,
      conceptId: c.id,
      asset: c.asset,
      side: c.sideAtMark || "LONG",
      entry: null, stop: null,
      targets: [],
      sizeUsd: null, sizeR: 1.0,
      timeHorizon: "swing",
      thesis: c.thesis || "",
      invalidation: "",
      gateStatus: "unchecked",
      status: "draft",
      tradeId: null,
      createdAt: new Date().toISOString().slice(0, 16).replace("T", " "),
      activatedAt: null,
    }]);
    c.status = "promoted";
    c.promotedAt = new Date().toISOString().slice(0, 16).replace("T", " ");
    c.tradePlanId = planId;
    if (onPromote) onPromote(planId);
  };

  return (
    <div className="concepts-view">
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">C1</span>
            <span>Suggested by system</span>
            <span className="block-sub">
              {suggestions.length} candidate{suggestions.length === 1 ? "" : "s"} ·
              high-score watchlist rows not yet marked
            </span>
          </div>
        </header>
        {suggestions.length === 0 ? (
          <div className="empty-state muted small">
            No system suggestions right now — mark anything on the watchlist manually.
          </div>
        ) : (
          <div className="concepts-list">
            {suggestions.map(s => (
              <div key={s.asset} className="concept-row suggested concept-row-clickable"
                   onClick={() => setOpenSug(s)}
                   title="Click to see what sources are saying">
                <div className="concept-asset">
                  <div className="mono asset-cell">{s.asset}</div>
                  <SideLabel side={s.side} />
                </div>
                <div className="concept-score">
                  <span className={`wl-score tier-${s.tier}`}>{s.score}</span>
                  <span className={`mono small ${s.dScore > 0 ? "pos" : s.dScore < 0 ? "neg" : "muted"}`}>
                    {s.dScore > 0 ? "+" : ""}{s.dScore} Δ
                  </span>
                </div>
                <div className="concept-reason muted small">{s.reason}</div>
                <div className="concept-actions">
                  <button className="btn-primary sm"
                    onClick={(e) => { e.stopPropagation(); markConcept(s); }}>
                    mark as concept ↵
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">C2</span>
            <span>Active concepts</span>
            <span className="block-sub">
              {active.length} marked · awaiting promotion to plan
            </span>
          </div>
        </header>
        {active.length === 0 ? (
          <div className="empty-state muted small">
            No active concepts. Mark something from the watchlist or the suggestion list above.
          </div>
        ) : (
          <div className="concepts-list">
            {active.map(c => (
              <div key={c.id} className="concept-row active">
                <div className="concept-asset">
                  <div className="mono asset-cell">{c.asset}</div>
                  <SideLabel side={c.sideAtMark || "LONG"} />
                  <span className="concept-source-chip mono small muted">{c.source}</span>
                </div>
                <div className="concept-score">
                  <span className={`wl-score tier-${c.tierAtMark || 3}`}>{c.scoreAtMark}</span>
                  <span className="mono small muted">@ mark</span>
                </div>
                <textarea
                  className="concept-thesis form-input"
                  placeholder="Thesis · why this, why now, what invalidates"
                  value={c.thesis || ""}
                  onChange={(e) => updateThesis(c.id, e.target.value)}
                />
                <div className="concept-meta mono small muted">marked {c.markedAt}</div>
                <div className="concept-actions">
                  <button className="btn-primary sm" onClick={() => promoteConcept(c)}>
                    promote to plan →
                  </button>
                  <button className="btn-ghost sm" onClick={() => retireConcept(c.id)}>
                    retire
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="block">
        <header className="block-head sm">
          <div className="block-title">
            <span className="block-num mono">C3</span>
            <span>History</span>
            <span className="block-sub">
              {history.length} promoted / retired · lineage record
            </span>
          </div>
          <div className="block-actions">
            <button className="filter-pill" onClick={() => setShowHistory(v => !v)}>
              {showHistory ? "hide" : "show"}
            </button>
          </div>
        </header>
        {showHistory && (
          history.length === 0 ? (
            <div className="empty-state muted small">No promoted or retired concepts yet.</div>
          ) : (
            <table className="wl-table">
              <thead>
                <tr>
                  <th>ASSET</th>
                  <th>STATUS</th>
                  <th className="num">SCORE@MARK</th>
                  <th>SOURCE</th>
                  <th>MARKED</th>
                  <th>RESOLVED</th>
                  <th>LINK</th>
                </tr>
              </thead>
              <tbody>
                {history.map(c => (
                  <tr key={c.id}>
                    <td className="mono asset-cell">{c.asset}</td>
                    <td>
                      <span className={`status-chip status-${c.status}`}>{c.status}</span>
                    </td>
                    <td className="num">{c.scoreAtMark}</td>
                    <td className="mono small muted">{c.source}</td>
                    <td className="mono small muted">{c.markedAt}</td>
                    <td className="mono small muted">{c.promotedAt || c.retiredAt || "—"}</td>
                    <td className="mono small">
                      {c.tradePlanId
                        ? <span className="plan-link">→ {c.tradePlanId}</span>
                        : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </section>
      <DrillSheet open={!!openSug} onClose={() => setOpenSug(null)}
        title={openSug ? openSug.asset : ""}
        subtitle={openSug ? `${openSug.side} · score ${openSug.score} · T${openSug.tier}` : ""}>
        {openSug && <SuggestionDetailPanel s={openSug} />}
      </DrillSheet>
    </div>
  );
}

function SuggestionDetailPanel({ s }) {
  const D = window.MA_DATA;
  const wlRow = (D.watchlist || []).find(w => w.asset === s.asset);
  const heroRow = (D.heroSignals || []).find(h => h.asset === s.asset);
  const themeMentions = ((D.streams && D.streams.themeMap) || [])
    .filter(t => (t.assets || t.tickers || []).map(x => (x || "").toUpperCase()).includes(s.asset.toUpperCase()))
    .slice(0, 6);
  const assetMentions = ((D.streams && D.streams.assetMap) || [])
    .filter(t => (t.label || "").toUpperCase() === s.asset.toUpperCase())
    .slice(0, 4);
  const sources = wlRow?.origins || heroRow?.sources || [];

  return (
    <div className="rt-content">
      <div className="rt-card-head">
        <div className="rt-asset-block">
          <div className="rt-asset mono">{s.asset}</div>
          <div className="rt-name">{wlRow?.name || s.asset}</div>
          <div className="rt-meta-row">
            <SideLabel side={s.side} />
            <span className="rt-setup">regime {s.regime}</span>
          </div>
        </div>
        <div className={`wl-score tier-${s.tier}`} style={{ fontSize: 24, padding: "6px 12px" }}>
          {s.score}
        </div>
      </div>

      <div className="rt-section">
        <div className="rt-section-head">
          <span className="rt-section-num mono">A</span>
          <span>Why suggested</span>
        </div>
        <p style={{ margin: "6px 0 0 0", lineHeight: 1.5 }}>{s.reason}</p>
        <div className="mono small muted" style={{ marginTop: 6 }}>
          score {s.score} · Δ {s.dScore >= 0 ? "+" : ""}{s.dScore} · tier T{s.tier} · regime {s.regime}
        </div>
      </div>

      {sources.length > 0 && (
        <div className="rt-section">
          <div className="rt-section-head">
            <span className="rt-section-num mono">B</span>
            <span>Watchlist origins · sources talking about this</span>
          </div>
          <div className="tag-row" style={{ marginTop: 8 }}>
            {sources.map((src, i) => <span key={i} className="tag-chip">{src}</span>)}
          </div>
        </div>
      )}

      {(themeMentions.length > 0 || assetMentions.length > 0) && (
        <div className="rt-section">
          <div className="rt-section-head">
            <span className="rt-section-num mono">C</span>
            <span>Live narrative context</span>
          </div>
          {assetMentions.map(t => (
            <div key={"a-" + t.label} className="mono small" style={{ padding: "4px 0" }}>
              · asset chatter <b>{t.label}</b> · {t.direction} · {t.age_days}d old · {(t.items || []).length || 0} items
            </div>
          ))}
          {themeMentions.map(t => (
            <div key={"t-" + t.label} className="mono small" style={{ padding: "4px 0" }}>
              · theme <b>{t.label}</b> · {t.direction} · {t.age_days}d old
            </div>
          ))}
        </div>
      )}

      {wlRow && (
        <div className="rt-section">
          <div className="rt-section-head">
            <span className="rt-section-num mono">D</span>
            <span>Watchlist breakdown</span>
          </div>
          <div className="rt-modifiers">
            <div className="rt-mod-row"><span className="rt-mod-lbl">tech</span><span className="rt-mod-val mono">{wlRow.tech}</span></div>
            <div className="rt-mod-row"><span className="rt-mod-lbl">vol</span><span className="rt-mod-val mono">{wlRow.vol}</span></div>
            <div className="rt-mod-row"><span className="rt-mod-lbl">R/R</span><span className="rt-mod-val mono">{(wlRow.rr || 0).toFixed(2)}</span></div>
            <div className="rt-mod-row"><span className="rt-mod-lbl">regime</span><span className="rt-mod-val mono">{wlRow.regime}</span></div>
            <div className="rt-mod-row"><span className="rt-mod-lbl">last scored</span><span className="rt-mod-val mono">{wlRow.last}</span></div>
          </div>
        </div>
      )}

      {sources.length === 0 && themeMentions.length === 0 && assetMentions.length === 0 && !wlRow && (
        <div className="empty-state muted small" style={{ padding: "1rem" }}>
          No additional context available yet — score-only suggestion. Once the ticker shows up in a live theme or has a watchlist origin, more detail will appear here.
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Concepts });
