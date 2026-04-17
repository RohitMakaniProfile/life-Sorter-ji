"""
skills/service.py  —  thin orchestrator
========================================
Public API (unchanged for all callers):
    load_skills, get_skill, list_skills, first_skill_id,
    run_skill, SkillManifest, SkillRunResult

All heavy logic lives in sub-modules:
    models.py          – SkillManifest, SkillRunResult, ProgressCb
    utils.py           – JSON / progress helpers
    loader.py          – skill registry
    summarizer.py      – LLM summarisation helpers
    platform_scout.py  – platform-scout skill
    scraper_service.py – scrape-playwright skill + scraped_pages persistence
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.config import PYTHON_BIN

# ── Re-export public API so callers don't need to change imports ──────────────
from .models import PageCb, ProgressCb, SkillManifest, SkillRunResult  # noqa: F401
from .loader import load_skills, get_skill, list_skills, first_skill_id  # noqa: F401
from .utils import (
    _json_dumps, _emit,
    _parse_progress_meta, _progress_stream_kind,
)
from .summarizer import (
    _summarize_single,
    _summarize_multi_page,
)
from .platform_scout import run_platform_scout


async def _stream_skill_subprocess_stdout(
    proc: asyncio.subprocess.Process,
    on_progress: ProgressCb | None,
    on_page: PageCb | None = None,
) -> tuple[str, bytes, str, int]:
    """
    Read skill subprocess stdout line-by-line so PROGRESS: events reach
    on_progress immediately instead of buffering until the process exits.
    """
    assert proc.stdout is not None
    stdout_parts: list[str] = []
    result_line = ""

    async def _drain_stderr() -> bytes:
        return await proc.stderr.read() if proc.stderr else b""

    stderr_task = asyncio.create_task(_drain_stderr())

    pending = ""
    while True:
        chunk_b = await proc.stdout.read(64 * 1024)
        if not chunk_b:
            break
        chunk = pending + chunk_b.decode("utf-8", errors="replace")
        stdout_parts.append(chunk_b.decode("utf-8", errors="replace"))
        lines = chunk.splitlines(keepends=True)
        pending = ""

        complete_lines: list[str] = []
        for ln in lines:
            if ln.endswith("\n") or ln.endswith("\r"):
                complete_lines.append(ln.rstrip("\r\n"))
            else:
                pending = ln

        for raw in complete_lines:
            t = raw.strip()
            if not t:
                continue
            if t.startswith("PROGRESS:"):
                raw_json = t[len("PROGRESS:"):].strip()
                meta = _parse_progress_meta(raw_json)
                meta["streamKind"] = _progress_stream_kind(meta)

                # Log page_data events for debugging
                if meta.get("event") == "page_data":
                    import structlog
                    logger = structlog.get_logger()
                    logger.info("skill_subprocess_page_data_received",
                               url=meta.get("url"),
                               has_on_page_callback=on_page is not None,
                               stream_kind=meta.get("streamKind"))

                if on_page is not None and meta.get("streamKind") == "data":
                    try:
                        await on_page(meta)
                    except Exception as e:
                        # Never break stream processing due to page callback failures.
                        import structlog
                        logger = structlog.get_logger()
                        logger.error("skill_on_page_callback_failed",
                                   url=meta.get("url"),
                                   error=str(e),
                                   error_type=type(e).__name__)
                event_name = str(meta.get("event", "info"))
                message_text = str(meta.get("url") or meta.get("message") or event_name)
                await _emit(on_progress, {
                    "stage": "running", "type": "info",
                    "message": message_text, "meta": meta,
                })
            else:
                result_line = t

    if pending.strip():
        t = pending.strip()
        if t.startswith("PROGRESS:"):
            raw_json = t[len("PROGRESS:"):].strip()
            meta = _parse_progress_meta(raw_json)
            meta["streamKind"] = _progress_stream_kind(meta)
            if on_page is not None and meta.get("streamKind") == "data":
                try:
                    await on_page(meta)
                except Exception:
                    pass
            event_name = str(meta.get("event", "info"))
            message_text = str(meta.get("url") or meta.get("message") or event_name)
            await _emit(on_progress, {
                "stage": "running", "type": "info",
                "message": message_text, "meta": meta,
            })
        else:
            result_line = t

    stderr_data = await stderr_task
    exit_code = await proc.wait()
    return "".join(stdout_parts), stderr_data, result_line, exit_code


async def run_skill(
    skill_id: str,
    message: str,
    history: list[dict[str, Any]] | None = None,
    args: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
    on_page: PageCb | None = None,
) -> SkillRunResult:
    manifest = get_skill(skill_id)
    if not manifest:
        return SkillRunResult(
            status="error", text="", error=f"Unknown skill: {skill_id}",
            data=None, duration_ms=0,
        )

    # ── Platform scout (pure-Python, no subprocess) ───────────────────────
    if skill_id == "platform-scout":
        return await run_platform_scout(message, args, on_progress)

    # ── Scrape-playwright (HTTP call to scraper microservice) ─────────────
    if skill_id == "scrape-playwright":
        from .scraper_service import run_playwright_skill
        return await run_playwright_skill(message, args or {}, on_progress, on_page)

    # ── Generic subprocess skill ──────────────────────────────────────────
    script_path = manifest.directory / manifest.entry
    if not script_path.exists():
        return SkillRunResult(
            status="error", text="",
            error=f"Skill entry not found: {script_path}",
            data=None, duration_ms=0,
        )

    started = time.time()
    payload: dict[str, Any] = {
        "message": message,
        "history": history or [],
        "skillId": skill_id,
        "runId": f"{skill_id}-{int(started * 1000)}",
    }
    if args:
        payload["args"] = args

    proc = await asyncio.create_subprocess_exec(
        PYTHON_BIN, "-u", str(script_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert proc.stdin is not None
    proc.stdin.write(_json_dumps(payload).encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    stdout_text, stderr_data, result_line, exit_code = await _stream_skill_subprocess_stdout(proc, on_progress, on_page)
    stderr_text = stderr_data.decode("utf-8", errors="replace").strip()

    text = stdout_text.strip()
    err: str | None = None
    data: Any = None
    parsed: dict[str, Any] | None = None

    parse_target = result_line or stdout_text.strip()
    if parse_target:
        try:
            parsed = json.loads(parse_target)
            if isinstance(parsed, dict):
                if isinstance(parsed.get("text"), str):
                    text = parsed.get("text") or ""
                if parsed.get("data") is not None:
                    data = parsed.get("data")
                if parsed.get("error"):
                    err = str(parsed.get("error"))
        except Exception:
            pass

    if exit_code != 0 and not err:
        err = stderr_text or f"Skill exited with code {exit_code}"

    # Log detailed error information for debugging
    if err or exit_code != 0:
        import structlog
        logger = structlog.get_logger()
        logger.error("skill_subprocess_failed",
                    skill_id=skill_id,
                    exit_code=exit_code,
                    error=err,
                    stderr=stderr_text[:1000] if stderr_text else None,
                    stdout_preview=stdout_text[:500] if stdout_text else None,
                    result_line=result_line[:500] if result_line else None,
                    parsed_error=parsed.get("error") if parsed and isinstance(parsed, dict) else None)

    status = "error" if err else "ok"
    if not text and err:
        text = ""

    if (
        on_page is None
        and status == "ok"
        and data is not None
        and manifest.summary_mode in ("single", "multi_page")
    ):
        try:
            if manifest.summary_mode == "multi_page":
                text = await _summarize_multi_page(
                    skill_id=skill_id, data=data,
                    array_path=manifest.summary_array_path,
                    content_field=manifest.summary_content_field,
                    url_field=manifest.summary_url_field,
                    fallback_text=text, on_progress=on_progress,
                )
            else:
                text = await _summarize_single(
                    skill_id=skill_id, data=data,
                    fallback_text=text, on_progress=on_progress,
                )
        except Exception:
            pass

    return SkillRunResult(
        status=status, text=text, error=err, data=data,
        duration_ms=int((time.time() - started) * 1000),
    )
