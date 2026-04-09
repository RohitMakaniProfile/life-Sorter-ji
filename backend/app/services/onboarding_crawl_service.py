"""
Onboarding crawl service — single-page Playwright scrape + web summary + business profile.

Responsibilities:
  1. Run scrape-playwright skill (maxPages=1) and record in skill_calls table.
  2. Build a compact web_summary string from the page data.
  3. Generate a business_profile markdown summary from the web_summary.
  4. Persist web_summary and business_profile back to the onboarding row.
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

import structlog
from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.services.ai_helper import _extract_json_value, ai_helper as _ai
from app.skills.service import run_skill
from app.sql_builder import build_query

logger = structlog.get_logger()
skill_calls_t = Table("skill_calls")
onboarding_t = Table("onboarding")

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
        insert_skill_call_sql = """
        INSERT INTO skill_calls
            (onboarding_session_id, skill_id, run_id, input, state)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        RETURNING id
        """
        # Keep minimal raw SQL: INSERT ... RETURNING with jsonb cast is Postgres-specific.
        row_id = await conn.fetchval(
            insert_skill_call_sql,
            onboarding_session_id,
            skill_id,
            f"{skill_id}-onboarding-{int(time.time() * 1000)}",
            json.dumps(input),
            "running",
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
        finish_skill_q = build_query(
            PostgreSQLQuery.update(skill_calls_t)
            .set(skill_calls_t.state, Parameter("%s"))
            .set(skill_calls_t.output, Parameter("%s"))
            .set(skill_calls_t.error, Parameter("%s"))
            .set(skill_calls_t.ended_at, fn.Now())
            .set(skill_calls_t.duration_ms, Parameter("%s"))
            .where(skill_calls_t.id == Parameter("%s")),
            [state, json.dumps(output if output is not None else []), error, duration_ms, skill_call_id],
        )
        await conn.execute(finish_skill_q.sql, *finish_skill_q.params)


# ---------------------------------------------------------------------------
# Single-page Playwright scrape
# ---------------------------------------------------------------------------

async def run_playwright_single_page(
    *,
    url: str,
    on_progress: ProgressCb | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Run scrape-playwright via the shared skills service with maxPages=1.
    Returns:
      - page_data: first page payload (or minimal fallback dict)
      - web_summary_text: summary text returned by skill post-processing
    """
    async def _skill_progress(meta: dict[str, Any]) -> None:
        if not on_progress:
            return
        if not isinstance(meta, dict):
            return
        if meta.get("stage") == "running":
            label = str(meta.get("message") or meta.get("label") or "Scraping")
            url_hint = ""
            m = meta.get("meta")
            if isinstance(m, dict):
                url_hint = str(m.get("url") or "")
            await on_progress(
                {
                    "stage": "scraping",
                    "label": label,
                    "current_page": url_hint,
                }
            )

    result = await run_skill(
        "scrape-playwright",
        message=f"Scrape this website homepage: {url}",
        args={"url": url, "maxPages": 1},
        on_progress=_skill_progress,
    )


    if result.status != "ok":
        raise RuntimeError(str(result.error or "scrape-playwright failed"))

    data = result.data or {}
    if not isinstance(data, dict):
        data = {}

    pages: list[dict[str, Any]] = data.get("pages") or []
    if pages and isinstance(pages[0], dict):
        return pages[0], str(result.text or "").strip()

    # Fallback: build a minimal record from whatever the scraper returned
    page_data = {
        "url": url,
        "title": str(data.get("title") or ""),
        "meta_description": str(data.get("meta_description") or ""),
        "elements": data.get("elements") or [],
        "tech_stack": data.get("tech_stack") or {},
    }
    return page_data, str(result.text or "").strip()


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
# Generate business profile
# ---------------------------------------------------------------------------

# Fallback prompt if not found in database
_BUSINESS_PROFILE_PROMPT_DEFAULT = """\
You are a business analyst. Read the provided website summary and produce a concise business profile in markdown.

Output only markdown. Keep it grounded in the provided evidence. If something is uncertain, say that clearly.

Use short sections:
- What They Do
- Target Customer
- Offer / Monetization
- Signals From Website
- Gaps / Unknowns
"""

_RCA_QUESTIONS_PROMPT_DEFAULT = """\
You are generating exactly 3 diagnostic RCA questions for a business onboarding flow.

Use all available context:
- business outcome
- business domain
- business task
- scale answers
- website summary
- business profile

Requirements:
- Return only valid JSON
- Format: {"questions":[{"question":"...","options":["...","...","..."]}]}
- Generate exactly 3 questions
- Each question must be concrete and diagnostic, not generic
- Each question must include 3-5 short multiple-choice options
- Use the business profile when available to tailor the questions
- Avoid repeating what is already obvious from the website
"""


async def _get_business_profile_prompt() -> str:
    """Fetch business-profile prompt from prompts repository (Redis cached, DB fallback)."""
    from app.services.prompts_service import get_prompt
    return await get_prompt("business-profile", default=_BUSINESS_PROFILE_PROMPT_DEFAULT)


