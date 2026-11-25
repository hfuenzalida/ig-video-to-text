import { useCallback, useEffect, useState, type FormEvent } from "react";
import type {
  ExtractedFacts,
  HealthInfo,
  LibraryDetail,
  LibraryListItem,
  TranscriptionResult,
  TranscriptWithExtraction,
} from "./types";

const API = "/api";

function downloadBlob(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [lang, setLang] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TranscriptionResult | null>(null);
  const [extraction, setExtraction] = useState<ExtractedFacts | null>(null);
  const [extractLoading, setExtractLoading] = useState(false);
  const [ocrInterval, setOcrInterval] = useState("");
  const [saveToLibrary, setSaveToLibrary] = useState(false);
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [libraryList, setLibraryList] = useState<LibraryListItem[]>([]);
  const [librarySearch, setLibrarySearch] = useState("");
  const [libraryHits, setLibraryHits] = useState<LibraryListItem[] | null>(null);
  const [libraryDetail, setLibraryDetail] = useState<LibraryDetail | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [importUrl, setImportUrl] = useState("");

  useEffect(() => {
    void fetch(`${API}/health`)
      .then((r) => r.json())
      .then((j: HealthInfo) => setHealth(j))
      .catch(() => setHealth(null));
  }, []);

  const refreshLibrary = useCallback(async () => {
    try {
      const res = await fetch(`${API}/library?limit=80`);
      if (!res.ok) return;
      const data: LibraryListItem[] = await res.json();
      setLibraryList(data);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void refreshLibrary();
  }, [refreshLibrary]);

  useEffect(() => {
    const q = librarySearch.trim();
    if (!q) {
      setLibraryHits(null);
      return;
    }
    const t = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await fetch(
            `${API}/library/search?q=${encodeURIComponent(q)}&limit=40`
          );
          if (!res.ok) return;
          const data: LibraryListItem[] = await res.json();
          setLibraryHits(data);
        } catch {
          setLibraryHits([]);
        }
      })();
    }, 320);
    return () => window.clearTimeout(t);
  }, [librarySearch]);

  const onSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (!file) {
        setError("Choose a video file first.");
        return;
      }
      setError(null);
      setLoading(true);
      setResult(null);
      setExtraction(null);
      const fd = new FormData();
      fd.append("file", file);
      const params = new URLSearchParams();
      if (lang.trim()) params.set("language", lang.trim());
      const ocrN = Number(ocrInterval);
      if (
        ocrInterval.trim() !== "" &&
        !Number.isNaN(ocrN) &&
        ocrN > 0
      ) {
        params.set("ocr_interval", String(ocrN));
      }
      if (saveToLibrary) params.set("save_library", "true");
      const qs = params.toString() ? `?${params}` : "";
      try {
        const res = await fetch(`${API}/transcribe${qs}`, {
          method: "POST",
          body: fd,
        });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || res.statusText);
        }
        const data: TranscriptionResult = await res.json();
        setResult(data);
        if (saveToLibrary) void refreshLibrary();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [file, lang, ocrInterval, saveToLibrary, refreshLibrary]
  );

  const onSubmitUrl = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const u = importUrl.trim();
      if (!u) {
        setError("Paste an Instagram reel/post URL.");
        return;
      }
      setError(null);
      setLoading(true);
      setResult(null);
      setExtraction(null);
      const params = new URLSearchParams();
      if (lang.trim()) params.set("language", lang.trim());
      const ocrN = Number(ocrInterval);
      if (
        ocrInterval.trim() !== "" &&
        !Number.isNaN(ocrN) &&
        ocrN > 0
      ) {
        params.set("ocr_interval", String(ocrN));
      }
      if (saveToLibrary) params.set("save_library", "true");
      const qs = params.toString() ? `?${params}` : "";
      try {
        const res = await fetch(`${API}/transcribe/url${qs}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: u }),
        });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || res.statusText);
        }
        const data: TranscriptionResult = await res.json();
        setResult(data);
        if (saveToLibrary) void refreshLibrary();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [
      importUrl,
      lang,
      ocrInterval,
      saveToLibrary,
      refreshLibrary,
    ]
  );

  const onSaveLibrary = useCallback(async () => {
    if (!result) return;
    setLibraryBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API}/library`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcription: result,
          extraction: extraction ?? undefined,
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      await refreshLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLibraryBusy(false);
    }
  }, [result, extraction, refreshLibrary]);

  const onDeleteLibrary = useCallback(
    async (videoId: string) => {
      if (!window.confirm("Remove this item from the library?")) return;
      try {
        const res = await fetch(`${API}/library/${videoId}`, {
          method: "DELETE",
        });
        if (!res.ok) return;
        if (libraryDetail?.video_id === videoId) setLibraryDetail(null);
        await refreshLibrary();
        setLibraryHits((h) => (h ? h.filter((x) => x.video_id !== videoId) : h));
      } catch {
        /* ignore */
      }
    },
    [refreshLibrary, libraryDetail?.video_id]
  );

  const onOpenLibraryItem = useCallback(async (videoId: string) => {
    try {
      const res = await fetch(`${API}/library/${videoId}`);
      if (!res.ok) return;
      const row = await res.json();
      const detail: LibraryDetail = {
        video_id: row.video_id,
        original_filename: row.original_filename,
        text: row.text,
        segments: row.segments,
        language: row.language,
        duration: row.duration,
        screen_text: row.screen_text,
        created_at: row.created_at,
        extraction: row.extraction,
      };
      setLibraryDetail(detail);
    } catch {
      /* ignore */
    }
  }, []);

  const onExtract = useCallback(async () => {
    if (!result) return;
    const spoken = result.text.trim();
    const screen = (result.screen_text?.lines_deduped ?? []).join("\n").trim();
    const combined = [
      spoken,
      screen ? `--- On-screen ---\n${screen}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
    if (!combined) {
      setError(
        "Nothing to extract — no speech and no on-screen text. Run OCR or use a video with audio."
      );
      return;
    }
    setError(null);
    setExtractLoading(true);
    try {
      const res = await fetch(`${API}/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: combined,
          language: result.language ?? undefined,
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data: ExtractedFacts = await res.json();
      setExtraction(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExtractLoading(false);
    }
  }, [result]);

  const onExportJson = useCallback(() => {
    if (!result) return;
    const payload: TranscriptWithExtraction = extraction
      ? { ...result, extraction }
      : { ...result };
    downloadBlob(
      `transcript-${result.video_id}.json`,
      JSON.stringify(payload, null, 2),
      "application/json"
    );
  }, [result, extraction]);

  const onExportTxt = useCallback(() => {
    if (!result) return;
    const lines: string[] = [
      `File: ${result.original_filename}`,
      `Language: ${result.language ?? "—"}`,
      `Duration: ${result.duration != null ? `${result.duration.toFixed(1)}s` : "—"}`,
      "",
      "— Full text —",
      result.text,
      "",
      "— With timestamps —",
    ];
    for (const s of result.segments) {
      lines.push(
        `[${s.start.toFixed(1)}s – ${s.end.toFixed(1)}s] ${s.text}`
      );
    }
    const screenLines = result.screen_text?.lines_deduped ?? [];
    if (screenLines.length > 0) {
      lines.push(
        "",
        "— On-screen (OCR, deduped) —",
        ...screenLines.map((l) => `• ${l}`),
        ""
      );
    }
    if (extraction) {
      lines.push("", "— Extracted —", "");
      if (extraction.summary) lines.push(extraction.summary, "");
      if (extraction.topics.length)
        lines.push("Topics:", ...extraction.topics.map((t) => `• ${t}`), "");
      if (extraction.entities.length)
        lines.push("Entities:", ...extraction.entities.map((t) => `• ${t}`), "");
      if (extraction.sentiment) lines.push(`Sentiment: ${extraction.sentiment}`, "");
      if (extraction.calls_to_action.length)
        lines.push(
          "Calls to action:",
          ...extraction.calls_to_action.map((t) => `• ${t}`),
          ""
        );
      if (extraction.handles.length)
        lines.push("Handles:", ...extraction.handles.map((h) => `@${h}`), "");
      if (extraction.urls.length)
        lines.push("URLs:", ...extraction.urls.map((u) => u), "");
      lines.push(`(method: ${extraction.method})`);
    }
    downloadBlob(`transcript-${result.video_id}.txt`, lines.join("\n"), "text/plain");
  }, [result, extraction]);

  return (
    <div className="app">
      <header className="header">
        <h1>Video to text</h1>
        <p className="sub">
          Whisper transcribes speech; optional OCR (Tesseract); optional Phase 5 URL
          import via yt-dlp (off by default on the server).
        </p>
      </header>

      <form className="card" onSubmit={onSubmitUrl}>
        <h2 className="card-title">Import from URL (Phase 5)</h2>
        <p className="sub url-hint">
          Allowed hosts:{" "}
          <code>{health?.url_import_hosts ?? "instagram.com (default)"}</code>
          . Requires <code>IG_VTT_URL_IMPORT=1</code> and <code>yt-dlp</code>. Instagram
          often needs browser cookies — see README. Respect platform terms.
        </p>
        <label className="field">
          <span>Instagram / Reels URL (https)</span>
          <input
            type="url"
            value={importUrl}
            onChange={(e) => setImportUrl(e.target.value)}
            placeholder="https://www.instagram.com/reel/…"
            autoComplete="off"
            disabled={health?.url_import_enabled === false}
          />
        </label>
        <button
          type="submit"
          disabled={
            loading ||
            (health != null && !health.url_import_enabled) ||
            (health != null && !health.yt_dlp)
          }
          className="primary"
        >
          {loading ? "Working…" : "Transcribe from URL"}
        </button>
        {health && !health.url_import_enabled && (
          <p className="err soft">
            URL import is disabled on this server (set <code>IG_VTT_URL_IMPORT=1</code>).
          </p>
        )}
        {health?.url_import_enabled && !health.yt_dlp && (
          <p className="err soft">
            yt-dlp not available — run <code>pip install yt-dlp</code> in the backend venv.
          </p>
        )}
      </form>

      <form className="card" onSubmit={onSubmit}>
        <h2 className="card-title">Upload file</h2>
        <label className="field">
          <span>Video</span>
          <input
            type="file"
            accept="video/*,.mp4,.webm,.mov,.m4v,.mkv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
            }}
          />
        </label>
        <label className="field">
          <span>Language (optional, e.g. en)</span>
          <input
            type="text"
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            placeholder="auto"
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>OCR interval (optional, seconds between frames; needs Tesseract)</span>
          <input
            type="text"
            inputMode="decimal"
            value={ocrInterval}
            onChange={(e) => setOcrInterval(e.target.value)}
            placeholder="off — e.g. 2"
            autoComplete="off"
          />
        </label>
        <label className="field check">
          <input
            type="checkbox"
            checked={saveToLibrary}
            onChange={(e) => setSaveToLibrary(e.target.checked)}
          />
          <span>Save to library after transcribe (SQLite + full-text index)</span>
        </label>
        <button type="submit" disabled={loading} className="primary">
          {loading ? "Transcribing…" : "Transcribe"}
        </button>
        {error && <p className="err">{error}</p>}
      </form>

      {result && (
        <section className="card out">
          <div className="row">
            <h2>Transcript</h2>
            <div className="btns">
              <button
                type="button"
                onClick={onExtract}
                disabled={
                  extractLoading ||
                  (!result.text?.trim() &&
                    !(result.screen_text?.lines_deduped?.length ?? 0))
                }
                className="secondary"
              >
                {extractLoading ? "Extracting…" : "Extract information"}
              </button>
              <button type="button" onClick={onExportJson} className="secondary">
                Download JSON
              </button>
              <button type="button" onClick={onExportTxt} className="secondary">
                Download .txt
              </button>
              <button
                type="button"
                onClick={onSaveLibrary}
                disabled={libraryBusy}
                className="secondary"
              >
                {libraryBusy ? "Saving…" : "Save / update library"}
              </button>
            </div>
          </div>
          <p className="meta">
            {result.original_filename} · {result.language ?? "language ?"} ·{" "}
            {result.duration != null
              ? `${result.duration.toFixed(1)}s`
              : "duration ?"}
          </p>
          <p className="body">{result.text || "(no speech detected)"}</p>
          {result.segments.length > 0 && (
            <ol className="segs">
              {result.segments.map((s, i) => (
                <li key={i}>
                  <span className="ts">
                    {s.start.toFixed(1)}s – {s.end.toFixed(1)}s
                  </span>{" "}
                  {s.text}
                </li>
              ))}
            </ol>
          )}
          {result.screen_text &&
            (result.screen_text.lines_deduped.length > 0 ||
              result.screen_text.frames.length > 0) && (
            <div className="extract screen-ocr">
              <h3 className="extract-title">On-screen text (OCR)</h3>
              <p className="extract-meta">
                Every {result.screen_text.interval_sec}s · {result.screen_text.method}
                {" · "}
                {result.screen_text.frames.length} frame(s) with text
              </p>
              {result.screen_text.lines_deduped.length > 0 ? (
                <ul className="extract-list deduped">
                  {result.screen_text.lines_deduped.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              ) : (
                <p className="extract-hint">No text detected in sampled frames.</p>
              )}
              {result.screen_text.frames.length > 0 && (
                <details className="ocr-frames">
                  <summary>Per-frame raw OCR</summary>
                  <ol className="segs">
                    {result.screen_text.frames.map((f, i) => (
                      <li key={i}>
                        <span className="ts">{f.t.toFixed(1)}s</span>{" "}
                        <span className="ocr-raw">{f.text || "—"}</span>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          )}
          {extraction && (
            <div className="extract">
              <h3 className="extract-title">Extracted</h3>
              <p className="extract-meta">
                Method: {extraction.method}
                {extraction.sentiment && ` · Sentiment: ${extraction.sentiment}`}
              </p>
              {extraction.summary ? (
                <p className="extract-summary">{extraction.summary}</p>
              ) : (
                <p className="extract-hint">
                  No AI summary (set <code>IG_VTT_LLM_BASE_URL</code> for full Phase 2).
                  Heuristic fields still list links and handles below.
                </p>
              )}
              {extraction.topics.length > 0 && (
                <div className="extract-block">
                  <span className="extract-label">Topics</span>
                  <ul className="extract-list">
                    {extraction.topics.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
              {extraction.entities.length > 0 && (
                <div className="extract-block">
                  <span className="extract-label">Entities</span>
                  <ul className="extract-list">
                    {extraction.entities.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
              {extraction.calls_to_action.length > 0 && (
                <div className="extract-block">
                  <span className="extract-label">Calls to action</span>
                  <ul className="extract-list">
                    {extraction.calls_to_action.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
              {(extraction.handles.length > 0 || extraction.urls.length > 0) && (
                <div className="extract-block">
                  <span className="extract-label">Links &amp; handles</span>
                  <ul className="extract-list">
                    {extraction.handles.map((h, i) => (
                      <li key={`h-${i}`}>@{h}</li>
                    ))}
                    {extraction.urls.map((u, i) => (
                      <li key={`u-${i}`}>
                        <a href={u} target="_blank" rel="noreferrer">
                          {u}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <section className="card lib">
        <h2 className="lib-title">Library</h2>
        <p className="sub lib-desc">
          Keyword search over saved transcripts, OCR lines, and extraction text (FTS5).
        </p>
        <label className="field">
          <span>Search library</span>
          <input
            type="search"
            value={librarySearch}
            onChange={(e) => setLibrarySearch(e.target.value)}
            placeholder="Type to search…"
            autoComplete="off"
          />
        </label>
        <ul className="lib-list">
          {(libraryHits ?? libraryList).length === 0 && (
            <li className="lib-empty">
              {librarySearch.trim()
                ? "No matches."
                : "No saved items yet — transcribe with “Save to library” or use Save / update library."}
            </li>
          )}
          {(libraryHits ?? libraryList).map((item) => (
            <li key={item.video_id} className="lib-row">
              <button
                type="button"
                className="lib-open"
                onClick={() => void onOpenLibraryItem(item.video_id)}
              >
                {item.original_filename}
              </button>
              <span className="lib-meta">
                {item.created_at}
                {item.has_extraction ? " · extraction" : ""}
                {item.preview ? (
                  <span className="lib-snippet"> — {item.preview}</span>
                ) : null}
              </span>
              <button
                type="button"
                className="lib-del"
                onClick={() => void onDeleteLibrary(item.video_id)}
                aria-label="Delete"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        {libraryDetail && (
          <div className="lib-detail">
            <div className="row">
              <h3>{libraryDetail.original_filename}</h3>
              <button
                type="button"
                className="secondary"
                onClick={() => setLibraryDetail(null)}
              >
                Close
              </button>
            </div>
            <p className="meta">
              {libraryDetail.created_at} · {libraryDetail.language ?? "—"} ·{" "}
              {libraryDetail.duration != null
                ? `${libraryDetail.duration.toFixed(1)}s`
                : "—"}
            </p>
            <p className="body">{libraryDetail.text || "(no speech)"}</p>
            {libraryDetail.extraction?.summary ? (
              <p className="extract-summary">{libraryDetail.extraction.summary}</p>
            ) : null}
          </div>
        )}
      </section>

      <footer className="foot">
        Backend: <code>ffmpeg</code>, <code>faster-whisper</code>; optional{" "}
        <code>tesseract</code>, <code>yt-dlp</code> + env for URL import;{" "}
        <code>library.db</code> for search.
      </footer>
    </div>
  );
}
