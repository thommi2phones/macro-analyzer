// Reasoning trail content for the drill-down sheet.

function ReasoningTrail({ signal }) {
  if (!signal) return null;
  const D = window.MA_DATA;
  const r = D.reasoning[signal.id] || D.reasoning["sig-ura-2605"]; // fallback to URA detail
  return (
    <div className="rt-content">
      {/* Header */}
      <div className="rt-card-head">
        <div className="rt-asset-block">
          <div className="rt-asset mono">{signal.asset}</div>
          <div className="rt-name">{signal.name}</div>
          <div className="rt-meta-row">
            <SideLabel side={signal.side} />
            <span className="rt-setup">{signal.setup}</span>
          </div>
        </div>
        <ScoreChip score={r.total} prev={signal.scorePrev} size="lg" />
      </div>
      <TierIndicator tier={r.tier} />

      {/* Levels recap */}
      <div className="rt-levels-grid">
        <div className="rt-l">
          <div className="rt-l-lbl">ENTRY</div>
          <div className="rt-l-val mono">{signal.entry < 1000 ? signal.entry.toFixed(2) : signal.entry.toLocaleString()}</div>
        </div>
        <div className="rt-l">
          <div className="rt-l-lbl">STOP</div>
          <div className="rt-l-val mono red">{signal.stop < 1000 ? signal.stop.toFixed(2) : signal.stop.toLocaleString()}</div>
        </div>
        <div className="rt-l">
          <div className="rt-l-lbl">TARGET</div>
          <div className="rt-l-val mono green">{signal.target < 1000 ? signal.target.toFixed(2) : signal.target.toLocaleString()}</div>
        </div>
        <div className="rt-l">
          <div className="rt-l-lbl">R/R</div>
          <div className="rt-l-val mono">{signal.rr.toFixed(2)}</div>
        </div>
      </div>

      {/* Section: composite breakdown */}
      <div className="rt-section">
        <div className="rt-section-head">
          <span className="rt-section-num mono">A</span>
          <span>Composite breakdown</span>
          <span className="rt-section-sub">total {r.total} / 100</span>
        </div>
        <div className="rt-bars">
          {r.components.map(c => (
            <SubScoreBar key={c.label} label={c.label} score={c.score} max={c.max} color={c.color} />
          ))}
        </div>
        <div className="rt-modifiers">
          {r.modifiers.map(m => (
            <div key={m.label} className="rt-mod-row">
              <span className="rt-mod-lbl">{m.label}</span>
              <span className={`rt-mod-val mono ${m.value.startsWith("+") ? "pos" : m.value === "0" ? "muted" : "neg"}`}>
                {m.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Section: why now */}
      <div className="rt-section">
        <div className="rt-section-head">
          <span className="rt-section-num mono">B</span>
          <span>Why this · why now</span>
        </div>
        <ul className="rt-why">
          {signal.whyNow.map((b, i) => <li key={i}>{b}</li>)}
        </ul>
      </div>

      {/* Section: contributing sources */}
      <div className="rt-section">
        <div className="rt-section-head">
          <span className="rt-section-num mono">C</span>
          <span>Contributing sources</span>
          <span className="rt-section-sub">{r.sources.length} · weighted</span>
        </div>
        <div className="rt-sources">
          {r.sources.map(s => (
            <SourcePill key={s.name} name={s.name} weight={s.weight} freshness={s.freshness} contrib={s.contrib} />
          ))}
        </div>
      </div>

      {/* Section: contributing theses */}
      <div className="rt-section">
        <div className="rt-section-head">
          <span className="rt-section-num mono">D</span>
          <span>Contributing theses</span>
        </div>
        <div className="rt-theses">
          {r.theses.map(t => (
            <div key={t.theme} className={`rt-thesis-row dir-${t.direction}`}>
              <span className={`rt-thesis-dot dir-${t.direction}`}></span>
              <span className="rt-thesis-theme mono">{t.theme}</span>
              <span className="rt-thesis-dir">{t.direction}</span>
              <span className="rt-thesis-conf mono">{Math.round(t.confidence * 100)}%</span>
            </div>
          ))}
        </div>
      </div>

      {/* Section: agent breakdown */}
      <div className="rt-section">
        <div className="rt-section-head">
          <span className="rt-section-num mono">E</span>
          <span>Agent-by-agent</span>
          <span className="rt-section-sub">brain calls behind this score</span>
        </div>
        <table className="wl-table dev-table">
          <thead>
            <tr>
              <th>AGENT</th>
              <th>MODEL</th>
              <th className="num">LATENCY</th>
              <th className="num">USD</th>
              <th>OK</th>
            </tr>
          </thead>
          <tbody>
            {r.agentBreakdown.map(a => (
              <tr key={a.agent}>
                <td className="mono">{a.agent}</td>
                <td className="mono muted">{a.model}</td>
                <td className="num mono">{a.latencyMs}<span className="muted">ms</span></td>
                <td className="num mono">${a.costUsd.toFixed(3)}</td>
                <td>{a.ok ? <span className="ok-dot ok"></span> : <span className="ok-dot fail"></span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rt-footer">
        <button className="btn-primary">Log this trade ↵</button>
        <button className="btn-secondary">Open chart_vision ⤴</button>
        <button className="btn-secondary">Raw feature vector</button>
      </div>
    </div>
  );
}

Object.assign(window, { ReasoningTrail });
