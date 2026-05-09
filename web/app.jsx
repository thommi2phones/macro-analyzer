// App shell + routing.

const { useState: useS, useMemo: useM, useEffect: useE } = React;

function App() {
  const [view, setView] = useS("positioning");
  const [openSig, setOpenSig] = useS(null);

  // Tweaks
  const [tw, setTweak] = useTweaks(/*EDITMODE-BEGIN*/{
    "accent": "gold",
    "density": "default",
    "showMobile": true
  }/*EDITMODE-END*/);

  useE(() => {
    document.documentElement.setAttribute("data-accent", tw.accent);
    document.documentElement.setAttribute("data-density", tw.density);
  }, [tw.accent, tw.density]);

  const D = window.MA_DATA;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">M</div>
          <div>
            <div className="brand-name">Macro Analyzer</div>
            <div className="brand-sub">Positioning desk · v3 thesis <span className="brand-version">build 2026.05.23-r4</span></div>
          </div>
        </div>
        <nav className="nav">
          <button className={`nav-tab ${view === "positioning" ? "on" : ""}`} onClick={() => setView("positioning")}>
            <span className="tab-num">/01</span>positioning
          </button>
          <button className={`nav-tab ${view === "journal" ? "on" : ""}`} onClick={() => setView("journal")}>
            <span className="tab-num">/02</span>journal
          </button>
          <button className={`nav-tab ${view === "dev" ? "on" : ""}`} onClick={() => setView("dev")}>
            <span className="tab-num">/03</span>dev
          </button>
          <button className={`nav-tab ${view === "inbox" ? "on" : ""}`} onClick={() => setView("inbox")}>
            <span className="tab-num">/04</span>inbox
          </button>
        </nav>
        <div className="topbar-spacer"></div>
        <div className="topbar-right">
          <span className="tb-status"><span className="dot-live"></span> LIVE · 26 sources</span>
          <span className="tb-status">
            <span className="rb-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--gold)", display: "inline-block" }}></span>
            {D.regime.framework.label.toUpperCase()} · {Math.round(D.regime.framework.confidence * 100)}%
          </span>
          <div className="tb-clock">
            <span className="tb-clock-time">14:23 ET</span>
            <span className="tb-clock-day">FRI · MAY 22</span>
          </div>
        </div>
      </header>

      {view === "positioning" && <KpiStrip />}
      {view === "positioning" && (
        <>
          <Positioning
            onOpenReasoning={(s) => setOpenSig(s)}
            onOpenTradeForm={() => {}}
          />
          {tw.showMobile && (
            <section className="block">
              <header className="block-head sm">
                <div className="block-title">
                  <span className="block-num mono">P9</span>
                  <span>Mobile preview · /positioning</span>
                  <span className="block-sub">phone subset · same data, same grammar</span>
                </div>
              </header>
              <div className="mobile-preview-wrap">
                <MobilePreview />
              </div>
            </section>
          )}
        </>
      )}
      {view === "journal" && <Journal />}
      {view === "dev" && <Dev />}
      {view === "inbox" && <Inbox />}

      <DrillSheet
        open={!!openSig}
        onClose={() => setOpenSig(null)}
        title={openSig ? `Reasoning trail · ${openSig.asset}` : ""}
        subtitle="Why this · why now · whose voice"
      >
        {openSig && <ReasoningTrail signal={openSig} />}
      </DrillSheet>

      <footer className="app-foot">
        <span>MACRO ANALYZER · INTERNAL · L. PIROLA</span>
        <span><a href="#">git@macro:hl-research</a> · 5 agents online</span>
      </footer>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Accent">
          <TweakRadio
            label="Accent color"
            value={tw.accent}
            options={["gold", "amber", "green", "violet", "blue"]}
            onChange={(v) => setTweak("accent", v)}
          />
        </TweakSection>
        <TweakSection label="Density">
          <TweakRadio
            label="Row density"
            value={tw.density}
            options={["compact", "default", "cozy"]}
            onChange={(v) => setTweak("density", v)}
          />
        </TweakSection>
        <TweakSection label="Mobile preview">
          <TweakToggle
            label="Show on positioning"
            value={tw.showMobile}
            onChange={(v) => setTweak("showMobile", v)}
          />
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

function KpiStrip() {
  const k = window.MA_DATA.kpis;
  return (
    <div className="kpi-strip">
      <div className="kpi">
        <div className="kpi-lbl">Cash posture</div>
        <div className="kpi-val">{k.cashPosture.label}</div>
        <div className="kpi-sub">
          {k.cashPosture.pct}% cash <span className={k.cashPosture.delta >= 0 ? "pos" : "neg"}>
            {k.cashPosture.delta >= 0 ? "+" : ""}{k.cashPosture.delta}pp
          </span>
        </div>
      </div>
      <div className="kpi">
        <div className="kpi-lbl">Active trades</div>
        <div className="kpi-val">{k.activeTrades.count}</div>
        <div className="kpi-sub">${(k.activeTrades.exposureUsd / 1000).toFixed(1)}k exposure</div>
      </div>
      <div className="kpi">
        <div className="kpi-lbl">P&amp;L today</div>
        <div className={`kpi-val ${k.pnlToday.usd >= 0 ? "pos" : "neg"}`}>
          {k.pnlToday.usd >= 0 ? "+" : ""}${(k.pnlToday.usd / 1000).toFixed(2)}k
        </div>
        <div className={`kpi-sub ${k.pnlToday.pct >= 0 ? "pos" : "neg"}`}>
          {k.pnlToday.pct >= 0 ? "+" : ""}{k.pnlToday.pct.toFixed(2)}%
        </div>
      </div>
      <div className="kpi">
        <div className="kpi-lbl">P&amp;L 7d</div>
        <div className={`kpi-val ${k.pnlWeek.usd >= 0 ? "pos" : "neg"}`}>
          {k.pnlWeek.usd >= 0 ? "+" : ""}${(k.pnlWeek.usd / 1000).toFixed(2)}k
        </div>
        <div className={`kpi-sub ${k.pnlWeek.pct >= 0 ? "pos" : "neg"}`}>
          {k.pnlWeek.pct >= 0 ? "+" : ""}{k.pnlWeek.pct.toFixed(2)}%
        </div>
      </div>
      <div className="kpi">
        <div className="kpi-lbl">Signals ≥ 75</div>
        <div className="kpi-val gold">{k.signalsHigh.count}</div>
        <div className="kpi-sub">
          <span className={k.signalsHigh.deltaVsYesterday >= 0 ? "pos" : "neg"}>
            {k.signalsHigh.deltaVsYesterday >= 0 ? "+" : ""}{k.signalsHigh.deltaVsYesterday}
          </span> vs yesterday
        </div>
      </div>
      <div className="kpi">
        <div className="kpi-lbl">Spend today</div>
        <div className="kpi-val">${k.spendToday.usd.toFixed(2)}</div>
        <div className="kpi-sub">cap ${k.spendToday.capUsd}</div>
        <div className="kpi-meter"><i style={{ width: `${(k.spendToday.usd / k.spendToday.capUsd) * 100}%` }}></i></div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
