// sources.jsx — Unified source roster, grouped by conviction tier.
//
// One place to see EVERY input stream — telegram authors, substack
// newsletters, podcasts, data feeds — grouped by the operator-assigned
// conviction tier (T0 highest → T4), regardless of input type. Replaces
// the scattered source rosters that previously lived across the streams,
// influence, and manual-input tabs.
//
// Data: window.MA_DATA.sourceHealth[] — each row carries `tier`
// (T0..T4 | infra | self), name, kind, weight, attrib30d, tags, plus the
// detail fields SourceDetailPanel renders in the drill-down sheet.

// Hooks accessed via React.* inline (not top-level destructured) so this
// script can't collide with another text/babel module's global bindings.

// Tier → display metadata. `infra` (FRED/Finnhub/news) and `self`
// (manual notes / chart drops) sit below the T0–T4 conviction ladder.
const _TIER_META = {
  T0:    { label: "T0", blurb: "highest conviction · act on these",        cls: "tier-t0" },
  T1:    { label: "T1", blurb: "high conviction · strong track record",    cls: "tier-t1" },
  T2:    { label: "T2", blurb: "watch · useful but unproven",              cls: "tier-t2" },
  T3:    { label: "T3", blurb: "experimental · low weight",                cls: "tier-t3" },
  T4:    { label: "T4", blurb: "noise / context only",                     cls: "tier-t4" },
  infra: { label: "INFRA", blurb: "data feeds · not conviction-ranked",    cls: "tier-infra" },
  self:  { label: "SELF",  blurb: "your own notes + chart drops",          cls: "tier-self" },
  "":    { label: "UNTIERED", blurb: "no tier assigned yet",               cls: "tier-none" },
};
const _TIER_ORDER = ["T0", "T1", "T2", "T3", "T4", "infra", "self", ""];

function SourceCard({ r, onOpen, isGroupHead }) {
  const attrib = r.attrib30d || 0;
  const meta = _TIER_META[r.tier] || _TIER_META[""];
  const isMember = (r.group_membership || []).length > 0;
  const subtitle = r.author && r.author !== r.name ? r.author : r.kind;
  const cls = "src-card" + (isGroupHead ? " src-card-grouphead" : "") + (isMember ? " src-card-member" : "");
  return (
    <article className={cls} onClick={() => onOpen(r)}>
      <div className="src-card-top">
        <span className={`src-tier-badge ${meta.cls}`}>{meta.label}</span>
        <span className="src-card-name">{r.name}</span>
        {isGroupHead && <span className="src-card-grouptag mono" title="group channel">◆</span>}
        <span className="src-card-drill muted">→</span>
      </div>
      <div className="src-card-kind muted small">{subtitle}</div>
      <div className="src-card-stats mono small">
        <span title="trust weight">w {(r.weight || 0).toFixed(2)}</span>
        <span className={attrib >= 0 ? "pos" : "neg"} title="30d attribution">
          {attrib >= 0 ? "+" : ""}${(attrib / 1000).toFixed(1)}k
        </span>
      </div>
      {(r.tags || []).length > 0 && (
        <div className="src-card-tags">
          {(r.tags || []).slice(0, 4).map(t => (
            <span key={t} className="tag-chip">{t}</span>
          ))}
        </div>
      )}
    </article>
  );
}

