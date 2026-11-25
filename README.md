# Instagram / video → text

Upload a local video file, extract audio with **ffmpeg**, transcribe with **faster-whisper** (Whisper, local, no paid API), optionally sample frames for **on-screen OCR** (Tesseract), optionally run **Phase 2 extraction** (summary, topics, entities, links), and download **JSON** or **.txt**.

Clone this repository as your project root. See **ROADMAP.md** for the full product plan and phases.

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for the web UI in development)
- **ffmpeg** on your `PATH` ([download](https://ffmpeg.org/download.html)) — on Windows, install and add `bin` to PATH, then open a new terminal.
- **Tesseract OCR** on your `PATH` if you use on-screen text ([install](https://github.com/tesseract-ocr/tesseract)) — optional; Windows installers often need `IG_VTT_TESSERACT_CMD` pointing at `tesseract.exe`.

## Backend

```text
cd .\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Optional environment:

| Variable | Default | Meaning |
|----------|---------|---------|
| `WHISPER_MODEL` | `base` | Whisper model: `tiny`, `base`, `small`, … |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` (if you have a GPU) |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `IG_VTT_MAX_UPLOAD_MB` | `500` | Max upload size |
| `IG_VTT_UPLOAD_DIR` | `backend/data/uploads` | Temp uploads (deleted after each job) |
| `IG_VTT_LLM_BASE_URL` | _(empty)_ | OpenAI-compatible API base (e.g. Ollama `http://127.0.0.1:11434/v1`) for Phase 2 |
| `IG_VTT_LLM_MODEL` | `llama3.2` | Model name for `/v1/chat/completions` |
| `IG_VTT_LLM_API_KEY` | _(empty)_ | Bearer token if required (Groq, OpenAI, etc.) |
| `IG_VTT_LLM_JSON_MODE` | _(off)_ | Set `1` to send `response_format: json_object` when the server supports it |
| `IG_VTT_OCR_LANG` | `eng` | Tesseract language(s), e.g. `eng+spa` |
| `IG_VTT_OCR_MAX_FRAMES` | `60` | Cap sampled frames per video (cost / time) |
| `IG_VTT_TESSERACT_CMD` | _(empty)_ | Full path to `tesseract` if not on PATH (common on Windows) |
| `IG_VTT_DB_PATH` | `backend/data/library.db` | SQLite database for the Phase 4 library + FTS index |

Start API:

```text
cd .\backend
.venv\Scripts\activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Check: `http://127.0.0.1:8000/api/health` should show `ffmpeg: true` after ffmpeg is installed, and `tesseract: true` when Tesseract is available for Phase 3 OCR.

Transcribe with OCR (e.g. every 2 seconds): add query `ocr_interval=2` to `POST /api/transcribe` (see UI field **OCR interval**).

**Phase 4 — library:** `GET /api/library`, `GET /api/library/search?q=…`, `GET /api/library/{video_id}`, `POST /api/library` (body: `{ "transcription": {…}, "extraction": optional }`), `DELETE /api/library/{video_id}`, `PATCH /api/library/{video_id}/extraction`. Transcribe with `save_library=true` to persist in one step.

**Phase 5 — URL import (optional):** `POST /api/transcribe/url` with JSON `{ "url": "https://…" }` and the same query params as file transcribe (`language`, `ocr_interval`, `save_library`). **Disabled by default** — set `IG_VTT_URL_IMPORT=1`. Uses **yt-dlp** (`pip install yt-dlp`); Instagram frequently requires auth — use `yt-dlp`’s cookie options (e.g. `--cookies-from-browser` in `IG_VTT_YTDLP_ARGS`) or export cookies per [yt-dlp docs](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp). This can break when sites change; you are responsible for complying with **Instagram’s terms** and applicable law. Prefer downloading in the app and using **Upload file** when possible.

| Variable | Default | Meaning |
|----------|---------|---------|
| `IG_VTT_URL_IMPORT` | _(off)_ | Set `1` or `true` to allow `POST /api/transcribe/url` |
| `IG_VTT_URL_IMPORT_HOSTS` | `instagram.com` | Comma-separated host suffixes (subdomains allowed) |
| `IG_VTT_URL_IMPORT_TIMEOUT_SEC` | `600` | Max seconds for yt-dlp download |
| `IG_VTT_YTDLP_ARGS` | _(empty)_ | Extra args for yt-dlp (quoted), e.g. `--cookies-from-browser chrome` |

## Frontend (dev)

In a second terminal:

```text
cd .\frontend
npm install
npm run dev
```

Open `http://localhost:5173`, pick a short `.mp4` / `.webm` / `.mov`, click **Transcribe**.

## Single command line (no UI)

```text
cd .\backend
.venv\Scripts\activate
curl -X POST "http://127.0.0.1:8000/api/transcribe" -F "file=@C:\path\to\video.mp4"
```

## Production-style (API serves built UI)

```text
cd .\frontend
npm run build
cd ..\backend
.venv\Scripts\activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open `http://127.0.0.1:8000/`.

## Supported formats

Server accepts: `.mp4`, `.webm`, `.mov`, `.mkv`, `.m4v`, `.avi` (any Instagram-exported or screen recording should work if ffmpeg can decode it).

## Next phases (not implemented here)

- LLM-based summarization and entity extraction
- OCR for on-screen text
- Optional Instagram URL import (terms and breakage apply)
