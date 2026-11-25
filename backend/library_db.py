"""Phase 4: local SQLite library with FTS5 keyword search."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    original_filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    language TEXT,
    duration REAL,
    transcript TEXT NOT NULL,
    segments_json TEXT NOT NULL,
    screen_json TEXT,
    extraction_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_library_created ON library(created_at DESC);
"""


def db_path() -> Path:
    return Path(
        os.environ.get(
            "IG_VTT_DB_PATH",
            Path(__file__).resolve().parent / "data" / "library.db",
        )
    )


def connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as c:
        c.executescript(_SCHEMA)
        cur = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_fts'"
        )
        if cur.fetchone() is None:
            c.execute(
                """
                CREATE VIRTUAL TABLE library_fts USING fts5(
                    job_uuid UNINDEXED,
                    filename,
                    body,
                    tokenize = 'unicode61'
                )
                """
            )


def _screen_lines(screen: dict[str, Any] | None) -> str:
    if not screen:
        return ""
    lines = screen.get("lines_deduped") or []
    return "\n".join(str(x) for x in lines if x)


def _extraction_blob(ex: dict[str, Any] | None) -> str:
    if not ex:
        return ""
    parts: list[str] = []
    if ex.get("summary"):
        parts.append(str(ex["summary"]))
    for key in ("topics", "entities", "calls_to_action", "handles", "urls"):
        for x in ex.get(key) or []:
            parts.append(str(x))
    if ex.get("sentiment"):
        parts.append(str(ex["sentiment"]))
    return "\n".join(parts)


def build_search_body(
    transcript: str,
    screen: dict[str, Any] | None,
    extraction: dict[str, Any] | None,
) -> str:
    chunks = [
        transcript or "",
        _screen_lines(screen),
        _extraction_blob(extraction),
    ]
    return "\n".join(c for c in chunks if c).strip()


def _fts_user_query(q: str) -> str | None:
    q = (q or "").strip()
    if not q:
        return None
    tokens = re.findall(r"[^\s]+", q)[:16]
    if not tokens:
        return None
    parts: list[str] = []
    for t in tokens:
        t = t.strip('"').replace('"', "")
        if not t:
            continue
        if any(c in t for c in '*:"(){}[]'):
            continue
        parts.append(f'"{t}"')
    if not parts:
        return None
    return " AND ".join(parts)


def _refresh_fts(
    conn: sqlite3.Connection,
    uuid: str,
    filename: str,
    transcript: str,
    screen: dict[str, Any] | None,
    extraction: dict[str, Any] | None,
) -> None:
    conn.execute("DELETE FROM library_fts WHERE job_uuid = ?", (uuid,))
    body = build_search_body(transcript, screen, extraction)
    conn.execute(
        "INSERT INTO library_fts(job_uuid, filename, body) VALUES (?, ?, ?)",
        (uuid, filename, body),
    )


def upsert_item(
    transcription: dict[str, Any],
    extraction: dict[str, Any] | None,
) -> None:
    uuid = transcription["video_id"]
    filename = transcription["original_filename"]
    transcript = transcription.get("text") or ""
    segments_json = json.dumps(transcription.get("segments") or [])
    screen = transcription.get("screen_text")
    screen_json = json.dumps(screen) if screen else None
    extraction_json = json.dumps(extraction) if extraction else None
    lang = transcription.get("language")
    duration = transcription.get("duration")

    with connect() as c:
        c.execute(
            """
            INSERT INTO library (
                uuid, original_filename, language, duration,
                transcript, segments_json, screen_json, extraction_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uuid) DO UPDATE SET
                original_filename = excluded.original_filename,
                language = excluded.language,
                duration = excluded.duration,
                transcript = excluded.transcript,
                segments_json = excluded.segments_json,
                screen_json = COALESCE(excluded.screen_json, library.screen_json),
                extraction_json = COALESCE(
                    excluded.extraction_json, library.extraction_json
                )
            """,
            (
                uuid,
                filename,
                lang,
                duration,
                transcript,
                segments_json,
                screen_json,
                extraction_json,
            ),
        )
        row = c.execute(
            """
            SELECT original_filename, transcript, screen_json, extraction_json
            FROM library WHERE uuid = ?
            """,
            (uuid,),
        ).fetchone()
        assert row is not None
        fn = row["original_filename"]
        tx = row["transcript"]
        scr = json.loads(row["screen_json"]) if row["screen_json"] else None
        exo = json.loads(row["extraction_json"]) if row["extraction_json"] else None
        _refresh_fts(c, uuid, fn, tx, scr, exo)
        c.commit()