function Sources() {
  const D = window.MA_DATA || {};
  const all = D.sourceHealth || [];

  const [q, setQ] = React.useState("");
  const [tierFilter, setTierFilter] = React.useState("ALL");
  const [openSrc, setOpenSrc] = React.useState(null);

  // Author conviction analysis (chart-drop derived) — the rich per-author
  // breakdown (conviction picks, top tickers, recurring setups) shown in
  // the drill-down. Fetched once; matched to a clicked source by name.
  const [analysis, setAnalysis] = React.useState(null);
  React.useEffect(() => {
    let cancelled = false;
    fetch("/api/manual/themes/trusted?window_days=90")
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (!cancelled && j) setAnalysis(j.authors || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Normalized matcher: registry ids/names drift from seeded author slugs
  // (emoji, underscores, group↔member aliasing), so strip to alnum and
  // match against display_name + both halves of author_id.
  const norm = (x) => String(x || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  // Known aliases where a registry source and its seeded analysis author
  // have different names (same entity). normalized registry → analysis.
  const SOURCE_ALIASES = {
    featherhandstrading: "markettraders",
    featherhands: "markettraders",
  };
  const matchAuthor = React.useCallback((src) => {
    if (!analysis || !src) return null;
    const keys = new Set([norm(src.source_id), norm(src.name), norm(src.author)].filter(Boolean));
    for (const k of [...keys]) { if (SOURCE_ALIASES[k]) keys.add(SOURCE_ALIASES[k]); }
    return analysis.find(a => {
      const aKeys = [norm(a.display_name), ...String(a.author_id || "").split(":").map(norm)];
      return aKeys.some(k => k && keys.has(k));
    }) || null;
  }, [analysis]);

  // Tier counts across the full roster (for the filter pills + header).
  const tierCounts = React.useMemo(() => {
    const c = {};
    for (const r of all) { const t = r.tier || ""; c[t] = (c[t] || 0) + 1; }
    return c;
  }, [all]);

  // Apply search + tier filter.
  const filtered = React.useMemo(() => {
    let rows = all.slice();
    if (tierFilter !== "ALL") rows = rows.filter(r => (r.tier || "") === tierFilter);
    if (q.trim()) {
      const needle = q.toLowerCase();
      rows = rows.filter(r =>
        (r.name || "").toLowerCase().includes(needle) ||
        (r.kind || "").toLowerCase().includes(needle) ||
        (r.author || "").toLowerCase().includes(needle) ||
        String(r.market_focus || "").toLowerCase().includes(needle) ||
        (r.tags || []).some(t => t.toLowerCase().includes(needle))
      );
    }
    return rows;
  }, [all, q, tierFilter]);

  // Group filtered rows by tier, preserving the canonical tier order.
  const groups = React.useMemo(() => {
    const g = {};
    for (const r of filtered) { const t = r.tier || ""; (g[t] = g[t] || []).push(r); }
    return g;
  }, [filtered]);

  const presentTiers = _TIER_ORDER.filter(t => groups[t] && groups[t].length);
  const convictionTiers = ["T0", "T1", "T2", "T3", "T4"].filter(t => tierCounts[t]);

  // Within a tier, cluster member authors under their parent group. A group
  // source (is_group) heads a cluster containing its own card + its members;
  // members can appear under multiple groups (e.g. Big_Nuts ∈ OG Whales +
  // Feather Hands). Everything else falls into a final "Independent" cluster.
  function clusterByGroup(tierRows) {
    const groupRows = tierRows.filter(r => r.is_group);
    const usedAsMember = new Set();
    const clusters = [];
    for (const g of groupRows) {
      const members = tierRows.filter(r =>
        !r.is_group && (
          (r.group_membership || []).includes(g.source_id) ||
          (g.group_members || []).includes(r.source_id)
        )
      );
      members.forEach(m => usedAsMember.add(m.source_id));
      clusters.push({ key: g.source_id, label: g.name, isGroup: true, cards: [g, ...members] });
    }
    const independents = tierRows.filter(r => !r.is_group && !usedAsMember.has(r.source_id));
    if (independents.length) {
      clusters.push({ key: "__independent", label: "Independent", isGroup: false, cards: independents });
    }
    return clusters;
  }

  return (
    <div className="view view-sources sources-view">
      {/* ── Header + controls ─────────────────────────────────────────── */}
      <section className="block block-quiet">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">U1</span>
            <span>Sources</span>
            <span className="block-sub">
              every input stream · grouped by conviction tier
            </span>
          </div>
          <div className="block-actions">
            <input
              className="src-search"
              placeholder="search sources, authors, tags…"
              value={q}
              onChange={e => setQ(e.target.value)}
            />
          </div>
        </header>
        <div className="block-body" style={{ paddingTop: 10 }}>
          <div className="src-tier-filter-row">
            <button
              className={`filter-pill ${tierFilter === "ALL" ? "on" : ""}`}
              onClick={() => setTierFilter("ALL")}
            >
              ALL <span className="muted">· {all.length}</span>
            </button>
            {_TIER_ORDER.filter(t => tierCounts[t]).map(t => {
              const meta = _TIER_META[t];
              return (
                <button
                  key={t || "untiered"}
                  className={`filter-pill src-tier-pill ${meta.cls} ${tierFilter === t ? "on" : ""}`}
                  onClick={() => setTierFilter(t)}
                  title={meta.blurb}
                >
                  {meta.label} <span className="muted">· {tierCounts[t]}</span>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Tier sections ─────────────────────────────────────────────── */}
      {presentTiers.length === 0 ? (
        <div className="empty-state mono muted" style={{ padding: "1.5rem" }}>
          no sources match · clear search or tier filter
        </div>
      ) : (
        presentTiers.map(t => {
          const meta = _TIER_META[t];
          const rows = groups[t];
          const clusters = clusterByGroup(rows);
          // If the tier has no real groups, render a single flat grid (no
          // "Independent" label clutter for newsletter/api tiers).
          const flat = clusters.length === 1 && !clusters[0].isGroup;
          return (
            <section key={t || "untiered"} className={`src-tier-section ${meta.cls}`}>
              <header className="src-tier-header">
                <span className={`src-tier-badge lg ${meta.cls}`}>{meta.label}</span>
                <span className="src-tier-blurb muted small">{meta.blurb}</span>
                <span className="src-tier-count mono small muted">{rows.length}</span>
              </header>
              {flat ? (
                <div className="src-card-grid">
                  {rows.map(r => (
                    <SourceCard key={r.source_id || r.name} r={r} onOpen={setOpenSrc} />
                  ))}
                </div>
              ) : (
                clusters.map(cl => (
                  <div key={cl.key} className={`src-group-cluster ${cl.isGroup ? "is-group" : "is-independent"}`}>
                    <div className="src-group-label">
                      {cl.isGroup
                        ? <><span className="src-group-tag mono">GROUP</span> {cl.label}
                            <span className="src-group-count mono muted"> · {cl.cards.length}</span></>
                        : <span className="src-group-indep mono muted">INDEPENDENT</span>}
                    </div>
                    <div className="src-card-grid">
                      {cl.cards.map(r => (
                        <SourceCard
                          key={(cl.key) + ":" + (r.source_id || r.name)}
                          r={r}
                          onOpen={setOpenSrc}
                          isGroupHead={cl.isGroup && r.is_group}
                        />
                      ))}
                    </div>
                  </div>
                ))
              )}
            </section>
          );
        })
      )}

      {/* ── Drill-down ───────────────────────────────────────────────── */}
      {/* Rich per-author analysis (conviction picks, top tickers,
          recurring setups, clickable ticker drill-down) when the source
          has chart-drop analysis; else the metadata detail panel. */}
      <DrillSheet
        open={!!openSrc}
        onClose={() => setOpenSrc(null)}
        title={openSrc ? openSrc.name : ""}
        subtitle={openSrc ? `${(_TIER_META[openSrc.tier] || _TIER_META[""]).label} · ${openSrc.kind || ""}` : ""}
      >
        {openSrc && (() => {
          const a = matchAuthor(openSrc);
          const Card = window.TrustedAuthorCard;
          const hasData = a && ((a.high_conviction_tickers || []).length ||
                                (a.top_tickers || []).length ||
                                (a.top_setups || []).length);
          if (hasData && Card) return <Card a={a} />;
          return <SourceDetailPanel s={openSrc} />;
        })()}
      </DrillSheet>
    </div>
  );
}

Object.assign(window, { Sources });
