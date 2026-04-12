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

from app.db import get_pool
from app.services.ai_helper import _extract_json_value, ai_helper as _ai
from app.skills.service import run_skill
from app.repositories import onboarding_repository as onboarding_repo
from app.services.token_usage_service import (
    log_onboarding_token_usage,
    STAGE_RCA_QUESTIONS,
    STAGE_BUSINESS_PROFILE,
)

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
    from app.repositories import skill_calls_repository as skill_repo
    pool = get_pool()
    run_id = f"{skill_id}-onboarding-{int(time.time() * 1000)}"
    async with pool.acquire() as conn:
        return await skill_repo.insert_onboarding_skill_call(
            conn,
            onboarding_session_id=onboarding_session_id,
            skill_id=skill_id,
            run_id=run_id,
            input_json=json.dumps(input),
        )


async def finish_onboarding_skill_call(
    skill_call_id: int,
    *,
    output: Any,
    error: str | None = None,
    started_at_ms: float,
) -> None:
    """Mark a skill_call row as done (or error) and store output."""
    from app.repositories import skill_calls_repository as skill_repo
    state = "error" if error else "done"
    duration_ms = int((time.time() - started_at_ms) * 1000)
    pool = get_pool()
    async with pool.acquire() as conn:
        await skill_repo.finish_onboarding_skill_call(
            conn,
            skill_call_id=skill_call_id,
            state=state,
            output_json=json.dumps(output if output is not None else []),
            error=error,
            duration_ms=duration_ms,
        )


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
            m = meta.get("meta")
            url_hint = ""
            if isinstance(m, dict):
                url_hint = str(m.get("url") or "")
                url_event = str(m.get("event") or "")
                # Forward individual URL events so the frontend can show discovered/done URLs
                if url_event in ("discovered", "page_data") and url_hint:
                    await on_progress({"url_event": url_event, "url": url_hint})

            label = str(meta.get("message") or meta.get("label") or "Scraping")
            await on_progress(
                {
                    "stage": "scraping",
                    "label": label,
                    "current_page": url_hint,
                }
            )

    result = await run_skill(
        "scrape-playwright",
        message=f"Scrape this website: {url}",
        args={"url": url, "maxPages": 5, "parallel": True, "maxParallelPages": 5},
        on_progress=_skill_progress,
    )


    if result.status != "ok":
        raise RuntimeError(str(result.error or "scrape-playwright failed"))

    data = result.data or {}
    if not isinstance(data, dict):
        data = {}

    pages: list[dict[str, Any]] = [p for p in (data.get("pages") or []) if isinstance(p, dict)]
    if pages:
        # Merge elements from all pages into the first page's record so
        # build_web_summary gets richer content without losing homepage metadata.
        merged = dict(pages[0])
        if len(pages) > 1:
            all_elements: list[dict] = list(pages[0].get("elements") or [])
            for p in pages[1:]:
                all_elements.extend(p.get("elements") or [])
            merged["elements"] = all_elements
        return merged, str(result.text or "").strip()

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
- Return ONLY valid JSON, no explanations or text before/after
- Format: {"questions":[{"question":"...","options":["...","...","..."]}]}
- Generate exactly 3 questions
- Each question must be concrete and diagnostic, not generic
- Each question must include 3-5 short multiple-choice options
- Use the business profile when available to tailor the questions
- Avoid repeating what is already obvious from the website

IMPORTANT: Output ONLY the JSON object. Do NOT use <thinking> tags. Do not include any reasoning, explanations, or markdown formatting. Your entire response must be valid JSON starting with { and ending with }.
"""


async def _get_business_profile_prompt() -> str:
    """Fetch business-profile prompt from prompts repository (Redis cached, DB fallback)."""
    from app.services.prompts_service import get_prompt
    return await get_prompt("business-profile", default=_BUSINESS_PROFILE_PROMPT_DEFAULT)


async def _get_rca_questions_prompt() -> str:
    """Fetch RCA question prompt from prompts repository (Redis cached, DB fallback)."""
    from app.services.prompts_service import get_prompt
    return await get_prompt("rca-questions", default=_RCA_QUESTIONS_PROMPT_DEFAULT)


async def generate_business_profile(*, web_summary: str, onboarding_id: str = "") -> str:
    """Generate a markdown/text business profile from the website summary."""
    summary = str(web_summary or "").strip()
    if not summary:
        return ""

    model_name = "anthropic/claude-sonnet-4-6"
    input_tokens = 0
    output_tokens = 0

    try:
        system_prompt = await _get_business_profile_prompt()
        result = await _ai.complete(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": summary},
            ],
            temperature=0.3,
            max_tokens=700,
        )
        profile = str(result.get("message") or "").strip()
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)

        logger.info("generate_business_profile success", chars=len(profile), input_tokens=input_tokens, output_tokens=output_tokens)

        # Log token usage
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_BUSINESS_PROFILE,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
            )

        return profile
    except Exception as exc:
        logger.warning("generate_business_profile failed", error=str(exc))
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_BUSINESS_PROFILE,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=False,
                error_msg=str(exc),
            )
        return ""


async def generate_rca_questions(
    *,
    onboarding_id: str,
    outcome: str,
    domain: str,
    task: str,
    web_summary: str,
    scale_answers: dict[str, Any] | None,
    business_profile: str = "",
    max_questions: int = 3,
) -> list[dict[str, Any]]:
    """Generate RCA questions using onboarding context, including business_profile.

    Logs token usage to token_usage table linked to onboarding_id.
    """
    raw = ""
    input_tokens = 0
    output_tokens = 0
    model_name = "anthropic/claude-sonnet-4-6"

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
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            temperature=0.3,
            max_tokens=4000,
        )
        raw = str(result.get("message") or "").strip()
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        finish_reason = str(result.get("finish_reason") or "")

        if finish_reason == "length":
            logger.warning(
                "generate_rca_questions: model output truncated at max_tokens — "
                "increase max_tokens or the model ran out of budget before finishing JSON",
                onboarding_id=onboarding_id,
                output_tokens=output_tokens,
                raw_preview=raw[:300],
            )

        logger.info(
            "generate_rca_questions raw_output",
            onboarding_id=onboarding_id,
            finish_reason=finish_reason,
            raw_output=raw[:4000],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

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

        # Log successful token usage
        await log_onboarding_token_usage(
            onboarding_id=onboarding_id,
            stage=STAGE_RCA_QUESTIONS,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=True,
        )
        return out
    except Exception as exc:
        logger.error(
            "generate_rca_questions failed",
            onboarding_id=onboarding_id,
            error=str(exc),
            raw_output=raw if raw else "(empty)",
            raw_length=len(raw) if raw else 0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        # Log failed token usage (still consumed tokens)
        await log_onboarding_token_usage(
            onboarding_id=onboarding_id,
            stage=STAGE_RCA_QUESTIONS,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=False,
            error_msg=str(exc),
            raw_output=raw,
        )
        raise RuntimeError(f"RCA question generation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Onboarding DB helpers
# ---------------------------------------------------------------------------

async def fetch_onboarding_context(onboarding_id: str) -> dict[str, Any]:
    """Return onboarding context fields from the onboarding row."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_crawl_context(conn, onboarding_id)
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
    from app.repositories import onboarding_repository as onboarding_repo
    pool = get_pool()
    async with pool.acquire() as conn:
        await onboarding_repo.update_crawl_outputs(conn, onboarding_id, web_summary, business_profile)