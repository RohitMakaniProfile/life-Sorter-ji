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
You are a world-class business growth consultant doing a 3-minute intake call with a founder.
You have just looked at their website. You know exactly what they want to achieve.
Your job: ask the 3 sharpest questions that will unlock a personalised action plan for them.

━━━ YOUR CONTEXT ━━━
You will receive:
- GOAL = their outcome category (e.g. "Lead Generation") + their exact chosen task (e.g. "Generate cold outreach sequences")
- DOMAIN = the business category they selected (e.g. "B2B Sales", "SEO & Organic Visibility")
- WEBSITE EVIDENCE = what you scraped from their actual website (title, description, content, tech stack)

━━━ YOUR DIAGNOSTIC MISSION ━━━
Bridge the gap between:
  → What their website shows right now
  → What they need to achieve their specific TASK

Ask questions that reveal WHY they haven't achieved this yet.
Common root causes to probe (pick the ones most relevant given the website evidence):
  • Missing clarity: they don't know WHO to target or WHAT to offer
  • Missing proof: no testimonials, case studies, or trust signals visible on site
  • Missing traffic: no way for their target customer to find them
  • Missing conversion: site has traffic/leads but they don't convert
  • Missing process: they don't have a system for follow-up, outreach, or fulfillment
  • Missing tools: doing things manually that should be automated
  • Wrong positioning: messaging on site doesn't match their ideal buyer

━━━ WHAT MAKES A PERFECT QUESTION ━━━
✅ References a SPECIFIC signal from their website (their actual headline, their CTA, their tech stack, what's missing)
✅ Directly tied to THEIR task — not generic business advice
✅ Short: max 12 words. Sounds like a smart friend, not a consultant survey.
✅ Each option is a concrete realistic scenario for a founder in THEIR domain
✅ A non-technical business owner answers it in under 15 seconds without confusion

━━━ EXAMPLES: BAD vs GOOD ━━━

BAD: "What is your monthly marketing budget?"
GOOD (for a tutor with no testimonials trying to get leads): "Why aren't past students referring others to you?"

BAD: "Who is your target audience?"
GOOD (for a D2C brand with a weak CTA trying to boost sales): "What stops people from buying the first time they visit your site?"

BAD: "How long have you been in business?"
GOOD (for a SaaS with no pricing page trying to generate trials): "Why do visitors leave without signing up for a trial?"

━━━ OPTION RULES ━━━
- Exactly 4 options per question
- Options A, B, C = distinct, specific scenarios for a founder in THEIR domain (not generic)
- Option D = always "Something else / I'm not sure"
- Max 8 words per option. No full sentences. No vague filler.
- Options must be mutually exclusive — if someone picks A, they wouldn't also pick B

━━━ CRITICAL RULES ━━━
❌ NEVER ask: "What is your target audience?" / "What's your budget?" / "How long in business?" / "Describe your product"
❌ NEVER ask something already answered by the website evidence
❌ NEVER use corporate jargon — write like you're texting a founder
❌ NEVER ask about things unrelated to their chosen TASK
❌ ALL 3 questions must be about DIFFERENT root causes — no overlapping topics

━━━ OUTPUT FORMAT (STRICT) ━━━
Return ONLY a valid JSON array. No explanation. No preamble. No markdown. Just this:
[
  {
    "question": "Your short question here?",
    "options": ["Specific option A", "Specific option B", "Specific option C", "Something else / not sure"]
  },
  {
    "question": "Second question?",
    "options": ["Option A", "Option B", "Option C", "Something else / not sure"]
  },
  {
    "question": "Third question?",
    "options": ["Option A", "Option B", "Option C", "Something else / not sure"]
  }
]
"""


async def generate_rca_questions(
    *,
    outcome: str,
    domain: str,
    task: str,
    web_summary: str,
    max_questions: int = 3,
) -> list[dict[str, Any]]:
    """
    Call the LLM to generate up to max_questions RCA questions with options.
    Returns an empty list on any failure so the task stream is not blocked.
    """
    user_content = (
        f"GOAL CATEGORY: {outcome}\n"
        f"THEIR EXACT TASK: {task}\n"
        f"DOMAIN: {domain}\n\n"
        f"━━━ WEBSITE EVIDENCE (what I scraped from their site) ━━━\n"
        f"{web_summary}\n\n"
        f"━━━ YOUR JOB ━━━\n"
        f"Generate exactly {max_questions} diagnostic questions.\n"
        f"Each question must:\n"
        f"1. Reference something specific from the website evidence above\n"
        f"2. Target a different root cause blocking their task: '{task}'\n"
        f"3. Have 4 options — 3 specific scenarios + 'Something else / not sure'\n\n"
        f"Focus on: what is the #1 thing stopping them from achieving '{task}' right now?"
    )

    try:
        result = await _ai.complete(
            model="anthropic/claude-sonnet-4-6",
            messages=[
                {"role": "system", "content": _RCA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        raw = str(result.get("message") or "").strip()
        questions = _parse_questions(raw, max_questions)
        logger.info("generate_rca_questions success", count=len(questions), task=task)
        return questions
    except Exception as exc:
        logger.warning("generate_rca_questions failed", error=str(exc))
        return []


def _parse_questions(raw: str, max_questions: int) -> list[dict[str, Any]]:
    """Extract a JSON array of question objects from LLM output robustly."""
    def _normalise(parsed: Any) -> list[dict[str, Any]]:
        if not isinstance(parsed, list):
            return []
        out = []
        for item in parsed:
            if isinstance(item, str) and item.strip():
                # Old format fallback: plain string question
                out.append({"question": item.strip(), "options": []})
            elif isinstance(item, dict) and item.get("question"):
                q = str(item["question"]).strip()
                opts = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
                out.append({"question": q, "options": opts})
        return out[:max_questions]

    # Try direct parse
    try:
        parsed = json.loads(raw)
        result = _normalise(parsed)
        if result:
            return result
    except Exception:
        pass

    # Try fenced code block
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        try:
            parsed = json.loads(fence.group(1).strip())
            result = _normalise(parsed)
            if result:
                return result
        except Exception:
            pass

    # Try extracting the first [...] array
    arr_match = re.search(r"\[[\s\S]*\]", raw)
    if arr_match:
        try:
            parsed = json.loads(arr_match.group(0))
            result = _normalise(parsed)
            if result:
                return result
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
    questions: list[dict[str, Any]],
) -> None:
    """Store questions as [{question, options, answer}] in rca_qa."""
    rca_qa = [
        {
            "question": q.get("question", ""),
            "options": q.get("options") or [],
            "answer": None,
        }
        for q in questions
        if q.get("question")
    ]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE onboarding SET rca_qa = $1::jsonb, updated_at = NOW() WHERE session_id = $2",
            json.dumps(rca_qa),
            session_id,
        )