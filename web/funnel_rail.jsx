// Shared funnel rail — the spine of the platform IA.
//
// Five numbered chips rendered in the topbar showing where you are in
// the watchlist → concept → plan → live → review funnel and how many
// items are pending at each stage. It is navigation, not a wizard:
// chips are clickable, no forced "next" arrows.

function FunnelRail({ view, onNav }) {
  const D = window.MA_DATA;

  // Live counts derived from MA_DATA. These match the funnel as data
  // moves through it — every shape change downstream updates here.
  const watchlistN = (D.watchlist || []).filter(r => r.score >= 70).length;
  const concepts = D.concepts || [];
  const activeConcepts = concepts.filter(c => c.status === "active").length;
  const suggestedN = (D.conceptSuggestions || []).length;
  const plans = D.plans || [];
  const draftPlans = plans.filter(p => p.status === "draft").length;
  const liveTrades = (D.activeTrades || []).length;
  const closedN = (D.closedTrades || []).length;

  const steps = [
    { key: "positioning", num: 1, label: "Positioning", sub: `${watchlistN} actionable` },
    { key: "concepts",    num: 2, label: "Concepts",    sub: `${activeConcepts} active · ${suggestedN} suggested` },
    { key: "identify",    num: 3, label: "Identify",    sub: `${draftPlans} draft plan${draftPlans === 1 ? "" : "s"}` },
    { key: "live",        num: 4, label: "Live",        sub: `${liveTrades} open` },
    { key: "journal",     num: 5, label: "Journal",     sub: `${closedN} reviewed` },
  ];

  return (
    <div className="funnel-rail" role="navigation" aria-label="Funnel">
      {steps.map((s, i) => (
        <React.Fragment key={s.key}>
          <button
            className={`fr-chip ${view === s.key ? "on" : ""}`}
            onClick={() => onNav(s.key)}
          >
            <span className="fr-num mono">/0{s.num}</span>
            <span className="fr-body">
              <span className="fr-label">{s.label}</span>
              <span className="fr-sub mono">{s.sub}</span>
            </span>
          </button>
          {i < steps.length - 1 && <span className="fr-sep" aria-hidden>→</span>}
        </React.Fragment>
      ))}
    </div>
  );
}

Object.assign(window, { FunnelRail });
