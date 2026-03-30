from __future__ import annotations

import asyncio
import json
import os
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


APP_DIR = Path(__file__).resolve().parent
SCRAPER_SCRIPT = APP_DIR / "playwright_scraper.py"


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

    async def event_stream() -> AsyncIterator[bytes]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert proc.stdout is not None
        assert proc.stderr is not None

        stdout_lines: list[str] = []

        async def _read_stdout() -> None:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                stdout_lines.append(line.decode("utf-8", errors="replace"))

        stdout_task = asyncio.create_task(_read_stdout())

        try:
            # Stream progress JSON objects from stderr as SSE events.
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                # stderr is expected to be a JSON object per line
                try:
                    evt = json.loads(raw)
                    if isinstance(evt, dict):
                        yield _sse(evt)
                    else:
                        yield _sse({"event": "info", "message": raw})
                except Exception:
                    yield _sse({"event": "info", "message": raw})

            code = await proc.wait()
            await stdout_task

            raw_stdout = "".join(stdout_lines).strip()
            final_line = raw_stdout.split("\n")[-1].strip() if raw_stdout else "{}"
            result_payload: dict[str, Any] = {}
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
                result_payload["text"] = result_payload.get("text") or f"scrape-playwright failed with code {code}"

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

    return StreamingResponse(event_stream(), media_type="text/event-stream")

