"""Phase 5: optional URL fetch (e.g. Instagram) via yt-dlp — fragile; use at your own risk."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

# Suffixes: host matches if it equals p or ends with "." + p (e.g. www.instagram.com).
_DEFAULT_HOST_PATTERNS = "instagram.com"


def url_import_enabled() -> bool:
    v = os.environ.get("IG_VTT_URL_IMPORT", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _host_patterns() -> list[str]:
    raw = os.environ.get("IG_VTT_URL_IMPORT_HOSTS", _DEFAULT_HOST_PATTERNS).strip()
    if not raw:
        return [_DEFAULT_HOST_PATTERNS]
    return [x.strip().strip(".").lower() for x in raw.split(",") if x.strip()]


def allowed_hosts_label() -> str:
    return ",".join(_host_patterns())


def assert_url_allowed(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("Only http(s) URLs are allowed")
    host = (p.hostname or "").lower()
    if not host:
        raise ValueError("URL has no host")
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127."):
        raise ValueError("Local hosts are not allowed")
    if re.match(r"^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)", host):
        raise ValueError("Private network hosts are not allowed")
    ok = False
    for pat in _host_patterns():
        if host == pat or host.endswith("." + pat):
            ok = True
            break
    if not ok:
        raise ValueError(
            f"Host {host!r} is not in the import allowlist "
            f"(set IG_VTT_URL_IMPORT_HOSTS; default: instagram.com subdomains)"
        )


def yt_dlp_command() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def yt_dlp_available() -> bool:
    cmd = yt_dlp_command()
    try:
        r = subprocess.run(
            [*cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def download_video_to_dir(url: str, dest_dir: Path) -> tuple[Path, str]:
    """
    Download a single media file into dest_dir. Returns (path, suggested filename).
    """
    assert_url_allowed(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = dest_dir / "src.%(ext)s"
    max_mb = int(os.environ.get("IG_VTT_MAX_UPLOAD_MB", "500"))
    timeout = int(os.environ.get("IG_VTT_URL_IMPORT_TIMEOUT_SEC", "600"))
    extra = os.environ.get("IG_VTT_YTDLP_ARGS", "").strip()
    extra_parts = shlex_split_safe(extra)
    cmd = [
        *yt_dlp_command(),
        "--no-playlist",
        "--newline",
        "-f",
        "bestvideo*+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(out_tmpl),
        "--max-filesize",
        f"{max_mb}M",
        "--socket-timeout",
        "30",
        "--retries",
        "3",
        *extra_parts,
        url,
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Download timed out after {timeout}s") from e
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or "yt-dlp failed"
        raise RuntimeError(err[:2000])

    candidates = [p for p in dest_dir.iterdir() if p.is_file()]
    if not candidates:
        raise RuntimeError("yt-dlp produced no file (Instagram often needs cookies; see README)")
    video = max(candidates, key=lambda p: p.stat().st_size)
    name = video.name
    if name.startswith("src."):
        name = f"import-{name[4:]}"
    return video, name


def shlex_split_safe(s: str) -> list[str]:
    if not s:
        return []
    try:
        import shlex

        return shlex.split(s, posix=False)
    except ValueError:
        return []
