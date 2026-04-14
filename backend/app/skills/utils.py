from __future__ import annotations

import json
import re
import traceback
from typing import Any

from .models import ProgressCb

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _json_default(value: Any) -> Any:
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    return str(value)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        try:
            print(
                "[skills.utils] json-dumps-failed",
                {"error": str(exc), "value_type": type(value).__name__, "traceback": traceback.format_exc()},
            )
        except Exception:
            pass
        raise


def _parse_progress_meta(raw_line: str) -> dict[str, Any]:
    """
    Parse a PROGRESS line robustly:
    - strips ANSI escapes
    - extracts JSON even when line has prefixes/suffixes
    - falls back to info/raw event when JSON is absent
    """
    cleaned = _ANSI_RE.sub("", str(raw_line or "")).strip()
    if not cleaned:
        return {"event": "info", "raw": ""}

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start: end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {"event": "info", "raw": cleaned}


def _extract_json_objects_from_text(text: str) -> tuple[list[dict[str, Any]], str]:
    out: list[dict[str, Any]] = []
    dec = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] != "{":
            i += 1
        if i >= n:
            return out, ""
        try:
            obj, j = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            return out, text[i:]
        if isinstance(obj, dict):
            out.append(obj)
        i = j
    return out, ""


def _progress_stream_kind(meta: dict[str, Any]) -> str:
    explicit = str(meta.get("streamKind") or "").strip().lower()
    if explicit in ("info", "data"):
        return explicit
    evt = str(meta.get("event") or "").strip().lower()
    if evt in {"page_data", "data", "result", "record", "item"}:
        return "data"
    return "info"


def _extract_url(message: str) -> str:
    m = re.search(r"https?://\S+", message or "")
    if not m:
        return ""
    return m.group(0).rstrip("),.;]\"'")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _get_by_path(data: Any, path: str | None) -> Any:
    if not path:
        return data
    cur = data
    for token in [p for p in path.split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(token)
        else:
            return None
    return cur


async def _emit(on_progress: ProgressCb | None, event: dict[str, Any]) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(event)
    except Exception as exc:
        try:
            print(f"[skills.utils] on_progress-failed | {exc}")
        except Exception:
            pass

