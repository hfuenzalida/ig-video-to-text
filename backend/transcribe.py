"""Extract audio with ffmpeg, transcribe with faster-whisper."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

# Lazy singleton to avoid loading model on import (slow).
_model = None
_model_name: str | None = None


def _get_model() -> Any:
    global _model, _model_name
    name = os.environ.get("WHISPER_MODEL", "base")
    if _model is not None and _model_name == name:
        return _model
    from faster_whisper import WhisperModel

    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "default")
    if compute_type == "default":
        compute_type = "int8" if device == "cpu" else "float16"
    _model = WhisperModel(
        name,
        device=device,
        compute_type=compute_type,
    )
    _model_name = name
    return _model


def _which_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install from https://ffmpeg.org/download.html"
        )
    return p


def extract_audio_16k_mono_wav(video_path: Path, out_wav: Path) -> None:
    _which_ffmpeg()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_wav),
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {r.stderr or r.stdout or 'unknown error'}"
        )


def transcribe_wav(
    wav_path: Path, language: str | None = None
) -> dict[str, Any]:
    model = _get_model()
    kwargs: dict[str, Any] = {"beam_size": 5}
    if language:
        kwargs["language"] = language
    segments_iter, info = model.transcribe(str(wav_path), **kwargs)
    segs: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    for seg in segments_iter:
        t = (seg.text or "").strip()
        if not t:
            continue
        full_text_parts.append(t)
        segs.append(
            {
                "start": round(float(seg.start), 2),
                "end": round(float(seg.end), 2),
                "text": t,
            }
        )
    full = " ".join(full_text_parts).strip()
    return {
        "text": full,
        "segments": segs,
        "language": getattr(info, "language", None),
        "duration": getattr(info, "duration", None),
    }


def process_video_to_transcript(
    video_path: Path, language: str | None = None
) -> dict[str, Any]:
    """Transcribe a video file; uses temp dir for intermediate wav."""
    with tempfile.TemporaryDirectory(prefix="igvtt_") as tmp:
        wav = Path(tmp) / f"{uuid.uuid4().hex}.wav"
        extract_audio_16k_mono_wav(video_path, wav)
        return transcribe_wav(wav, language=language)
