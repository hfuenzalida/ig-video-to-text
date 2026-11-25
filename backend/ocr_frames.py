"""Phase 3: sample video frames and OCR with Tesseract."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

def _which_tesseract_cmd() -> str | None:
    env = os.environ.get("IG_VTT_TESSERACT_CMD", "").strip()
    if env and Path(env).is_file():
        return env
    return shutil.which("tesseract")


def probe_duration_seconds(video_path: Path) -> float | None:
    """Best-effort duration via ffprobe (optional if Whisper already returned duration)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return None
    try:
        return max(0.0, float((r.stdout or "").strip()))
    except ValueError:
        return None


def _sample_times(duration: float, interval: float, max_frames: int) -> list[float]:
    if duration <= 0 or interval <= 0 or max_frames <= 0:
        return []
    times: list[float] = []
    t = 0.0
    # Leave small margin so last seek is inside file
    end = max(0.0, duration - 0.05)
    while t <= end and len(times) < max_frames:
        times.append(round(t, 2))
        t += interval
    return times


def _extract_frame_png(video_path: Path, t_sec: float, out_png: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(t_sec),
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_png),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not out_png.is_file():
        raise RuntimeError(
            f"ffmpeg frame extract failed at {t_sec}s: {r.stderr or r.stdout or 'unknown'}"
        )


def _ocr_png(path: Path, lang: str) -> str:
    import pytesseract
    from PIL import Image

    cmd = _which_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    with Image.open(path) as im:
        im = im.convert("RGB")
        return pytesseract.image_to_string(im, lang=lang) or ""


def _normalize_line(s: str) -> str:
    s = " ".join(s.split())
    return s.strip()


def dedupe_lines(frame_texts: list[tuple[float, str]]) -> list[str]:
    """First-seen order; case-insensitive key; drop near-duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for _t, raw in frame_texts:
        for line in raw.splitlines():
            n = _normalize_line(line)
            if not n:
                continue
            key = n.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(n)
    return out


def process_video_screen_ocr(
    video_path: Path,
    *,
    interval_sec: float,
    duration_hint: float | None = None,
) -> dict[str, Any]:
    """
    Sample frames every interval_sec; run Tesseract; dedupe lines.
    """
    if interval_sec <= 0:
        raise ValueError("interval_sec must be positive")
    tess = _which_tesseract_cmd()
    if not tess:
        raise RuntimeError(
            "Tesseract not found. Install Tesseract OCR and add it to PATH, "
            "or set IG_VTT_TESSERACT_CMD to the tesseract executable."
        )
    duration = duration_hint
    if duration is None or duration <= 0:
        duration = probe_duration_seconds(video_path)
    if duration is None or duration <= 0:
        raise RuntimeError(
            "Could not determine video duration for OCR sampling (need speech "
            "transcript duration or ffprobe)."
        )

    max_frames = int(os.environ.get("IG_VTT_OCR_MAX_FRAMES", "60"))
    lang = os.environ.get("IG_VTT_OCR_LANG", "eng").strip() or "eng"
    times = _sample_times(duration, interval_sec, max_frames)
    if not times:
        return {
            "interval_sec": interval_sec,
            "frames": [],
            "lines_deduped": [],
            "method": "tesseract",
        }

    frame_rows: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory(prefix="igvtt_ocr_") as tmp:
        tmp_path = Path(tmp)
        for t in times:
            png = tmp_path / f"f_{uuid.uuid4().hex}.png"
            try:
                _extract_frame_png(video_path, t, png)
                txt = _ocr_png(png, lang).strip()
            except (RuntimeError, OSError):
                txt = ""
            finally:
                png.unlink(missing_ok=True)
            if txt:
                frame_rows.append((t, txt))

    lines = dedupe_lines(frame_rows)
    frames_out = [{"t": t, "text": text} for t, text in frame_rows]
    return {
        "interval_sec": interval_sec,
        "frames": frames_out,
        "lines_deduped": lines,
        "method": "tesseract",
    }
