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
      {regime && regime.framework && (
        <div className="home-regime">
          <div className="home-regime-lbl mono small muted">FRAMEWORK REGIME</div>
          <div className="home-regime-row">
            <span className="home-regime-name">{regime.framework.label}</span>
            <span className="home-regime-conf mono">
              {Math.round(regime.framework.confidence * 100)}% conf · active {regime.framework.sinceDays}d
            </span>
            <span className="home-regime-bias mono muted">
              bias {String(regime.framework.bias || "").replace(/_/g, " ")} · size ×{regime.framework.sizingModifier.toFixed(2)}
            </span>
          </div>
        </div>
      )}

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
