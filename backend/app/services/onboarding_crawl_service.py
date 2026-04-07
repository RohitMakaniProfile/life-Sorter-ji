"""
Onboarding crawl service — single-page Playwright scrape + web summary + RCA questions.

Replaces crawl_service.py for the onboarding task stream. Responsibilities:
  1. Run scrape-playwright skill (maxPages=1) and record in skill_calls table.
  2. Build a compact web_summary string from the page data.
  3. Generate up to 3 RCA questions using the web_summary + onboarding context.
  4. Persist web_summary and rca_qa back to the onboarding row.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Awaitable, Callable

import httpx
import structlog

from app.db import get_pool
from app.services.ai_helper import ai_helper as _ai

logger = structlog.get_logger()

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]

# ---------------------------------------------------------------------------
# skill_calls helpers
# ---------------------------------------------------------------------------

async def create_onboarding_skill_call(
    *,
    onboarding_session_id: str,
    skill_id: str,
    input: dict[str, Any],
) -> int:
    """INSERT a running skill_call row scoped to an onboarding session. Returns the row id."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            """
            INSERT INTO skill_calls
                (onboarding_session_id, skill_id, run_id, input, state)
            VALUES ($1, $2, $3, $4::jsonb, 'running')
            RETURNING id
            """,
            onboarding_session_id,
            skill_id,
            f"{skill_id}-onboarding-{int(time.time() * 1000)}",
            json.dumps(input),
        )
    return int(row_id)


async def finish_onboarding_skill_call(
    skill_call_id: int,
    *,
    output: Any,
    error: str | None = None,
    started_at_ms: float,
) -> None:
    """Mark a skill_call row as done (or error) and store output."""
    state = "error" if error else "done"
    duration_ms = int((time.time() - started_at_ms) * 1000)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE skill_calls
            SET state        = $1,
                output       = $2::jsonb,
                error        = $3,
                ended_at     = NOW(),
                duration_ms  = $4
            WHERE id = $5
            """,
            state,
            json.dumps(output if output is not None else []),
            error,
            duration_ms,
            skill_call_id,
        )


# ---------------------------------------------------------------------------
# Single-page Playwright scrape
# ---------------------------------------------------------------------------