async def _get_rca_questions_prompt() -> str:
    """Fetch RCA question prompt from prompts repository (Redis cached, DB fallback)."""
    from app.services.prompts_service import get_prompt
    return await get_prompt("rca-questions", default=_RCA_QUESTIONS_PROMPT_DEFAULT)


async def generate_business_profile(*, web_summary: str) -> str:
    """Generate a markdown/text business profile from the website summary."""
    summary = str(web_summary or "").strip()
    if not summary:
        return ""
    try:
        system_prompt = await _get_business_profile_prompt()
        result = await _ai.complete(
            model="anthropic/claude-sonnet-4-6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": summary},
            ],
            temperature=0.3,
            max_tokens=700,
        )
        profile = str(result.get("message") or "").strip()
        logger.info("generate_business_profile success", chars=len(profile))
        return profile
    except Exception as exc:
        logger.warning("generate_business_profile failed", error=str(exc))
        return ""


async def generate_rca_questions(
    *,
    outcome: str,
    domain: str,
    task: str,
    web_summary: str,
    scale_answers: dict[str, Any] | None,
    business_profile: str = "",
    max_questions: int = 3,
) -> list[dict[str, Any]]:
    """Generate RCA questions using onboarding context, including business_profile."""
    raw = ""
    try:
        system_prompt = await _get_rca_questions_prompt()
        user_payload = {
            "outcome": str(outcome or "").strip(),
            "domain": str(domain or "").strip(),
            "task": str(task or "").strip(),
            "scale_answers": scale_answers or {},
            "web_summary": str(web_summary or "").strip(),
            "business_profile": str(business_profile or "").strip(),
            "max_questions": int(max_questions or 3),
        }
        result = await _ai.complete(
            model="anthropic/claude-sonnet-4-6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            temperature=0.3,
            max_tokens=900,
        )
        raw = str(result.get("message") or "").strip()
        logger.info("generate_rca_questions raw_output", raw_output=raw[:4000])
        parsed = json.loads(_extract_json_value(raw)) if raw else {}
        if isinstance(parsed, dict):
            items = parsed.get("questions")
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = None
        if not isinstance(items, list):
            raise ValueError("RCA prompt response did not contain a questions list")
        out: list[dict[str, Any]] = []
        for item in items[: max(1, int(max_questions or 3))]:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            options = item.get("options") or []
            if not question:
                continue
            out.append(
                {
                    "question": question,
                    "options": [str(opt).strip() for opt in options if str(opt).strip()][:5],
                }
            )
        if not out:
            raise ValueError("RCA prompt response produced zero usable questions")
        return out
    except Exception as exc:
        logger.warning("generate_rca_questions failed", error=str(exc), raw_preview=raw[:400])
        raise RuntimeError(f"RCA question generation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Onboarding DB helpers
# ---------------------------------------------------------------------------

async def fetch_onboarding_context(onboarding_id: str) -> dict[str, Any]:
    """Return onboarding context fields from the onboarding row."""
    pool = get_pool()
    async with pool.acquire() as conn:
        fetch_context_q = build_query(
            PostgreSQLQuery.from_(onboarding_t)
            .select(
                onboarding_t.outcome,
                onboarding_t.domain,
                onboarding_t.task,
                onboarding_t.scale_answers,
                onboarding_t.web_summary,
                onboarding_t.business_profile,
            )
            .where(onboarding_t.id == Parameter("%s")),
            [onboarding_id],
        )
        row = await conn.fetchrow(fetch_context_q.sql, *fetch_context_q.params)
    if not row:
        return {}
    scale_answers_raw = row["scale_answers"]
    if isinstance(scale_answers_raw, str):
        try:
            parsed = json.loads(scale_answers_raw)
            scale_answers = parsed if isinstance(parsed, dict) else {}
        except Exception:
            scale_answers = {}
    else:
        scale_answers = scale_answers_raw if isinstance(scale_answers_raw, dict) else {}
    return {
        "outcome": str(row["outcome"] or ""),
        "domain": str(row["domain"] or ""),
        "task": str(row["task"] or ""),
        "scale_answers": scale_answers,
        "web_summary": str(row["web_summary"] or ""),
        "business_profile": str(row["business_profile"] or ""),
    }


async def update_onboarding_crawl_outputs(
    onboarding_id: str,
    *,
    web_summary: str,
    business_profile: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        update_outputs_q = build_query(
            PostgreSQLQuery.update(onboarding_t)
            .set(onboarding_t.web_summary, Parameter("%s"))
            .set(onboarding_t.business_profile, Parameter("%s"))
            .set(onboarding_t.updated_at, fn.Now())
            .where(onboarding_t.id == Parameter("%s")),
            [web_summary, business_profile, onboarding_id],
        )
        await conn.execute(update_outputs_q.sql, *update_outputs_q.params)
