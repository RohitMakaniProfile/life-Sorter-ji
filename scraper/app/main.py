from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse


def _json_default(value: Any) -> Any:
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    return str(value)


def _sse(data: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n".encode("utf-8")


def _extract_json_objects(buffer: str) -> tuple[list[dict[str, Any]], str]:
    """
    Parse as many top-level JSON objects as possible from a text buffer.
    Supports concatenated objects with or without newlines.
    """
    out: list[dict[str, Any]] = []
    dec = json.JSONDecoder()
    i = 0
    n = len(buffer)
    while i < n:
        # Skip whitespace and noise until a likely JSON object start.
        while i < n and buffer[i] not in "{":
            i += 1
        if i >= n:
            return out, ""
        try:
            obj, j = dec.raw_decode(buffer, i)
        except json.JSONDecodeError:
            # Keep possible partial JSON from the first "{" onward.
            return out, buffer[i:]
        if isinstance(obj, dict):
            out.append(obj)
        i = j
    return out, ""


def _normalize_event_objects(objs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obj in objs:
        # Some emitters double-encode progress JSON into a string field.
        # Unwrap it so backend receives standard dict events.
        if isinstance(obj, dict) and obj.get("event") == "info":
            msg = obj.get("message")
            if isinstance(msg, str):
                nested, rem = _extract_json_objects(msg)
                if nested and not rem.strip():
                    out.extend(nested)
                    continue
        out.append(obj)
    return out


def _parse_stderr_fragment(text: str) -> list[dict[str, Any]]:
    line = text.strip()
    if not line:
        return []
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            return _normalize_event_objects([obj])
    except Exception:
        pass

    rec_objs, rem = _extract_json_objects(line)
    rec_objs = _normalize_event_objects(rec_objs)
    if rec_objs:
        residue = (rem or "").strip()
        if residue:
            rec_objs.append({"event": "info", "message": residue})
        return rec_objs

    return [{"event": "info", "message": line}]


APP_DIR = Path(__file__).resolve().parent
SCRAPER_SCRIPT = APP_DIR / "playwright_scraper.py"

import sys as _sys
if str(APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(APP_DIR))


app = FastAPI(title="Ikshan Scraper", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/v1/scrape-playwright/stream")
async def scrape_playwright_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    url = str(body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    max_pages = body.get("maxPages")
    max_depth = body.get("maxDepth")
    deep = body.get("deep")
    parallel = body.get("parallel")
    resume_ck = body.get("resumeCheckpoint")
    skip_urls = body.get("skipUrls")

    job_file: str | None = None
    job_obj: dict[str, Any] = {}
    if isinstance(resume_ck, dict) and resume_ck:
        job_obj["resumeCheckpoint"] = resume_ck
    if isinstance(skip_urls, list) and skip_urls:
        job_obj["skipUrls"] = skip_urls
    if job_obj:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as jf:
            json.dump(job_obj, jf, ensure_ascii=False)
            job_file = jf.name

    cmd: list[str] = [
        os.environ.get("PYTHON", "python"),
        "-u",
        str(SCRAPER_SCRIPT),
        "--url",
        url,
    ]
    if max_pages is not None:
        cmd += ["--max-pages", str(int(max_pages))]
    if max_depth is not None:
        cmd += ["--max-depth", str(int(max_depth))]
    if bool(deep):
        cmd += ["--deep"]
    if parallel is not None:
        cmd += ["--parallel"] if bool(parallel) else ["--no-parallel"]
    if job_file:
        cmd += ["--job-json", job_file]

    async def event_stream() -> AsyncIterator[bytes]:
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            assert proc.stdout is not None
            assert proc.stderr is not None

            stdout_chunks: list[bytes] = []

            async def _read_stdout() -> None:
                while True:
                    chunk = await proc.stdout.read(65536)
                    if not chunk:
                        break
                    stdout_chunks.append(chunk)

            stdout_task = asyncio.create_task(_read_stdout())
            stderr_buffer = ""

            try:
                while True:
                    chunk_b = await proc.stderr.read(65536)
                    if not chunk_b:
                        break
                    stderr_buffer += chunk_b.decode("utf-8", errors="replace")
                    while True:
                        newline_idx = stderr_buffer.find("\n")
                        if newline_idx == -1:
                            break
                        line = stderr_buffer[:newline_idx]
                        stderr_buffer = stderr_buffer[newline_idx + 1 :]
                        for evt in _parse_stderr_fragment(line):
                            yield _sse(evt)

                if stderr_buffer.strip():
                    for evt in _parse_stderr_fragment(stderr_buffer):
                        yield _sse(evt)

                code = await proc.wait()
                await stdout_task

                raw_stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace").strip()
                final_line = raw_stdout.split("\n")[-1].strip() if raw_stdout else "{}"
                result_payload: dict[str, Any] = {}
                try:
                    parsed = json.loads(raw_stdout or final_line)
                    if isinstance(parsed, dict):
                        result_payload = parsed
                except Exception:
                    try:
                        parsed = json.loads(final_line)
                        if isinstance(parsed, dict):
                            result_payload = parsed
                    except Exception:
                        result_payload = {
                            "text": "scrape-playwright: could not parse scraper result",
                            "error": "playwright_parse_error",
                        }

                if code != 0 and not result_payload.get("error"):
                    result_payload["error"] = "playwright_scraper_failed"
                    result_payload["text"] = result_payload.get("text") or (
                        f"scrape-playwright failed with code {code}"
                    )

                # Normalize done payload shape for backend consumer.
                if (
                    isinstance(result_payload, dict)
                    and result_payload.get("data") is None
                    and result_payload.get("error") is None
                ):
                    result_payload = {
                        "text": str(result_payload.get("text") or ""),
                        "data": result_payload,
                        "error": None,
                    }
                yield _sse({"event": "done", "result": result_payload})
            finally:
                try:
                    if proc.returncode is None:
                        proc.kill()
                except Exception:
                    pass
                try:
                    stdout_task.cancel()
                except Exception:
                    pass
        finally:
            if job_file:
                try:
                    os.unlink(job_file)
                except OSError:
                    pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")

