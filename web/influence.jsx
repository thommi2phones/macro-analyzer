// influence.jsx — /05 influence tab. Visualizes the lobbying graph from
// `/api/insiders/lobbying-graph`. Renders a simple SVG force-directed
// layout in-browser (no external graph lib — keeps the SPA's all-CDN
// dependency story intact). Click any node to ego-net + side-panel.
//
// The force layout is a small Verlet-style relaxation: O(N^2) repulsion,
// linear spring attraction for links, run a few hundred ticks at mount.
// At ~200 nodes this stays under 100ms, well inside an interaction budget.

const COLORS = {
  client: "#e3b04b",
  registrant: "#5fb3ff",
  lobbyist: "#9b6ee8",
  agency: "#48c984",
  issue: "#e98073",
  prev_role: "#cccccc",
  other: "#777777",
};


function useGraphData(period, minAmount, focus) {
  const [data, setData] = React.useState({ nodes: [], links: [] });
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const qp = new URLSearchParams();
    if (period) qp.set("period", period);
    if (minAmount > 0) qp.set("min_amount", String(minAmount));
    if (focus) qp.set("focus", focus);
    qp.set("limit", "250");
    fetch(`/api/insiders/lobbying-graph?${qp}`)
      .then((r) => r.json())
      .then((j) => { if (!cancelled) setData(j); })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [period, minAmount, focus]);

  return { data, loading, err };
}


function useSidePanel(focus, period) {
  const [panel, setPanel] = React.useState(null);
  React.useEffect(() => {
    if (!focus) { setPanel(null); return; }
    const qp = new URLSearchParams({ focus });
    if (period) qp.set("period", period);
    fetch(`/api/insiders/lobbying-graph/side-panel?${qp}`)
      .then((r) => r.json())
      .then(setPanel)
      .catch(() => setPanel(null));
  }, [focus, period]);
  return panel;
}


// Cheap force layout — runs a fixed number of ticks at mount and on
// data change. We don't animate; the SVG re-renders once positions
// settle. Keeps the math simple and predictable.
function runForceLayout(nodes, links, width, height, iters = 250) {
  if (!nodes.length) return [];
  const pos = nodes.map((n, i) => ({
    ...n,
    x: width / 2 + Math.cos((i / nodes.length) * 2 * Math.PI) * 220,
    y: height / 2 + Math.sin((i / nodes.length) * 2 * Math.PI) * 220,
    vx: 0, vy: 0,
  }));
  const idx = new Map(pos.map((p, i) => [p.id, i]));

  const linkPairs = links
    .map((l) => ({ a: idx.get(typeof l.source === "string" ? l.source : l.source.id),
                   b: idx.get(typeof l.target === "string" ? l.target : l.target.id),
                   w: Math.max(0.1, Math.log10((l.amount_usd || 1) + 1) / 6) }))
    .filter((l) => l.a !== undefined && l.b !== undefined);

  const REPEL = 4500;
  const SPRING = 0.025;
  const DAMPING = 0.85;
  const CENTER_PULL = 0.005;

  for (let t = 0; t < iters; t++) {
    // Repulsion (O(N^2))
    for (let i = 0; i < pos.length; i++) {
      for (let j = i + 1; j < pos.length; j++) {
        const dx = pos[j].x - pos[i].x;
        const dy = pos[j].y - pos[i].y;
        const dist2 = dx * dx + dy * dy + 0.01;
        const f = REPEL / dist2;
        const dist = Math.sqrt(dist2);
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        pos[i].vx -= fx; pos[i].vy -= fy;
        pos[j].vx += fx; pos[j].vy += fy;
      }
    }
    // Springs
    for (const { a, b, w } of linkPairs) {
      const dx = pos[b].x - pos[a].x;
      const dy = pos[b].y - pos[a].y;
      const f = SPRING * (1 + w);
      pos[a].vx += dx * f; pos[a].vy += dy * f;
      pos[b].vx -= dx * f; pos[b].vy -= dy * f;
    }
    // Center pull + integrate
    for (const p of pos) {
      p.vx += (width / 2 - p.x) * CENTER_PULL;
      p.vy += (height / 2 - p.y) * CENTER_PULL;
      p.vx *= DAMPING; p.vy *= DAMPING;
      p.x += p.vx; p.y += p.vy;
    }
  }
  return pos;
}


