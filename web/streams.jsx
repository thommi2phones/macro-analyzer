// /streams — who's talking about what, across the 26 live sources.
//
// Two-layer view: top is the brain's roll-up of recurring themes
// (which sources are clustering on which narrative + direction);
// below is the per-source feed with the latest item snippet, source
// weight, freshness, and 7d item count. The "26 sources LIVE" chip
// in the topbar links here.
//
// A3 — search, sort, and per-source drilldown added.

function Streams() {
  const D = window.MA_DATA;
  const s = D.streams || { topVoices: [], bySource: [], summary: "" };
  const [themeFilter, setThemeFilter] = React.useState("ALL");
  const [sortBy, setSortBy]           = React.useState("weight");
  const [srcQ, setSrcQ]               = React.useState("");
  const [openSrc, setOpenSrc]         = React.useState(null);

  const allThemes = Array.from(new Set(
    (s.bySource || []).flatMap(x => x.themes || [])
  )).sort();

  let sources = (s.bySource || []).slice();

  // Theme filter
  if (themeFilter !== "ALL") {
    sources = sources.filter(x => (x.themes || []).includes(themeFilter));
  }

  // Text search — name, kind, or tags
  if (srcQ.trim()) {
    const q = srcQ.toLowerCase();
    sources = sources.filter(x =>
      x.name.toLowerCase().includes(q) ||
      (x.kind || "").toLowerCase().includes(q) ||
      (x.themes || []).some(t => t.toLowerCase().includes(q))
    );
  }

  // Sort
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
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S1</span>
            <span>Streams · top voices</span>
            <span className="block-sub">
              brain digest · {s.asOf || "—"} · {(s.bySource || []).length} sources tracked
            </span>
          </div>
        </header>
        {s.summary && (
          <div className="streams-summary">{s.summary}</div>
        )}
        <div className="topvoices-grid">
          {s.topVoices.map(v => (
            <div key={v.theme} className={`tv-card dir-${(v.direction || "").replace(/\s+/g, "-")}`}>
              <div className="tv-head">
                <span className="tv-theme">{v.theme}</span>
                <span className="tv-dir mono small">{v.direction}</span>
              </div>
              <div className="tv-sources mono small muted">
                {v.sources.join(" · ")}
              </div>
              <p className="tv-synopsis">{v.synopsis}</p>
              <div className="tv-meta mono small muted">
                {v.items} items · last {v.lastUpdate}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">S2</span>
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
                onClick={() => setOpenSrc(src)}
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

      {/* Per-source detail drilldown */}
      <DrillSheet
        open={!!openSrc}
        onClose={() => setOpenSrc(null)}
        title={openSrc ? openSrc.name : ""}
        subtitle={openSrc ? openSrc.kind : ""}
      >
        {openSrc && <SourceDetailPanel s={openSrc} />}
      </DrillSheet>
    </div>
  );
}

Object.assign(window, { Streams });
