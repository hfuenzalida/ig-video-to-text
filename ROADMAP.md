# Instagram Video to Text — Roadmap & session notes

This file captures the plan and working notes from the sessions that set up the **IG Video to Text** project. The canonical project folder is:

**`C:\Users\horat\Downloads\IG Video to Text`**

(Previously the same app lived under the `Algoritmic Trader` workspace; it was relocated here on purpose.)

---

## Product goal

Build an app that turns **Instagram-style videos (Reels, etc.)** into **usable text** so you can **extract information** (topics, quotes, on-screen text, later: entities and summaries) using **free-tier or local AI** where possible.

**Recommended MVP focus:** start with **upload a video file** (export from device or screen recording), not scraping Instagram URLs, because the official API is limited and scraping can break or conflict with terms of service.

---

## Recommended stack (free / local)

| Layer | Suggestion |
|--------|------------|
| **Frontend** | Vite + React (or Next.js) |
| **Backend** | Python + FastAPI |
| **Video / audio** | `ffmpeg` on PATH |
| **Speech-to-text** | `faster-whisper` (Whisper, local, no paid API) |
| **On-screen text (later)** | Tesseract or PaddleOCR on sampled frames |
| **Summarization / extraction (later)** | Ollama, Gemini free tier, Groq free tier, or Hugging Face — pick one and standardize on JSON output |
| **Storage (later)** | SQLite (local) or Supabase free tier |

---

## Architecture (target pipeline)

```text
User provides video (upload)
        ↓
Store / stream file
        ↓
ffmpeg → extract audio
        ↓
Whisper → transcript + timestamps
        ↓
(Phase 2+) LLM → summary, topics, entities
        ↓
(Phase 3+) Frame sampling + OCR → captions, charts, on-screen text
        ↓
(Phase 4+) Searchable store (optional vectors)
```

---

## Phased roadmap

### Phase 1 — MVP: video → transcript (done in repo)

**Goal:** Upload a local video, get clean text and timed segments, export **JSON** and **.txt**.

**Implemented:**

- **Backend** (`backend/`): FastAPI, `POST /api/transcribe`, `GET /api/health`, `ffmpeg` → 16 kHz mono WAV, **faster-whisper** transcription, temp uploads under configurable dir then deleted.
- **Frontend** (`frontend/`): Vite + React UI: file picker, optional language code, display full text + segments, download JSON and plain text.
- **Docs:** `README.md` in this folder (run instructions, env vars).

**Prerequisites:** Python 3.11+, Node 18+, **ffmpeg** on PATH. First run downloads a Whisper model.

**Environment (optional):** `WHISPER_MODEL` (default `base`), `WHISPER_DEVICE` (`cpu` / `cuda`), `CORS_ORIGINS`, `IG_VTT_MAX_UPLOAD_MB`, `IG_VTT_UPLOAD_DIR`.

**Supported extensions:** `.mp4`, `.webm`, `.mov`, `.mkv`, `.m4v`, `.avi`.

### Phase 2 — Information extraction

- Summaries, main topics, entities, sentiment, calls to action, mentioned handles/URLs.  
- Standardize a **JSON schema** for “extracted facts” and keep the raw transcript.

### Phase 3 — OCR on video frames

- Sample frames every N seconds; run OCR; deduplicate; merge with spoken transcript.

### Phase 4 — Searchable knowledge base

- DB rows per video, transcript, entities, tags; keyword search; optional `pgvector` / local Chroma.

### Phase 5 — Instagram import (optional)

- Safest: user downloads the file and uploads.  
- Public URL + `yt-dlp`: fragile and policy-sensitive.  
- Official Graph API: mainly for **your own** business/creator content.

---

## JSON shapes (reference)

**Transcription (Phase 1 API response — simplified):**

```json
{
  "video_id": "…",
  "original_filename": "reel.mp4",
  "text": "…",
  "segments": [
    { "start": 0.0, "end": 4.2, "text": "…" }
  ],
  "language": "en",
  "duration": 123.4
}
```

**Future extraction (example):**

```json
{
  "summary": "…",
  "topics": ["…"],
  "entities": ["…"],
  "sentiment": "…"
}
```

---

## How to run (Phase 1)

From **`C:\Users\horat\Downloads\IG Video to Text`**, see **`README.md`** for full steps. In short:

1. **Backend:** create venv in `backend`, `pip install -r requirements.txt`, run `uvicorn main:app` from `backend`.
2. **Frontend (dev):** in `frontend`, `npm install`, `npm run dev`, open the printed localhost URL (proxy to API).
3. **Optional:** `npm run build` in `frontend`, then serve only the API; open the API root to use the built UI.

---

## Project layout (this folder)

```text
IG Video to Text/
  ROADMAP.md          ← this file
  README.md
  .gitignore
  backend/
    main.py
    transcribe.py
    requirements.txt
  frontend/
    (Vite + React app — see package.json)
```

`node_modules` and `backend/.venv` are not copied by design; recreate with `npm install` and `python -m venv` + `pip install -r requirements.txt`.

---

## Session correction (folder move)

The implementation was first created under **`Algoritmic Trader\ig_video_transcript`**. The project was **copied** to **`C:\Users\horat\Downloads\IG Video to Text`** (source only; heavy `venv` / `node_modules` excluded). The **`ROADMAP.md`** you asked for is this file, placed in the same destination folder.

If a duplicate still exists in the old repo, you can delete **`ig_video_transcript`** there to avoid confusion; this folder is the intended home for the app.

---

## Build order (reminder)

1. Upload + transcription.  
2. Transcript timestamps (included in Phase 1).  
3. LLM summary / extraction.  
4. OCR for on-screen text.  
5. Searchable database.  
6. Exports and optional Instagram URL import.

End of ROADMAP.
