// /identify — step ③ of the funnel.
//
// Left rail: list of plans grouped by status. Right pane: editor for
// the selected plan with entry/stop/targets/sizing fields, gate
// evaluator output, concept lineage chip, and the "activate" button
// that writes a trades row and flips the plan to live.

function Identify({ focusPlanId, onActivated }) {
  const D = window.MA_DATA;
  const [, force] = React.useState(0);
  const rerender = () => force(n => n + 1);

  const plans = D.plans || [];
  const drafts = plans.filter(p => p.status === "draft");
  const live = plans.filter(p => p.status === "live");
  const closed = plans.filter(p => p.status === "closed" || p.status === "cancelled");

  const [selectedId, setSelectedId] = React.useState(
    focusPlanId || (drafts[0] && drafts[0].id) || (plans[0] && plans[0].id) || null
  );
  React.useEffect(() => {
    if (focusPlanId) setSelectedId(focusPlanId);
  }, [focusPlanId]);

  const selected = plans.find(p => p.id === selectedId);

  const updatePlan = (patch) => {
    if (!selected) return;
    Object.assign(selected, patch);
    rerender();
  };

  const activatePlan = () => {
    if (!selected) return;
    if (selected.entry == null || selected.stop == null) {
      alert("Plan needs entry and stop before activation.");
      return;
    }
    const tradeId = `t-2026-${String(900 + Math.floor(Math.random() * 99)).padStart(3, "0")}`;
    selected.status = "live";
    selected.tradeId = tradeId;
    selected.activatedAt = new Date().toISOString().slice(0, 16).replace("T", " ");
    // Push into activeTrades so the /live and Positioning views see it.
    const target = (selected.targets && selected.targets[0] && selected.targets[0].price) || 0;
    D.activeTrades = (D.activeTrades || []).concat([{
      id: tradeId,
      asset: selected.asset,
      side: selected.side,
      entry: selected.entry,
      stop: selected.stop,
      target,
      sizeUsd: selected.sizeUsd || 0,
      ageDays: 0,
      pnlPct: 0,
      pnlUsd: 0,
      regimeAtOpen: (D.regime && D.regime.framework && D.regime.framework.label) || "—",
      scoreAtOpen: 0,
      scoreNow: 0,
      status: "running",
      planId: selected.id,
    }]);
    if (onActivated) onActivated(tradeId);
    rerender();
  };

  const cancelPlan = () => {
    if (!selected) return;
    selected.status = "cancelled";
    selected.cancelledAt = new Date().toISOString().slice(0, 16).replace("T", " ");
    rerender();
  };

  // Stub gate evaluator — reuses the Piece B/E advisory shape so the
  // panel renders consistently whether the backend wires up or not.
  const gate = (() => {
    if (!selected) return null;
    const reasons = [];
    if (selected.entry == null) reasons.push("entry missing");
    if (selected.stop == null) reasons.push("stop missing");
    if (selected.entry != null && selected.stop != null) {
      const risk = Math.abs(selected.entry - selected.stop);
      if (risk / selected.entry > 0.15) reasons.push("risk > 15% of entry");
    }
    if (!selected.thesis) reasons.push("thesis missing");
    if (!selected.invalidation) reasons.push("invalidation missing");
    if (reasons.length === 0) return { status: "pass", reasons: ["all gates clear"] };
    if (reasons.length <= 2) return { status: "warn", reasons };
    return { status: "block", reasons };
  })();

  const concept = selected && selected.conceptId
    ? (D.concepts || []).find(c => c.id === selected.conceptId)
    : null;

  return (
    <div className="identify-view two-col-3070">
      <aside className="block">
        <header className="block-head sm">
          <div className="block-title">
            <span className="block-num mono">I1</span>
            <span>Plans</span>
            <span className="block-sub">
              {drafts.length} draft · {live.length} live · {closed.length} closed
            </span>
          </div>
        </header>
        <div className="plan-list">
          {drafts.length > 0 && (
            <div className="plan-group-head muted small">DRAFT</div>
          )}
          {drafts.map(p => (
            <PlanListItem key={p.id} plan={p} selected={p.id === selectedId} onClick={() => setSelectedId(p.id)} />
          ))}
          {live.length > 0 && (
            <div className="plan-group-head muted small">LIVE</div>
          )}
          {live.map(p => (
            <PlanListItem key={p.id} plan={p} selected={p.id === selectedId} onClick={() => setSelectedId(p.id)} />
          ))}
          {closed.length > 0 && (
            <div className="plan-group-head muted small">CLOSED / CANCELLED</div>
          )}
          {closed.map(p => (
            <PlanListItem key={p.id} plan={p} selected={p.id === selectedId} onClick={() => setSelectedId(p.id)} />
          ))}
          {plans.length === 0 && (
            <div className="empty-state muted small">
              No plans yet. Promote an active concept from /concepts.
            </div>
          )}
        </div>
      </aside>

      <div className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">I2</span>
            <span>{selected ? `Plan editor · ${selected.asset}` : "Plan editor"}</span>
            <span className="block-sub">
              {selected
                ? `${selected.side} · ${selected.status}`
                : "select a plan from the list"}
            </span>
          </div>
          {selected && concept && (
            <div className="block-actions">
              <span className="lineage-chip mono small">
                from concept {concept.id} · marked {concept.markedAt}
              </span>
            </div>
          )}
        </header>

        {selected ? (
          <div className="plan-editor">
            <div className="form-row">
              <label>
                <span className="form-lbl">ENTRY</span>
                <input
                  className="form-input mono"
                  inputMode="decimal"
                  disabled={selected.status !== "draft"}
                  value={selected.entry == null ? "" : selected.entry}
                  onChange={e => updatePlan({ entry: e.target.value === "" ? null : parseFloat(e.target.value) })}
                  placeholder="41.20"
                />
              </label>
              <label>
                <span className="form-lbl">STOP</span>
                <input
                  className="form-input mono"
                  inputMode="decimal"
                  disabled={selected.status !== "draft"}
                  value={selected.stop == null ? "" : selected.stop}
                  onChange={e => updatePlan({ stop: e.target.value === "" ? null : parseFloat(e.target.value) })}
                  placeholder="39.40"
                />
              </label>
              <label>
                <span className="form-lbl">SIZE $</span>
                <input
                  className="form-input mono"
                  inputMode="decimal"
                  disabled={selected.status !== "draft"}
                  value={selected.sizeUsd == null ? "" : selected.sizeUsd}
                  onChange={e => updatePlan({ sizeUsd: e.target.value === "" ? null : parseFloat(e.target.value) })}
                  placeholder="32000"
                />
              </label>
              <label>
                <span className="form-lbl">HORIZON</span>
                <select
                  className="form-input"
                  disabled={selected.status !== "draft"}
                  value={selected.timeHorizon || "swing"}
                  onChange={e => updatePlan({ timeHorizon: e.target.value })}
                >
                  <option value="intraday">intraday</option>
                  <option value="swing">swing</option>
                  <option value="position">position</option>
                </select>
              </label>
            </div>

            <div className="form-row">
              <label className="grow">
                <span className="form-lbl">TARGETS · comma-separated prices</span>
                <input
                  className="form-input mono"
                  disabled={selected.status !== "draft"}
                  value={(selected.targets || []).map(t => t.price).join(", ")}
                  onChange={e => {
                    const prices = e.target.value.split(",").map(s => parseFloat(s.trim())).filter(n => !isNaN(n));
                    const weight = prices.length ? 1 / prices.length : 0;
                    updatePlan({ targets: prices.map(p => ({ price: p, weight })) });
                  }}
                  placeholder="44.50, 47.50"
                />
              </label>
            </div>

            <div className="form-row">
              <label className="grow">
                <span className="form-lbl">THESIS · why this, why now</span>
                <textarea
                  className="form-input"
                  disabled={selected.status !== "draft"}
                  value={selected.thesis || ""}
                  onChange={e => updatePlan({ thesis: e.target.value })}
                  rows={2}
                  placeholder="Reactor restart cadence accelerating; physical U3O8 tape firming."
                />
              </label>
            </div>

            <div className="form-row">
              <label className="grow">
                <span className="form-lbl">INVALIDATION · what breaks this</span>
                <textarea
                  className="form-input"
                  disabled={selected.status !== "draft"}
                  value={selected.invalidation || ""}
                  onChange={e => updatePlan({ invalidation: e.target.value })}
                  rows={2}
                  placeholder="Daily close below 39.40 or U3O8 spot breaks $90."
                />
              </label>
            </div>

            <VisionConfirmation
              plan={selected}
              onChange={(images) => updatePlan({ visionImages: images })}
            />

            <div className={`gate-panel gate-${gate.status}`}>
              <div className="gate-head">
                <span className="gate-status mono">GATE · {gate.status.toUpperCase()}</span>
                <span className="gate-sub muted small">advisory check before activation</span>
              </div>
              <ul className="gate-reasons">
                {gate.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>

            <div className="form-actions">
              {selected.status === "draft" && (
                <>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={gate.status === "block"}
                    onClick={activatePlan}
                  >
                    activate trade ↵
                  </button>
                  <button type="button" className="btn-ghost" onClick={cancelPlan}>
                    cancel plan
                  </button>
                </>
              )}
              {selected.status === "live" && (
                <span className="form-ok">
                  ● live · trade {selected.tradeId} · view on /live
                </span>
              )}
              {selected.status === "cancelled" && (
                <span className="muted small">cancelled {selected.cancelledAt}</span>
              )}
            </div>
          </div>
        ) : (
          <div className="empty-state muted">
            No plan selected. Pick one from the list, or promote a concept on /concepts.
          </div>
        )}
      </div>
    </div>
  );
}

// Vision confirmation — drop chart screenshots tied to a plan and run
// them through the existing /charts/analyze endpoint. The plan keeps
// its own list of images + per-image analysis so the same chart can be
// re-reviewed later from /live. Falls back to local-only thumbnails
// when the backend isn't running (static preview).
function VisionConfirmation({ plan, onChange }) {
  const dropRef = React.useRef(null);
  const [busy, setBusy] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const images = (plan && plan.visionImages) || [];
  const disabled = plan && plan.status !== "draft";

  const writeBack = (next) => onChange(next);

  const onFiles = (fileList) => {
    if (disabled) return;
    setErr(null);
    const accepted = Array.from(fileList || []).filter(f => f.type.startsWith("image/"));
    if (!accepted.length) return;
    const additions = accepted.map(f => ({
      id: `img-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      url: URL.createObjectURL(f),
      name: f.name,
      timeframe: "1D",
      note: "",
      analysis: null,
      analysisStatus: "idle",
      _file: f,
    }));
    writeBack([...images, ...additions]);
  };

  const removeImage = (id) => {
    const it = images.find(x => x.id === id);
    if (it && it.url && it.url.startsWith("blob:")) URL.revokeObjectURL(it.url);
    writeBack(images.filter(x => x.id !== id));
  };

  const updateImage = (id, patch) => {
    writeBack(images.map(x => x.id === id ? { ...x, ...patch } : x));
  };

  const runAnalysis = async (img) => {
    setBusy(img.id);
    setErr(null);
    updateImage(img.id, { analysisStatus: "running" });
    try {
      const res = await fetch("/charts/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: img.url,
          asset_context: `${plan.asset} ${plan.side} · ${img.timeframe || "1D"}`,
          additional_context: `Plan thesis: ${plan.thesis || "—"}\nInvalidation: ${plan.invalidation || "—"}`,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      updateImage(img.id, { analysis: data, analysisStatus: "done" });
    } catch (e) {
      updateImage(img.id, { analysisStatus: "error" });
      setErr(`Backend not reachable — ${e.message}. Images are stored on the plan; analysis runs when the API is up.`);
    } finally {
      setBusy(null);
    }
  };

  // Paste-from-clipboard: only active while this section is focused.
  React.useEffect(() => {
    const onPaste = (e) => {
      if (!document.activeElement || !dropRef.current?.contains(document.activeElement)) return;
      const items = e.clipboardData?.items || [];
      const files = [];
      for (const it of items) {
        if (it.type && it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) onFiles(files);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [images, disabled]);

  return (
    <div className="vision-block" ref={dropRef} tabIndex={-1}>
      <div className="vision-head">
        <span className="form-lbl">VISION · CHART CONFIRMATION</span>
        <span className="vision-sub muted small">
          drop, paste, or pick chart screenshots · {images.length} attached
        </span>
      </div>
      <div
        className={`vision-drop ${disabled ? "disabled" : ""}`}
        onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer?.files); }}
        onDragOver={(e) => e.preventDefault()}
      >
        <input
          type="file"
          accept="image/*"
          multiple
          disabled={disabled}
          onChange={(e) => onFiles(e.target.files)}
        />
        <span className="muted small">
          Drop here · ⌘V paste · or click to pick
        </span>
      </div>
      {err && <div className="vision-err small">{err}</div>}
      {images.length > 0 && (
        <div className="vision-grid">
          {images.map(img => (
            <div key={img.id} className="vision-tile">
              <img src={img.url} alt={img.name} />
              <div className="vision-tile-meta">
                <select
                  className="form-input mono"
                  disabled={disabled}
                  value={img.timeframe || "1D"}
                  onChange={(e) => updateImage(img.id, { timeframe: e.target.value })}
                >
                  {["15m","1H","4H","1D","1W"].map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <button
                  type="button"
                  className="btn-ghost xs"
                  disabled={disabled || busy === img.id}
                  onClick={() => runAnalysis(img)}
                >
                  {busy === img.id ? "analyzing…" :
                   img.analysisStatus === "done" ? "re-analyze" : "analyze"}
                </button>
                <button
                  type="button"
                  className="btn-ghost xs"
                  disabled={disabled}
                  onClick={() => removeImage(img.id)}
                >
                  remove
                </button>
              </div>
              {img.analysisStatus === "running" && (
                <div className="vision-status muted small">analyzing…</div>
              )}
              {img.analysisStatus === "done" && img.analysis && (
                <div className="vision-result small">
                  {img.analysis.summary ||
                   img.analysis.analysis ||
                   JSON.stringify(img.analysis).slice(0, 200)}
                </div>
              )}
              {img.analysisStatus === "error" && (
                <div className="vision-status neg small">analyze failed · retry when API is up</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PlanListItem({ plan, selected, onClick }) {
  return (
    <button className={`plan-list-item ${selected ? "on" : ""}`} onClick={onClick}>
      <div className="pli-head">
        <span className="mono asset-cell">{plan.asset}</span>
        <SideLabel side={plan.side} />
        <span className={`status-chip status-${plan.status}`}>{plan.status}</span>
      </div>
      <div className="pli-meta mono small muted">
        {plan.entry != null ? `entry ${plan.entry}` : "no entry"} ·
        {" "}{plan.stop != null ? `stop ${plan.stop}` : "no stop"}
        {plan.conceptId ? ` · from ${plan.conceptId}` : ""}
      </div>
    </button>
  );
}

Object.assign(window, { Identify });
