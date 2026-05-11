// /live — step ④ of the funnel.
//
// Open positions with plan lineage. The list reuses the
// ActiveTradesPanel rendering from positioning.jsx but is hosted on
// its own page; selecting a trade reveals its plan + concept lineage
// chain and a placeholder exit-management panel.

function Live({ focusTradeId }) {
  const D = window.MA_DATA;
  const trades = D.activeTrades || [];
  const plans = D.plans || [];
  const concepts = D.concepts || [];

  const [selectedId, setSelectedId] = React.useState(
    focusTradeId || (trades[0] && trades[0].id)
  );
  React.useEffect(() => {
    if (focusTradeId) setSelectedId(focusTradeId);
  }, [focusTradeId]);
  const selected = trades.find(t => t.id === selectedId);
  const plan = selected && (selected.planId
    ? plans.find(p => p.id === selected.planId)
    : plans.find(p => p.tradeId === selected.id));
  const concept = plan && plan.conceptId
    ? concepts.find(c => c.id === plan.conceptId)
    : null;

  return (
    <div className="live-view two-col-6040">
      <div className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">L1</span>
            <span>Live trades</span>
            <span className="block-sub">
              {trades.length} open · click a row for plan lineage
            </span>
          </div>
        </header>
        {trades.length === 0 ? (
          <div className="empty-state muted">
            No open positions. Activate a plan on /identify to put one here.
          </div>
        ) : (
          <div className="trades-list">
            {trades.map(t => {
              const scoreD = (t.scoreNow || 0) - (t.scoreAtOpen || 0);
              const isSel = t.id === selectedId;
              return (
                <button
                  key={t.id}
                  className={`trade-row status-${t.status} ${isSel ? "on" : ""}`}
                  onClick={() => setSelectedId(t.id)}
                >
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
                      <span className="mono">{t.target && t.target < 1000 ? t.target.toFixed(2) : (t.target || 0).toLocaleString()}</span>
                    </div>
                  </div>
                  <div className="tr-score">
                    <span className="tr-l-lbl">score</span>
                    <div>
                      <span className="mono muted">{t.scoreAtOpen || 0}→</span>
                      <span className="mono">{t.scoreNow || 0}</span>
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
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="block">
        <header className="block-head sm">
          <div className="block-title">
            <span className="block-num mono">L2</span>
            <span>Lineage · {selected ? selected.asset : "—"}</span>
            <span className="block-sub">concept → plan → trade</span>
          </div>
        </header>
        {selected ? (
          <div className="lineage-panel">
            <LineageStep
              label="Concept"
              body={concept
                ? `${concept.id} · marked ${concept.markedAt} · ${concept.source}`
                : "no concept linked"}
              note={concept && concept.thesis}
              muted={!concept}
            />
            <LineageStep
              label="Plan"
              body={plan
                ? `${plan.id} · ${plan.status} · gate ${plan.gateStatus || "—"}`
                : "no plan linked"}
              note={plan && plan.thesis}
              muted={!plan}
            />
            <LineageStep
              label="Trade"
              body={`${selected.id} · entry ${selected.entry} · stop ${selected.stop}`}
              note={`opened ${selected.ageDays}d ago · P&L ${selected.pnlPct >= 0 ? "+" : ""}${(selected.pnlPct || 0).toFixed(2)}%`}
            />
            <div className="form-actions">
              <button className="btn-ghost" disabled>scale out (todo)</button>
              <button className="btn-ghost" disabled>move stop (todo)</button>
              <button className="btn-primary" disabled>close trade (todo)</button>
            </div>
          </div>
        ) : (
          <div className="empty-state muted">Select a trade to see its lineage.</div>
        )}
      </div>
    </div>
  );
}

function LineageStep({ label, body, note, muted }) {
  return (
    <div className={`lineage-step ${muted ? "muted" : ""}`}>
      <div className="ls-label mono small">{label.toUpperCase()}</div>
      <div className="ls-body mono">{body}</div>
      {note && <div className="ls-note small muted">{note}</div>}
    </div>
  );
}

Object.assign(window, { Live });
