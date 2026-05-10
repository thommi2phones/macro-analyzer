// /inbox — manual input layer.
//
// Drop a chart screenshot and/or paste a blurb, attach metadata
// (ticker, side, conviction, timeframe, author + channel), preview
// the auto-detected suggestions, then submit. Submissions land in
// the documents table and propagate to the watchlist on next score.

const { useState: useIS, useEffect: useIE, useRef: useIR } = React;

const SIDES = ["LONG", "SHORT", "WATCH"];
const TIMEFRAMES = ["1H", "4H", "1D", "1W"];
const CHANNEL_TYPES = ["self", "telegram", "discord", "twitter", "tradingview", "other"];

function Inbox() {
  // Form state
  const [text, setText] = useIS("");
  const [ticker, setTicker] = useIS("");
  const [side, setSide] = useIS("");
  const [conviction, setConviction] = useIS(3);
  const [timeframe, setTimeframe] = useIS("");
  const [note, setNote] = useIS("");
  const [author, setAuthor] = useIS("");
  const [channel, setChannel] = useIS("");
  const [channelType, setChannelType] = useIS("self");

  // Image state — list of {file, url} so a single drop can carry several
  // chart views (e.g. 1H + 4H + context). Append on drop/paste/picker.
  const [images, setImages] = useIS([]);
  const dropRef = useIR(null);

  // Async state
  const [previewData, setPreviewData] = useIS(null);
  const [submitting, setSubmitting] = useIS(false);
  const [submitMsg, setSubmitMsg] = useIS(null);

  // Server-side data
  const [history, setHistory] = useIS([]);
  const [authors, setAuthors] = useIS([]);

  useIE(() => { refreshHistory(); refreshAuthors(); }, []);

  function refreshHistory() {
    fetch("/api/manual/inputs?limit=20").then(r => r.json()).then(setHistory);
  }
  function refreshAuthors() {
    fetch("/api/manual/authors").then(r => r.json()).then(setAuthors);
  }

  // Drag-drop + paste-from-clipboard image handling
  useIE(() => {
    function onPaste(e) {
      const items = e.clipboardData?.items || [];
      const fresh = [];
      for (const it of items) {
        if (it.type && it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) fresh.push(f);
        }
      }
      if (fresh.length) attachFiles(fresh);
    }
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, []);

  function attachFiles(fs) {
    const accepted = Array.from(fs).filter(f => f && f.type && f.type.startsWith("image/"));
    if (!accepted.length) return;
    setImages(prev => [
      ...prev,
      ...accepted.map(f => ({ file: f, url: URL.createObjectURL(f) })),
    ]);
  }
  function removeImage(idx) {
    setImages(prev => {
      const it = prev[idx];
      if (it) URL.revokeObjectURL(it.url);
      return prev.filter((_, i) => i !== idx);
    });
  }
  function clearImages() {
    setImages(prev => {
      prev.forEach(it => URL.revokeObjectURL(it.url));
      return [];
    });
  }
  function onDrop(e) {
    e.preventDefault();
    if (e.dataTransfer.files?.length) attachFiles(e.dataTransfer.files);
  }
  function onDragOver(e) { e.preventDefault(); }

  async function runPreview() {
    if (!author.trim()) {
      setSubmitMsg({ type: "warn", text: "Add an author/source before previewing." });
      return;
    }
    const payload = buildPayload();
    const r = await fetch("/api/manual/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      setSubmitMsg({ type: "err", text: "Preview failed: " + r.status });
      return;
    }
    const data = await r.json();
    setPreviewData(data);
    // Auto-fill blanks the user hasn't touched.
    if (!ticker && data.detected_tickers?.length) setTicker(data.detected_tickers[0]);
  }

  function buildPayload() {
    return {
      text,
      metadata: {
        ticker: ticker || null,
        side: side || null,
        conviction: Number(conviction) || null,
        timeframe: timeframe || null,
        note: note || null,
      },
      author: {
        display_name: author,
        channel: channel || null,
        channel_type: channelType || null,
      },
    };
  }

  async function submit() {
    if (!author.trim()) {
      setSubmitMsg({ type: "warn", text: "Author is required." });
      return;
    }
    if (!text.trim() && images.length === 0) {
      setSubmitMsg({ type: "warn", text: "Add some text or at least one image." });
      return;
    }
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const fd = new FormData();
      fd.append("payload", JSON.stringify(buildPayload()));
      // Field name `files` matches the FastAPI `list[UploadFile]` param.
      images.forEach(({ file: f }) => fd.append("files", f, f.name));
      const r = await fetch("/api/manual/ingest", { method: "POST", body: fd });
      if (!r.ok) {
        const err = await r.text();
        setSubmitMsg({ type: "err", text: "Submit failed: " + err.slice(0, 200) });
        return;
      }
      const data = await r.json();
      const imgNote = images.length > 1 ? ` · ${images.length} images` : "";
      setSubmitMsg({
        type: "ok",
        text: `Saved · ${data.detected_tickers.join(", ") || "no tickers"} · tags ${data.tags.join(", ")}` +
              imgNote +
              (data.pending_vision ? " · vision pending" : ""),
      });
      // Reset for next drop, keep author so consecutive drops are fast.
      setText(""); setTicker(""); setSide(""); setTimeframe("");
      setNote(""); setConviction(3); clearImages(); setPreviewData(null);
      refreshHistory(); refreshAuthors();
    } finally {
      setSubmitting(false);
    }
  }

  // Author autocomplete: pick from known authors → fills name + channel + channel_type.
  function pickAuthor(a) {
    setAuthor(a.display_name || "");
    setChannel(a.channel || "");
    setChannelType(a.channel_type || "self");
  }

  return (
    <div className="inbox-view">
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">I1</span>
            <span>Manual input</span>
            <span className="block-sub">drop chart · paste blurb · attribute source</span>
          </div>
        </header>

        <div className="inbox-grid">
          {/* Left: image + text */}
          <div className="inbox-col">
            <div
              ref={dropRef}
              className={`inbox-drop ${images.length ? "has-file" : ""}`}
              onDrop={onDrop}
              onDragOver={onDragOver}
            >
              {images.length > 0 ? (
                <div className="inbox-drop-preview">
                  <div className="inbox-thumbs">
                    {images.map((it, idx) => (
                      <div key={it.url} className="inbox-thumb">
                        <img src={it.url} alt={`chart ${idx + 1}`} />
                        <button
                          className="inbox-thumb-x"
                          title="remove image"
                          onClick={() => removeImage(idx)}
                        >×</button>
                      </div>
                    ))}
                  </div>
                  <div className="inbox-drop-sub">
                    {images.length} image{images.length === 1 ? "" : "s"} attached ·
                    drop / paste / pick more
                  </div>
                  <div className="inbox-actions" style={{ marginTop: 4 }}>
                    <input type="file" accept="image/*" multiple onChange={(e) => {
                      if (e.target.files?.length) attachFiles(e.target.files);
                      e.target.value = "";
                    }} />
                    <button className="filter-pill" onClick={clearImages}>clear all</button>
                  </div>
                </div>
              ) : (
                <div className="inbox-drop-empty">
                  <div className="inbox-drop-headline">Drop chart screenshots here</div>
                  <div className="inbox-drop-sub">multiple images OK · paste from clipboard · or pick files</div>
                  <input type="file" accept="image/*" multiple onChange={(e) => {
                    if (e.target.files?.length) attachFiles(e.target.files);
                    e.target.value = "";
                  }} />
                </div>
              )}
            </div>

            <label className="inbox-label">Body / blurb</label>
            <textarea
              className="inbox-textarea"
              rows={6}
              placeholder={"Paste from Telegram/Discord/notes. Mention tickers ($BTC, $XRP). The pre-tagger and mention extractor read this."}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />

            <div className="inbox-actions">
              <button className="filter-pill on" onClick={runPreview} disabled={submitting}>analyze</button>
              <button className="filter-pill" onClick={submit} disabled={submitting}>
                {submitting ? "saving…" : "save drop"}
              </button>
              {submitMsg && (
                <span className={`inbox-msg ${submitMsg.type}`}>{submitMsg.text}</span>
              )}
            </div>

            {previewData && (
              <div className="inbox-preview-card">
                <div className="inbox-preview-row">
                  <span className="lbl">tickers</span>
                  <span>{previewData.detected_tickers?.length ? previewData.detected_tickers.join(", ") : "—"}</span>
                </div>
                <div className="inbox-preview-row">
                  <span className="lbl">tags</span>
                  <span>{previewData.suggested_tags?.join(", ") || "—"}</span>
                </div>
                <div className="inbox-preview-row">
                  <span className="lbl">routes to</span>
                  <span>{previewData.suggested_agents?.join(", ") || "—"}</span>
                </div>
                <div className="inbox-preview-row">
                  <span className="lbl">author known?</span>
                  <span>{previewData.suggested_author_id || "new"}</span>
                </div>
              </div>
            )}
          </div>

          {/* Right: metadata */}
          <div className="inbox-col">
            <label className="inbox-label">Author / source</label>
            <input
              className="inbox-input"
              placeholder="@capo, BWatch chat, self, etc."
              list="known-authors"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
            />
            <datalist id="known-authors">
              {authors.map(a => (
                <option key={a.author_id} value={a.display_name}>{a.channel}</option>
              ))}
            </datalist>

            <label className="inbox-label">Channel / group</label>
            <input
              className="inbox-input"
              placeholder='e.g. "BWatch chat", "self", "TradingView public"'
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            />

            <label className="inbox-label">Channel type</label>
            <div className="filter-pill-row">
              {CHANNEL_TYPES.map(t => (
                <button key={t} className={`filter-pill ${channelType === t ? "on" : ""}`}
                        onClick={() => setChannelType(t)}>{t}</button>
              ))}
            </div>

            <label className="inbox-label">Ticker</label>
            <input
              className="inbox-input"
              placeholder='auto-detected from blurb · override here'
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
            />

            <label className="inbox-label">Side</label>
            <div className="filter-pill-row">
              {SIDES.map(s => (
                <button key={s} className={`filter-pill ${side === s ? "on" : ""}`}
                        onClick={() => setSide(s)}>{s}</button>
              ))}
            </div>

            <label className="inbox-label">Conviction · {conviction}/5</label>
            <input
              type="range" min="1" max="5" step="1"
              value={conviction}
              onChange={(e) => setConviction(e.target.value)}
              className="inbox-range"
            />

            <label className="inbox-label">Timeframe</label>
            <div className="filter-pill-row">
              {TIMEFRAMES.map(t => (
                <button key={t} className={`filter-pill ${timeframe === t ? "on" : ""}`}
                        onClick={() => setTimeframe(t)}>{t}</button>
              ))}
            </div>

            <label className="inbox-label">One-line note (optional)</label>
            <input
              className="inbox-input"
              placeholder="e.g. wedge break, retest of POC, etc."
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />

            {authors.length > 0 && (
              <div className="inbox-known-authors">
                <div className="inbox-label">Known sources</div>
                <div className="filter-pill-row">
                  {authors.slice(0, 8).map(a => (
                    <button key={a.author_id} className="filter-pill"
                            title={`${a.channel || "—"} · ${a.submission_count} drops`}
                            onClick={() => pickAuthor(a)}>
                      {a.display_name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* History */}
      <section className="block">
        <header className="block-head">
          <div className="block-title">
            <span className="block-num mono">I2</span>
            <span>Recent drops</span>
            <span className="block-sub">last 20 · text + chart submissions</span>
          </div>
          <div className="block-actions">
            <button className="filter-pill" onClick={refreshHistory}>refresh</button>
          </div>
        </header>
        {history.length === 0 ? (
          <div className="inbox-empty">No drops yet. Add one above.</div>
        ) : (
          <table className="inbox-history">
            <thead>
              <tr>
                <th>when</th>
                <th>type</th>
                <th>ticker · side</th>
                <th>author</th>
                <th>tags</th>
                <th>vision</th>
              </tr>
            </thead>
            <tbody>
              {history.map(h => {
                const meta = h.user_metadata?.resolved || {};
                const tagsObj = h.tags || {};
                const tags = Array.isArray(tagsObj.tags) ? tagsObj.tags : [];
                const pending = !!tagsObj.pending_vision;
                return (
                  <tr key={h.document_id}>
                    <td className="mono dim">{(h.ingested_at || "").slice(0, 19).replace("T", " ")}</td>
                    <td>
                      {h.content_type === "manual_chart" ? "chart" : "note"}
                      {Array.isArray(h.attachment_paths) && h.attachment_paths.length > 1 ? (
                        <span className="dim mono"> ·{h.attachment_paths.length}</span>
                      ) : null}
                    </td>
                    <td>
                      <strong>{meta.ticker || "—"}</strong>
                      {meta.side ? <span className="dim mono"> · {meta.side}</span> : null}
                    </td>
                    <td>{h.author_id?.replace(":", " · ") || "—"}</td>
                    <td className="mono dim">{tags.join(", ")}</td>
                    <td>{pending ? <span className="badge-pending">pending</span> : <span className="dim">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
