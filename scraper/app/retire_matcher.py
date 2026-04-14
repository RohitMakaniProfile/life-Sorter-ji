"""
Download and apply Retire.js jsrepository.json rules against script-loaded URLs and bodies.

Rule source: https://github.com/RetireJS/retire.js (repository/jsrepository.json).
Intended for identifying common client-side libraries from network responses, not CVE reporting here.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_RETIRE_URL = (
    "https://raw.githubusercontent.com/RetireJS/retire.js/master/repository/jsrepository.json"
)

_VERSION_PLACEHOLDER = "§§version§§"


@dataclass(frozen=True)
class _CompiledPattern:
    library_id: str
    kind: str  # uri | filename | filecontent
    pattern: str
    regex: re.Pattern[str]


def _retire_regex_from_pattern(raw: str) -> str | None:
    """Turn Retire pattern into a Python regex; §§version§§ becomes a version capture."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw
    if _VERSION_PLACEHOLDER in s:
        s = s.replace(_VERSION_PLACEHOLDER, r"(?P<ver>[\w\.\-\+a-zA-Z]*)")
    return s


def _cache_path() -> Path:
    base = Path(__file__).resolve().parent / ".cache"
    base.mkdir(parents=True, exist_ok=True)
    return base / "jsrepository.json"


def fetch_retire_repo(
    url: str | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Load Retire jsrepository.json from disk cache when fresh; otherwise download.
    Env: RETIRE_JSREPO_URL, RETIRE_CACHE_MAX_AGE_SEC (default 7d), SKIP_RETIRE_DOWNLOAD=1 to use stale-only.
    """
    src = (url or os.getenv("RETIRE_JSREPO_URL") or "").strip() or DEFAULT_RETIRE_URL
    path = _cache_path()
    max_age = max_age_seconds
    if max_age is None:
        max_age = int(os.getenv("RETIRE_CACHE_MAX_AGE_SEC", str(7 * 24 * 3600)))

    skip_dl = os.getenv("SKIP_RETIRE_DOWNLOAD", "").lower() in ("1", "true", "yes")
    now = time.time()

    if path.is_file():
        age = now - path.stat().st_mtime
        if skip_dl or age < max_age:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        if skip_dl:
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    req = urllib.request.Request(
        src,
        headers={"User-Agent": "ikshan-playwright-retire/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
        data = json.loads(raw)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        return data
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        raise


def compile_retire_patterns(repo: dict[str, Any] | None) -> list[_CompiledPattern]:
    if not repo:
        return []
    out: list[_CompiledPattern] = []
    for lib_id, entry in repo.items():
        if not isinstance(entry, dict) or lib_id == "retire-example":
            continue
        ext = entry.get("extractors")
        if not isinstance(ext, dict):
            continue
        for kind in ("uri", "filename", "filecontent"):
            patterns = ext.get(kind)
            if not isinstance(patterns, list):
                continue
            for p in patterns:
                if not isinstance(p, str):
                    continue
                rx = _retire_regex_from_pattern(p)
                if not rx:
                    continue
                try:
                    out.append(
                        _CompiledPattern(
                            library_id=str(lib_id),
                            kind=kind,
                            pattern=p[:200],
                            regex=re.compile(rx),
                        )
                    )
                except re.error:
                    continue
    return out


_patterns_cache: list[_CompiledPattern] | None = None


def get_retire_patterns() -> list[_CompiledPattern]:
    global _patterns_cache
    if _patterns_cache is None:
        try:
            repo = fetch_retire_repo()
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            repo = {}
        _patterns_cache = compile_retire_patterns(repo)
    return _patterns_cache


def invalidate_retire_cache() -> None:
    global _patterns_cache
    _patterns_cache = None


def match_script_samples(
    samples: list[dict[str, Any]],
    patterns: list[_CompiledPattern] | None = None,
    max_hits: int = 80,
) -> list[dict[str, Any]]:
    """
    samples: items with keys 'url' (required), 'body' (optional str — truncated JS text).
    Returns dedupe-friendly hit dicts: library, via, sample_url, matched_preview.
    """
    pats = patterns if patterns is not None else get_retire_patterns()
    if not pats or not samples:
        return []

    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for sample in samples:
        url = str(sample.get("url") or "")
        if not url:
            continue
        body = sample.get("body")
        body_str = body if isinstance(body, str) else None
        try:
            path = urlparse(url).path or ""
            base = path.rsplit("/", 1)[-1] if path else ""
        except Exception:
            path, base = "", ""

        for cp in pats:
            key: tuple[str, str, str] | None = None
            if cp.kind == "uri":
                if cp.regex.search(url) or (path and cp.regex.search(path)):
                    key = (cp.library_id, "uri", url[:300])
            elif cp.kind == "filename":
                if base and cp.regex.search(base):
                    key = (cp.library_id, "filename", url[:300])
            elif cp.kind == "filecontent" and body_str:
                m = cp.regex.search(body_str)
                if m:
                    ver = (m.groupdict().get("ver") or "")[:32]
                    key = (cp.library_id, "filecontent", url[:200] + (f"@{ver}" if ver else ""))

            if key and key not in seen:
                seen.add(key)
                hits.append(
                    {
                        "library": cp.library_id,
                        "via": cp.kind,
                        "url": url[:500],
                        "pattern": cp.pattern,
                    }
                )
                if len(hits) >= max_hits:
                    return hits

    return hits


def retire_libraries_from_hits(hits: list[dict[str, Any]]) -> list[str]:
    return sorted({str(h["library"]) for h in hits if h.get("library")})
