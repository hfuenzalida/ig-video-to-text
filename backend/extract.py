"""Phase 2: derive structured facts from a transcript (LLM optional, heuristics always)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

_URL_RE = re.compile(
    r"(https?://[^\s\]\)\"'<>]+|www\.[^\s\]\)\"'<>]+)",
    re.IGNORECASE,
)
_HANDLE_RE = re.compile(r"@([a-zA-Z0-9._]{1,30})\b")
def _normalize_url(u: str) -> str:
    u = u.rstrip(").,;]")
    if u.lower().startswith("www."):
        return "https://" + u
    return u


def extract_heuristic(text: str) -> dict[str, Any]:
    """URLs, @handles, and rough CTA phrases from the transcript."""
    urls = sorted({_normalize_url(m.group(1)) for m in _URL_RE.finditer(text)})
    handles = sorted({m.group(1) for m in _HANDLE_RE.finditer(text)}, key=str.lower)
    cta_labels: list[str] = []
    if re.search(r"\bfollow\b", text, re.I):
        cta_labels.append("follow")
    if re.search(r"\bsubscribe\b", text, re.I):
        cta_labels.append("subscribe")
    if re.search(r"\blink\s+in\s+bio\b", text, re.I):
        cta_labels.append("link in bio")
    if re.search(r"\bswipe\s+up\b", text, re.I):
        cta_labels.append("swipe up")
    if re.search(r"\bclick\s+(?:the\s+)?link\b", text, re.I):
        cta_labels.append("click link")
    if re.search(r"\bcheck\s+out\b", text, re.I):
        cta_labels.append("check out")
    if re.search(r"\bdm\s+me\b", text, re.I):
        cta_labels.append("DM me")
    if re.search(r"\bcomment\b", text, re.I):
        cta_labels.append("comment")
    out_cta: list[str] = []
    for c in cta_labels:
        if c not in out_cta:
            out_cta.append(c)
    return {
        "urls": urls,
        "handles": handles,
        "calls_to_action": out_cta,
    }


def _llm_config() -> tuple[str | None, str, str]:
    base = os.environ.get("IG_VTT_LLM_BASE_URL", "").strip() or None
    model = os.environ.get("IG_VTT_LLM_MODEL", "llama3.2").strip()
    key = os.environ.get("IG_VTT_LLM_API_KEY", "").strip()
    return base, model, key


def _parse_json_content(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s)


def _merge_lists(a: list[str], b: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in a + b:
        k = x.strip()
        if not k:
            continue
        low = k.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(k)
    return out


def extract_with_llm(text: str, language: str | None) -> dict[str, Any]:
    base, model, api_key = _llm_config()
    if not base:
        return {}
    lang_note = f" The spoken language may be {language}." if language else ""
    schema_hint = """Return ONLY a JSON object with keys:
summary (string, 2-5 sentences),
topics (array of short strings),
entities (array of people, brands, products, places mentioned),
sentiment (one of: positive, neutral, negative, mixed),
calls_to_action (array of strings),
handles (Instagram/Twitter handles without @),
urls (full URLs if any).
Use [] or "" where unknown. No markdown."""
    prompt = f"""You analyze video transcripts (e.g. social reels).{lang_note}

Transcript:
---
{text[:120_000]}
---

{schema_hint}"""
    url = base.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if os.environ.get("IG_VTT_LLM_JSON_MODE", "").strip() in ("1", "true", "yes"):
        payload["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"LLM request failed: {e}") from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected LLM response shape: {data!r}") from e
    if not isinstance(content, str):
        raise RuntimeError("LLM returned non-string content")
    parsed = _parse_json_content(content)
    return {
        "summary": str(parsed.get("summary") or "").strip(),
        "topics": [str(x).strip() for x in (parsed.get("topics") or []) if str(x).strip()],
        "entities": [str(x).strip() for x in (parsed.get("entities") or []) if str(x).strip()],
        "sentiment": str(parsed.get("sentiment") or "").strip() or None,
        "calls_to_action": [
            str(x).strip() for x in (parsed.get("calls_to_action") or []) if str(x).strip()
        ],
        "handles": [str(x).strip().lstrip("@") for x in (parsed.get("handles") or []) if str(x).strip()],
        "urls": [_normalize_url(str(x).strip()) for x in (parsed.get("urls") or []) if str(x).strip()],
    }


def build_extracted_facts(
    text: str, language: str | None = None
) -> dict[str, Any]:
    """Combine heuristic extraction with optional OpenAI-compatible LLM."""
    h = extract_heuristic(text)
    method = "heuristic"
    summary = ""
    topics: list[str] = []
    entities: list[str] = []
    sentiment: str | None = None
    llm_part: dict[str, Any] = {}
    base, _, _ = _llm_config()
    if base and text.strip():
        try:
            llm_part = extract_with_llm(text, language)
        except RuntimeError:
            llm_part = {}
        if llm_part:
            method = "llm+heuristic"
            summary = llm_part.get("summary") or ""
            topics = llm_part.get("topics") or []
            entities = llm_part.get("entities") or []
            sentiment = llm_part.get("sentiment")
            if sentiment and sentiment.lower() not in (
                "positive",
                "neutral",
                "negative",
                "mixed",
            ):
                sentiment = None
    calls = _merge_lists(llm_part.get("calls_to_action") or [], h["calls_to_action"])
    handles = _merge_lists(llm_part.get("handles") or [], h["handles"])
    urls = _merge_lists(llm_part.get("urls") or [], h["urls"])
    return {
        "summary": summary,
        "topics": topics,
        "entities": entities,
        "sentiment": sentiment,
        "calls_to_action": calls,
        "handles": handles,
        "urls": urls,
        "method": method,
    }
