"""IG Video to Text: transcript, OCR, extraction, library, optional URL import (Phase 5)."""

from __future__ import annotations

import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

from extract import build_extracted_facts
import library_db
from ocr_frames import process_video_screen_ocr
from transcribe import process_video_to_transcript
import url_import

# Upload directory (ephemeral; cleaned per request after processing)
UPLOAD_DIR = Path(os.environ.get("IG_VTT_UPLOAD_DIR", Path(__file__).resolve().parent / "data" / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Max upload size in bytes (default 500 MB)
MAX_BYTES = int(os.environ.get("IG_VTT_MAX_UPLOAD_MB", "500")) * 1024 * 1024

ALLOWED_EXT = {".mp4", ".webm", ".mov", ".mkv", ".m4v", ".avi"}


class Segment(BaseModel):
    start: float
    end: float
    text: str


class OcrFrame(BaseModel):
    t: float = Field(..., description="Timestamp (seconds) of sampled frame")
    text: str


class ScreenTextResult(BaseModel):
    """On-screen text from Phase 3 (Tesseract on sampled frames)."""

    interval_sec: float
    frames: list[OcrFrame] = []
    lines_deduped: list[str] = []
    method: str = "tesseract"


class TranscriptionResult(BaseModel):
    video_id: str = Field(..., description="Server-generated id for this run")
    original_filename: str
    text: str
    segments: list[Segment] = []
    language: str | None = None
    duration: float | None = None
    screen_text: ScreenTextResult | None = None


class ExtractedFacts(BaseModel):
    """Structured facts derived from transcript (Phase 2)."""

    summary: str = ""
    topics: list[str] = []
    entities: list[str] = []
    sentiment: str | None = None
    calls_to_action: list[str] = []
    handles: list[str] = []
    urls: list[str] = []
    method: str = Field(
        default="heuristic",
        description="heuristic | llm+heuristic",
    )


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Full transcript text")
    language: str | None = Field(
        default=None,
        description="Optional ISO language hint for the LLM",
    )


class UrlImportRequest(BaseModel):
    """Public Instagram/Reels URL (https). Phase 5 — requires env + yt-dlp."""

    url: str = Field(..., min_length=12, max_length=2048)

    @field_validator("url")
    @classmethod
    def _trim_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class LibrarySaveRequest(BaseModel):
    """Snapshot to store (same shape as export JSON)."""

    transcription: TranscriptionResult
    extraction: ExtractedFacts | None = None


class LibraryListItem(BaseModel):
    video_id: str
    original_filename: str
    created_at: str
    language: str | None = None
    duration: float | None = None
    has_extraction: bool = False


class LibrarySearchHit(LibraryListItem):
    preview: str | None = None


class LibraryGetResponse(BaseModel):
    video_id: str
    original_filename: str
    created_at: str
    language: str | None = None
    duration: float | None = None
    text: str
    segments: list[Segment] = []
    screen_text: ScreenTextResult | None = None
    extraction: ExtractedFacts | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    library_db.init_db()
    yield


app = FastAPI(
    title="IG Video to Text",
    version="0.5.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    ff = shutil.which("ffmpeg")
    llm = bool(os.environ.get("IG_VTT_LLM_BASE_URL", "").strip())
    tess_env = os.environ.get("IG_VTT_TESSERACT_CMD", "").strip()
    tess = bool(
        (tess_env and Path(tess_env).is_file()) or shutil.which("tesseract")
    )
    return {
        "status": "ok",
        "ffmpeg": bool(ff),
        "whisper_model": os.environ.get("WHISPER_MODEL", "base"),
        "llm_configured": llm,
        "tesseract": tess,
        "library_db": str(library_db.db_path()),
        "url_import_enabled": url_import.url_import_enabled(),
        "yt_dlp": url_import.yt_dlp_available(),
        "url_import_hosts": url_import.allowed_hosts_label(),
    }


def _read_upload_chunked(
    dest: Path, upload: UploadFile, max_bytes: int
) -> int:
    n = 0
    with dest.open("wb") as f:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            n += len(chunk)
            if n > max_bytes:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File larger than {max_bytes // (1024 * 1024)} MB")
            f.write(chunk)
    return n


def _parse_ocr_interval(ocr_interval: float | None) -> float | None:
    if ocr_interval is None:
        return None
    if ocr_interval <= 0:
        return None
    if ocr_interval < 0.25 or ocr_interval > 120:
        raise HTTPException(
            400,
            "ocr_interval must be 0.25–120 seconds, 0, or omitted",
        )
    return ocr_interval


def _compute_transcription(
    video_path: Path,
    language: str | None,
    ocr_sec: float | None,
) -> tuple[dict, ScreenTextResult | None]:
    raw = process_video_to_transcript(video_path, language=language)
    screen: ScreenTextResult | None = None
    if ocr_sec is not None:
        try:
            ocr_raw = process_video_screen_ocr(
                video_path,
                interval_sec=ocr_sec,
                duration_hint=raw.get("duration"),
            )
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        screen = ScreenTextResult(
            interval_sec=ocr_raw["interval_sec"],
            frames=[OcrFrame(**f) for f in ocr_raw["frames"]],
            lines_deduped=ocr_raw["lines_deduped"],
            method=ocr_raw.get("method", "tesseract"),
        )
    return raw, screen


def _result_from_raw(
    job_id: str,
    original_filename: str,
    raw: dict,
    screen: ScreenTextResult | None,
) -> TranscriptionResult:
    segs = [
        Segment(start=s["start"], end=s["end"], text=s["text"])
        for s in raw.get("segments", [])
    ]
    return TranscriptionResult(
        video_id=job_id,
        original_filename=original_filename,
        text=raw.get("text", ""),
        segments=segs,
        language=raw.get("language"),
        duration=raw.get("duration"),
        screen_text=screen,
    )


@app.post("/api/transcribe", response_model=TranscriptionResult)
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Query(
        default=None,
        description="Optional ISO language code, e.g. en",
    ),
    ocr_interval: float | None = Query(
        default=None,
        description="Sample every N seconds for on-screen OCR (Tesseract); omit or 0 to skip",
    ),
    save_library: bool = Query(
        default=False,
        description="If true, persist this result to the local SQLite library (Phase 4)",
    ),
) -> TranscriptionResult:
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(
            400,
            f"Unsupported type {suffix!r}. Allowed: {', '.join(sorted(ALLOWED_EXT))}",
        )
    ocr_sec = _parse_ocr_interval(ocr_interval)
    job_id = uuid.uuid4().hex
    out_dir = UPLOAD_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"video{suffix}"
    try:
        _read_upload_chunked(video_path, file, MAX_BYTES)
        raw, screen = _compute_transcription(video_path, language, ocr_sec)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    finally:
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
        except OSError:
            pass

    result = _result_from_raw(job_id, file.filename, raw, screen)
    if save_library:
        try:
            library_db.upsert_item(
                result.model_dump(mode="json"),
                None,
            )
        except OSError as e:
            raise HTTPException(500, f"Library save failed: {e}") from e
    return result


@app.post("/api/transcribe/url", response_model=TranscriptionResult)
def transcribe_url(
    body: UrlImportRequest,
    language: str | None = Query(
        default=None,
        description="Optional ISO language code, e.g. en",
    ),
    ocr_interval: float | None = Query(
        default=None,
        description="Sample every N seconds for on-screen OCR (Tesseract); omit or 0 to skip",
    ),
    save_library: bool = Query(
        default=False,
        description="If true, persist this result to the local SQLite library (Phase 4)",
    ),
) -> TranscriptionResult:
    if not url_import.url_import_enabled():
        raise HTTPException(
            403,
            "URL import is disabled. Set IG_VTT_URL_IMPORT=1 on the server (Phase 5).",
        )
    if not url_import.yt_dlp_available():
        raise HTTPException(
            503,
            "yt-dlp is not available. Install with: pip install yt-dlp",
        )
    ocr_sec = _parse_ocr_interval(ocr_interval)
    job_id = uuid.uuid4().hex
    out_dir = UPLOAD_DIR / job_id
    raw: dict = {}
    screen: ScreenTextResult | None = None
    display_name = "import.bin"
    try:
        try:
            video_path, display_name = url_import.download_video_to_dir(
                body.url, out_dir
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e
        suf = video_path.suffix.lower()
        if suf not in ALLOWED_EXT:
            raise HTTPException(
                400,
                f"Downloaded type {suf!r} not supported. Allowed: {', '.join(sorted(ALLOWED_EXT))}",
            )
        raw, screen = _compute_transcription(video_path, language, ocr_sec)
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    finally:
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
        except OSError:
            pass

    result = _result_from_raw(job_id, display_name, raw, screen)
    if save_library:
        try:
            library_db.upsert_item(
                result.model_dump(mode="json"),
                None,
            )
        except OSError as e:
            raise HTTPException(500, f"Library save failed: {e}") from e
    return result


@app.post("/api/extract", response_model=ExtractedFacts)
def extract(req: ExtractRequest) -> ExtractedFacts:
    raw = build_extracted_facts(req.text, language=req.language)
    return ExtractedFacts(**raw)


@app.post("/api/library")
def library_save(req: LibrarySaveRequest) -> dict[str, str]:
    library_db.upsert_item(
        req.transcription.model_dump(mode="json"),
        req.extraction.model_dump(mode="json") if req.extraction else None,
    )
    return {"status": "saved", "video_id": req.transcription.video_id}


@app.get("/api/library", response_model=list[LibraryListItem])
def library_list(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[LibraryListItem]:
    rows = library_db.list_items(limit=limit, offset=offset)
    return [
        LibraryListItem(
            video_id=r["video_id"],
            original_filename=r["original_filename"],
            created_at=r["created_at"],
            language=r["language"],
            duration=r["duration"],
            has_extraction=bool(r["has_extraction"]),
        )
        for r in rows
    ]


@app.get("/api/library/search", response_model=list[LibrarySearchHit])
def library_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(30, ge=1, le=100),
) -> list[LibrarySearchHit]:
    rows = library_db.search_items(q, limit=limit)
    return [
        LibrarySearchHit(
            video_id=r["video_id"],
            original_filename=r["original_filename"],
            created_at=r["created_at"],
            language=r["language"],
            duration=r["duration"],
            has_extraction=bool(r["has_extraction"]),
            preview=r.get("preview"),
        )
        for r in rows
    ]


@app.get("/api/library/{video_id}", response_model=LibraryGetResponse)
def library_get(video_id: str) -> LibraryGetResponse:
    row = library_db.get_item(video_id)
    if not row:
        raise HTTPException(404, "Not found")
    ex = row.get("extraction")
    segs = [Segment(**s) for s in row["segments"]]
    st = row.get("screen_text")
    screen = ScreenTextResult.model_validate(st) if st else None
    extraction = ExtractedFacts.model_validate(ex) if ex else None
    return LibraryGetResponse(
        video_id=row["video_id"],
        original_filename=row["original_filename"],
        created_at=row["created_at"],
        language=row.get("language"),
        duration=row.get("duration"),
        text=row.get("text") or "",
        segments=segs,
        screen_text=screen,
        extraction=extraction,
    )


@app.delete("/api/library/{video_id}")
def library_delete(video_id: str) -> dict[str, str | bool]:
    ok = library_db.delete_item(video_id)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True, "video_id": video_id}


@app.patch("/api/library/{video_id}/extraction", response_model=ExtractedFacts)
def library_patch_extraction(video_id: str, body: ExtractedFacts) -> ExtractedFacts:
    data = body.model_dump(mode="json")
    if not library_db.update_extraction_only(video_id, data):
        raise HTTPException(404, "Not found")
    return body


# Serve built SPA from ../frontend/dist when present (optional single-port deploy)
def _static_dir() -> Path | None:
    d = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if d.is_dir() and (d / "index.html").is_file():
        return d
    return None


@app.get("/")
def index():
    d = _static_dir()
    if d:
        return FileResponse(d / "index.html")
    return Response(
        content="API only. Run Vite at http://localhost:5173 or build frontend to frontend/dist",
        media_type="text/plain",
    )


# Optional: mount static assets
_sd = _static_dir()
if _sd:
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/assets",
        StaticFiles(directory=_sd / "assets"),
        name="assets",
    )