def update_extraction_only(uuid: str, extraction: dict[str, Any]) -> bool:
    with connect() as c:
        row = c.execute(
            "SELECT original_filename, transcript, screen_json, extraction_json FROM library WHERE uuid = ?",
            (uuid,),
        ).fetchone()
        if not row:
            return False
        filename, transcript, screen_json, _old_ex = row
        screen = json.loads(screen_json) if screen_json else None
        c.execute(
            "UPDATE library SET extraction_json = ? WHERE uuid = ?",
            (json.dumps(extraction), uuid),
        )
        _refresh_fts(c, uuid, filename, transcript, screen, extraction)
        c.commit()
    return True


def delete_item(uuid: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM library WHERE uuid = ?", (uuid,))
        c.execute("DELETE FROM library_fts WHERE job_uuid = ?", (uuid,))
        c.commit()
        return cur.rowcount > 0


def list_items(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with connect() as c:
        rows = c.execute(
            """
            SELECT uuid, original_filename, created_at, language, duration,
                   (extraction_json IS NOT NULL AND length(extraction_json) > 2) AS has_extraction
            FROM library
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["video_id"] = d.pop("uuid")
        out.append(d)
    return out


def get_item(uuid: str) -> dict[str, Any] | None:
    with connect() as c:
        row = c.execute("SELECT * FROM library WHERE uuid = ?", (uuid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["segments"] = json.loads(d.pop("segments_json") or "[]")
        d["text"] = d.pop("transcript")
        if d.get("screen_json"):
            d["screen_text"] = json.loads(d.pop("screen_json"))
        else:
            d.pop("screen_json", None)
            d["screen_text"] = None
        if d.get("extraction_json"):
            d["extraction"] = json.loads(d.pop("extraction_json"))
        else:
            d.pop("extraction_json", None)
            d["extraction"] = None
        d["video_id"] = d.pop("uuid")
        d.pop("id", None)
        return d


def search_items(q: str, limit: int = 30) -> list[dict[str, Any]]:
    mq = _fts_user_query(q)
    if not mq:
        return []
    limit = max(1, min(limit, 100))
    with connect() as c:
        try:
            rows = c.execute(
                """
                SELECT l.uuid, l.original_filename, l.created_at, l.language, l.duration,
                       (l.extraction_json IS NOT NULL AND length(l.extraction_json) > 2)
                         AS has_extraction,
                       snippet(library_fts, 2, '[', ']', '…', 20) AS preview,
                       bm25(library_fts) AS score
                FROM library l
                JOIN library_fts ON l.uuid = library_fts.job_uuid
                WHERE library_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (mq, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = c.execute(
                """
                SELECT l.uuid, l.original_filename, l.created_at, l.language, l.duration,
                       (l.extraction_json IS NOT NULL AND length(l.extraction_json) > 2)
                         AS has_extraction,
                       snippet(library_fts, 2, '[', ']', '…', 20) AS preview,
                       0 AS score
                FROM library l
                JOIN library_fts ON l.uuid = library_fts.job_uuid
                WHERE library_fts MATCH ?
                LIMIT ?
                """,
                (mq, limit),
            ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["video_id"] = d.pop("uuid")
        out.append(d)
    return out