async def run_playwright_single_page(
    *,
    url: str,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """
    Call the remote scraper microservice with maxPages=1.
    Returns the first (and only) page dict from result.data.pages,
    or a minimal error dict if the scrape fails.
    """
    base = os.getenv("SCRAPER_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError("SCRAPER_BASE_URL not configured")

    payload: dict[str, Any] = {"url": url, "maxPages": 1}
    done_result: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{base}/v1/scrape-playwright/stream",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code >= 400:
                err_text = (await resp.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"scraper_http_{resp.status_code}: {err_text.strip() or 'request failed'}"
                )

            async for line in resp.aiter_lines():
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if not raw:
                    continue
                try:
                    meta = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(meta, dict):
                    continue

                event = str(meta.get("event") or "").strip().lower()

                if event == "done" and isinstance(meta.get("result"), dict):
                    done_result = meta["result"]
                    continue

                # Forward progress to the task-stream send callback
                if on_progress:
                    await on_progress({
                        "stage": "scraping",
                        "label": str(meta.get("url") or meta.get("message") or event or "Scraping"),
                        "current_page": str(meta.get("url") or ""),
                    })

    if done_result is None:
        raise RuntimeError("scraper stream ended without done event")

    if done_result.get("error"):
        raise RuntimeError(str(done_result["error"]))

    data = done_result.get("data") or {}
    # Normalise: some scraper builds return payload directly instead of nesting under data
    if not isinstance(data, dict):
        data = done_result

    pages: list[dict[str, Any]] = data.get("pages") or []
    if pages and isinstance(pages[0], dict):
        return pages[0]

    # Fallback: build a minimal record from whatever the scraper returned
    return {
        "url": url,
        "title": str(data.get("title") or ""),
        "meta_description": str(data.get("meta_description") or ""),
        "elements": data.get("elements") or [],
        "tech_stack": data.get("tech_stack") or {},
    }


# ---------------------------------------------------------------------------
# Build web_summary
# ---------------------------------------------------------------------------

_MAX_SUMMARY_CHARS = 3200  # ~800 tokens


def build_web_summary(page_data: dict[str, Any], url: str) -> str:
    """
    Build a structured, LLM-friendly summary of a single scraped page.
    Capped at ~800 tokens so it fits cleanly in RCA prompts.
    """
    lines: list[str] = []

    lines.append(f"Website: {url}")

    title = str(page_data.get("title") or "").strip()
    if title:
        lines.append(f"Title: {title}")

    desc = str(page_data.get("meta_description") or "").strip()
    if desc:
        lines.append(f"Description: {desc[:300]}")

    tech: dict[str, Any] = page_data.get("tech_stack") or {}
    detected: list[str] = tech.get("detected") or []
    if detected:
        lines.append(f"Tech stack: {', '.join(detected[:10])}")

    elements: list[dict[str, Any]] = page_data.get("elements") or []
    content_lines: list[str] = []
    for el in elements[:30]:
        if not isinstance(el, dict):
            continue
        t = str(el.get("type") or "").strip()
        c = str(el.get("content") or "").strip()
        if t and c:
            content_lines.append(f"- {t}: {c[:200]}")
        if len(content_lines) >= 15:
            break

    if content_lines:
        lines.append("Key content:")
        lines.extend(content_lines)

    summary = "\n".join(lines)
    return summary[:_MAX_SUMMARY_CHARS]


# ---------------------------------------------------------------------------
# Generate RCA questions
# ---------------------------------------------------------------------------

_RCA_SYSTEM_PROMPT = """\
You are an expert business diagnostician. Given a business's website summary \
and their stated goal, generate up to 3 concise, specific, layman-friendly \
diagnostic questions that will help identify the root cause of their challenge.

Rules:
- Maximum 3 questions.
- Each question must be answerable in 1-3 sentences by a non-technical business owner.
- Questions must be directly motivated by the website evidence and the user's goal.
- Do not ask generic questions. Make every question specific to what you can observe.
- Output ONLY a JSON array of question strings. Example: ["Q1", "Q2", "Q3"]
"""


async def generate_rca_questions(
    *,
    outcome: str,
    domain: str,
    task: str,
    web_summary: str,
    max_questions: int = 3,
) -> list[str]:
    """
    Call the LLM to generate up to max_questions RCA questions.
    Returns an empty list on any failure so the task stream is not blocked.
    """
    user_content = json.dumps({
        "outcome": outcome,
        "domain": domain,
        "task": task,
        "web_summary": web_summary,
    }, ensure_ascii=False)

    try:
        result = await _ai.complete(
            model="anthropic/claude-sonnet-4-6",
            messages=[
                {"role": "system", "content": _RCA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            max_tokens=512,
        )
        raw = str(result.get("message") or "").strip()
        questions = _parse_questions(raw, max_questions)
        return questions
    except Exception as exc:
        logger.warning("generate_rca_questions failed", error=str(exc))
        return []


def _parse_questions(raw: str, max_questions: int) -> list[str]:
    """Extract a JSON array of strings from LLM output robustly."""
    # Try direct parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(q) for q in parsed if str(q).strip()][:max_questions]
    except Exception:
        pass

    # Try fenced code block
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        try:
            parsed = json.loads(fence.group(1).strip())
            if isinstance(parsed, list):
                return [str(q) for q in parsed if str(q).strip()][:max_questions]
        except Exception:
            pass

    # Try extracting the first [...] array
    arr_match = re.search(r"\[[\s\S]*?\]", raw)
    if arr_match:
        try:
            parsed = json.loads(arr_match.group(0))
            if isinstance(parsed, list):
                return [str(q) for q in parsed if str(q).strip()][:max_questions]
        except Exception:
            pass

    return []


# ---------------------------------------------------------------------------
# Onboarding DB helpers
# ---------------------------------------------------------------------------

async def fetch_onboarding_context(session_id: str) -> dict[str, Any]:
    """Return outcome, domain, task, web_summary from the onboarding row."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT outcome, domain, task, web_summary FROM onboarding WHERE session_id = $1",
            session_id,
        )
    if not row:
        return {}
    return {
        "outcome": str(row["outcome"] or ""),
        "domain": str(row["domain"] or ""),
        "task": str(row["task"] or ""),
        "web_summary": str(row["web_summary"] or ""),
    }


async def update_onboarding_web_summary(session_id: str, web_summary: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE onboarding SET web_summary = $1, updated_at = NOW() WHERE session_id = $2",
            web_summary,
            session_id,
        )


async def update_onboarding_rca_questions(
    session_id: str,
    questions: list[str],
) -> None:
    """Store questions as [{question: str, answer: ""}] in rca_qa."""
    rca_qa = [{"question": q, "answer": None} for q in questions]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE onboarding SET rca_qa = $1::jsonb, updated_at = NOW() WHERE session_id = $2",
            json.dumps(rca_qa),
            session_id,
        )