// ── Top-level shell ────────────────────────────────────────────────────────

function Influence() {
  const [tab, setTab] = React.useState("themes");
  const TABS = [
    ["themes",    "Themes",         "I2", "per-theme drivers · ticker mentions × lobbying"],
    ["lobbying",  "Lobbying graph", "I3", "force-directed registrant / lobbyist / issue network"],
    ["trades",    "Trades",         "I4", "insider + congressional + large-holder filings"],
    ["contracts", "Contracts",      "I5", "federal contract awards · timeline"],
    ["authors",   "Authors",        "I6", "per-author trust + bias leaderboard"],
  ];
  const active = TABS.find(t => t[0] === tab);

  return (
    <div className="view view-influence influence-view">
      {/* ── I1 Theme overview ────────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">I1</span>
            <span>Theme overview</span>
            <span className="block-sub">where capital + influence are flowing · last 60d</span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 14 }}>
          <ThemeOverviewStrip />
        </div>
      </section>

      {/* ── Tab nav (filter-pill row, no block frame) ────────────────── */}
      <div className="influence-tab-row">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`filter-pill ${tab === key ? "on" : ""}`}
          >{label}</button>
        ))}
      </div>

      {/* ── Active tab content ───────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">{active[2]}</span>
            <span>{active[1]}</span>
            <span className="block-sub">{active[3]}</span>
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 14 }}>
          {tab === "themes" && <ThemesPanel />}
          {tab === "lobbying" && <LobbyingGraph />}
          {tab === "trades" && <Timeline channels={["gov_insider", "corp_insider", "large_holder", "social"]} kind="Trades" />}
          {tab === "contracts" && <Timeline channels={["fed_spend"]} kind="Contracts" />}
          {tab === "authors" && <AuthorThemesPanel />}
        </div>
      </section>
    </div>
  );
}


// ── Overview strip — a 1-liner per top theme above the tabs ────────────────

function ThemeOverviewStrip() {
  const [data, setData] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/insiders/theme-breakdown?window_days=60")
      .then((r) => r.json()).then(setData).catch(() => setData(null));
  }, []);
  if (!data || !data.themes || !data.themes.length) {
    return <div className="empty-state mono muted" style={{ padding: "1rem" }}>theme breakdown loading…</div>;
  }
  const max = Math.max(...data.themes.map((t) => t.total)) || 1;
  return (
    <div className="influence-tile-grid">
      {data.themes.slice(0, 8).map((t) => (
        <article key={t.theme} className="influence-tile">
          <div className="it-label mono">{t.theme.replace(/_/g, " ")}</div>
          <div className="it-value mono">{t.total.toFixed(1)}</div>
          <div className="it-meta mono small muted">
            ticker {t.insider_score.toFixed(0)} · LDA {t.lda_score.toFixed(0)}
          </div>
          <div className="it-bar">
            <div className="it-bar-fill" style={{ width: `${Math.min(100, 100 * t.total / max)}%` }} />
          </div>
        </article>
      ))}
    </div>
  );
}


// ── Themes panel — per-theme drivers ────────────────────────────────────────

function ThemesPanel() {
  const [data, setData] = React.useState(null);
  const [windowDays, setWindowDays] = React.useState(60);
  React.useEffect(() => {
    fetch(`/api/insiders/theme-breakdown?window_days=${windowDays}&top_n_per_theme=8`)
      .then((r) => r.json()).then(setData).catch(() => setData(null));
  }, [windowDays]);
  if (!data) return <div className="empty-state mono muted" style={{ padding: "1rem" }}>loading…</div>;
  return (
    <div>
      <div className="influence-control-row">
        <span className="mono small muted">window</span>
        <div className="filter-pill-row">
          {[14, 30, 60, 90, 180].map(d => (
            <button key={d}
              className={`filter-pill ${windowDays === d ? "on" : ""}`}
              onClick={() => setWindowDays(d)}
            >{d}d</button>
          ))}
        </div>
      </div>
      <div className="influence-theme-grid">
        {data.themes.map((t) => (
          <article key={t.theme} className="influence-theme-card">
            <div className="itc-head">
              <span className="itc-title">{t.theme.replace(/_/g, " ")}</span>
              <span className="itc-score mono">{t.total.toFixed(1)}</span>
            </div>
            <div className="itc-sub mono small muted">
              ticker mentions {t.insider_score.toFixed(1)} · lobbying {t.lda_score.toFixed(1)}
            </div>
            {t.by_channel.length > 0 && (
              <div className="itc-chips">
                {t.by_channel.map((c) => (
                  <span key={c.channel} className="itc-chip mono">
                    {c.channel_label} · {c.weight}
                  </span>
                ))}
              </div>
            )}
            {t.top_authors.length > 0 ? (
              <div className="itc-drivers">
                <div className="itc-drivers-head mono">TOP DRIVERS</div>
                <ul className="itc-drivers-list">
                  {t.top_authors.map((a) => (
                    <li key={a.author_id}>
                      <span className="mono itc-count">×{a.n_mentions}</span>
                      <span className="itc-author">{a.author}</span>
                      <span className="mono small muted itc-channel">· {a.channel_label}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="mono small muted itc-empty">No ticker drivers this window</div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}


// ── Per-author leaderboard ─────────────────────────────────────────────────

function AuthorThemesPanel() {
  const [data, setData] = React.useState(null);
  const [minTrust, setMinTrust] = React.useState(1.0);
  React.useEffect(() => {
    fetch(`/api/insiders/author-themes?min_trust=${minTrust}&window_days=90&limit=40`)
      .then((r) => r.json()).then(setData).catch(() => setData(null));
  }, [minTrust]);
  if (!data) return <div className="dim">loading…</div>;
  const rows = data.authors || [];
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <label className="dim">min trust
          <input type="number" min={0} max={3} step={0.1} value={minTrust}
                 onChange={(e) => setMinTrust(Number(e.target.value))}
                 style={{ marginLeft: 6, width: 60 }} />
        </label>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "#aaa" }}>
            <th style={{ padding: "6px 8px" }}>Author</th>
            <th>Channel</th>
            <th>Trust</th>
            <th>Drops</th>
            <th>Top tickers</th>
            <th>Bias</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.author_id} style={{ borderTop: "1px solid #2a2a32" }}>
              <td style={{ padding: "6px 8px" }}>{a.display_name}</td>
              <td className="dim">{a.channel}</td>
              <td className="mono">{a.trust_weight?.toFixed(1)}</td>
              <td className="mono">{a.n_drops}</td>
              <td>{(a.top_tickers || []).slice(0, 4).map((t) => `${t.ticker}×${t.n}`).join(" · ")}</td>
              <td className="dim">{Object.entries(a.bias_distribution || {}).map(([k, v]) => `${k}:${v}`).join(", ")}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={6} className="dim" style={{ padding: 16 }}>No authors at min_trust ≥ {minTrust} in the last 90d.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}


// ── Timeline (Trades / Contracts) ──────────────────────────────────────────

function Timeline({ channels, kind }) {
  const [events, setEvents] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [focusEvent, setFocusEvent] = React.useState(null);
  React.useEffect(() => {
    setLoading(true);
    fetch(`/api/insiders/timeline?channels=${channels.join(",")}&limit=120`)
      .then((r) => r.json())
      .then((j) => setEvents(j.events || []))
      .finally(() => setLoading(false));
  }, [channels.join(",")]);
  // Group by day
  const days = React.useMemo(() => {
    const map = {};
    for (const ev of events) {
      const day = (ev.filed_at || "").slice(0, 10) || "unknown";
      (map[day] ||= []).push(ev);
    }
    return Object.entries(map).sort((a, b) => (b[0] > a[0] ? 1 : -1));
  }, [events]);
  if (loading) return <div className="dim">loading…</div>;
  if (!events.length) {
    return <div className="dim" style={{ padding: 16 }}>
      No {kind.toLowerCase()} events yet. Run <span className="mono">insiders pull --source all</span> to populate.
    </div>;
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 24 }}>
      <div>
        {days.map(([day, evs]) => (
          <div key={day} style={{ marginBottom: 18 }}>
            <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>{day}</div>
            {evs.map((ev) => (
              <div key={ev.document_id}
                   onClick={() => setFocusEvent(ev)}
                   style={{
                     padding: "8px 12px",
                     background: focusEvent?.document_id === ev.document_id ? "#1f1f28" : "var(--panel, #14141a)",
                     borderLeft: `3px solid ${channelColor(ev.channel)}`,
                     marginBottom: 6, borderRadius: 4,
                     cursor: "pointer", fontSize: 12,
                   }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>
                    <strong>{ev.author}</strong>
                    {ev.ticker && <span className="mono" style={{ marginLeft: 8, color: "var(--gold, #e3b04b)" }}>${ev.ticker}</span>}
                    {ev.side && <span className="dim mono" style={{ marginLeft: 6 }}>{ev.side}</span>}
                  </span>
                  <span className="dim mono" style={{ fontSize: 10 }}>{ev.channel_label}</span>
                </div>
                {ev.note && <div className="dim" style={{ fontSize: 11, marginTop: 2 }}>{ev.note}</div>}
              </div>
            ))}
          </div>
        ))}
      </div>
      <aside style={{ position: "sticky", top: 16, alignSelf: "start" }}>
        {focusEvent ? (
          <div style={{ padding: 14, background: "var(--panel, #14141a)", borderRadius: 8 }}>
            <h3 style={{ marginTop: 0, fontSize: 14 }}>{focusEvent.author}</h3>
            <div className="dim mono" style={{ fontSize: 10 }}>{focusEvent.source_id}</div>
            <div style={{ marginTop: 10, fontSize: 12 }}>
              {focusEvent.ticker && <div>Ticker: <span className="mono">${focusEvent.ticker}</span> {focusEvent.side}</div>}
              {focusEvent.conviction && <div>Conviction: {focusEvent.conviction}/5</div>}
              <div className="dim" style={{ marginTop: 6 }}>{focusEvent.filed_at}</div>
            </div>
            <pre style={{ marginTop: 12, padding: 8, background: "#0e0e14", fontSize: 11, whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
              {focusEvent.raw_text}
            </pre>
            {focusEvent.source_url && (
              <a href={focusEvent.source_url} target="_blank" rel="noopener noreferrer"
                 style={{ display: "inline-block", marginTop: 10, fontSize: 12 }}>
                open source ↗
              </a>
            )}
          </div>
        ) : (
          <div className="dim" style={{ padding: 16, fontSize: 12 }}>
            Click an event to see the raw filing text + source link.
          </div>
        )}
      </aside>
    </div>
  );
}

function channelColor(channel) {
  const map = {
    gov_insider: "#5fb3ff",
    corp_insider: "#9b6ee8",
    large_holder: "#e3b04b",
    fed_spend: "#48c984",
    lobbying: "#e98073",
    social: "#cccccc",
  };
  return map[channel] || "#777";
}


// ── Existing lobbying force-directed graph (now wrapped) ───────────────────

function LobbyingGraph() {
  const [period, setPeriod] = React.useState("2026-Q1");
  const [minAmount, setMinAmount] = React.useState(50000);
  const [focus, setFocus] = React.useState(null);

  const { data, loading, err } = useGraphData(period, minAmount, focus);
  const panel = useSidePanel(focus, period);

  const W = 920, H = 560;
  const laidOut = React.useMemo(
    () => runForceLayout(data.nodes, data.links, W, H),
    [data.nodes, data.links]
  );
  const posById = React.useMemo(() => {
    const m = new Map();
    for (const p of laidOut) m.set(p.id, p);
    return m;
  }, [laidOut]);

  const focusNode = focus && data.nodes.find((n) => n.id === focus);

  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", marginBottom: 12 }}>
        <span className="dim mono">{data.nodes.length} nodes · {data.links.length} edges</span>
      </div>

      <div className="filters" style={{ display: "flex", gap: 16, marginBottom: 16, alignItems: "center" }}>
        <label className="dim">period
          <select value={period} onChange={(e) => { setFocus(null); setPeriod(e.target.value); }}
                  style={{ marginLeft: 6 }}>
            {["2026-Q1", "2026-Q2", "2025-Q4", "2025-Q3", ""].map((p) => (
              <option key={p || "all"} value={p}>{p || "(all)"}</option>
            ))}
          </select>
        </label>
        <label className="dim">min $ spend
          <input
            type="number"
            value={minAmount}
            step={10000}
            min={0}
            onChange={(e) => { setFocus(null); setMinAmount(Number(e.target.value) || 0); }}
            style={{ marginLeft: 6, width: 110 }}
          />
        </label>
        {focus && (
          <button className="btn-small" onClick={() => setFocus(null)}>
            ← clear focus on {focusNode ? focusNode.label : focus}
          </button>
        )}
        {loading && <span className="dim">loading…</span>}
        {err && <span style={{ color: "#e98073" }}>error: {err}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: `${W}px 1fr`, gap: 24 }}>
        <svg width={W} height={H} style={{ background: "var(--panel, #14141a)", borderRadius: 8 }}>
          {data.links.map((l, i) => {
            const a = posById.get(typeof l.source === "string" ? l.source : l.source.id);
            const b = posById.get(typeof l.target === "string" ? l.target : l.target.id);
            if (!a || !b) return null;
            const w = l.amount_usd ? Math.max(0.5, Math.log10(l.amount_usd + 1) / 3) : 0.5;
            return (
              <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    stroke="#666" strokeOpacity={0.35} strokeWidth={w} />
            );
          })}
          {laidOut.map((n) => {
            const r = 4 + Math.min(14, Math.log10((n.value || 1) + 1) * 2);
            const fill = COLORS[n.kind] || COLORS.other;
            const isFocus = focus === n.id;
            return (
              <g key={n.id} style={{ cursor: "pointer" }}
                 onClick={() => setFocus(n.id === focus ? null : n.id)}>
                <circle cx={n.x} cy={n.y} r={r} fill={fill}
                        stroke={isFocus ? "#fff" : "#0008"} strokeWidth={isFocus ? 2 : 1} />
                {(isFocus || r >= 8) && (
                  <text x={n.x + r + 3} y={n.y + 3} fontSize={10} fill="#ddd">
                    {n.label.length > 32 ? n.label.slice(0, 30) + "…" : n.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        <aside className="influence-side" style={{ minWidth: 220 }}>
          {!focus && (
            <div className="dim" style={{ padding: 12 }}>
              Click a node to focus its ego-net and load its issues + agencies.
              <div style={{ marginTop: 16 }}>
                {Object.entries(COLORS).map(([kind, color]) => (
                  <div key={kind} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                    <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, background: color }} />
                    {kind}
                  </div>
                ))}
              </div>
            </div>
          )}
          {focus && panel && (
            <div style={{ padding: 12 }}>
              <h3 style={{ marginTop: 0 }}>{focusNode ? focusNode.label : focus}</h3>
              <div className="dim mono" style={{ fontSize: 11 }}>{focus}</div>
              <Section title="Top issues" rows={panel.top_issues} />
              <Section title="Top targeted agencies" rows={panel.top_agencies} />
              <Section title="Lobbyists employed" rows={panel.lobbyists} />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}


function Section({ title, rows }) {
  if (!rows || !rows.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 }}>{title}</div>
      <ul style={{ paddingLeft: 16, margin: "4px 0 0 0" }}>
        {rows.map((r) => (
          <li key={r.node} style={{ fontSize: 12 }}>
            <span className="dim mono" style={{ marginRight: 6 }}>×{r.n}</span>
            {r.node.includes(":") ? r.node.split(":", 2)[1] : r.node}
          </li>
        ))}
      </ul>
    </div>
  );
}


Object.assign(window, { Influence });
