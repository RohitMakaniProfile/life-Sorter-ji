"""
Onboarding crawl service — smart 5-page Playwright scrape + web summary + business profile.

Responsibilities:
  1. Run scrape-playwright skill (up to 5 pages, parallel) and record in skill_calls table.
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
# Single-page Playwright scrape (with 5-page parallel crawl)
# ---------------------------------------------------------------------------

async def run_playwright_single_page(
    *,
    url: str,
    on_progress: ProgressCb | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Run scrape-playwright via the shared skills service with maxPages=5 (parallel).
    Returns:
      - page_data: merged page payload (all pages merged into first)
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
            # Merge body_text from all pages for JS SPA fallback
            all_body_parts = []
            for p in pages:
                bt = str(p.get("body_text") or "").strip()
                if bt:
                    all_body_parts.append(bt)
            if all_body_parts:
                merged["body_text"] = "\n\n".join(all_body_parts)
        return merged, str(result.text or "").strip()

    # Fallback: build a minimal record from whatever the scraper returned
    page_data = {
        "url": url,
        "title": str(data.get("title") or ""),
        "meta_description": str(data.get("meta_description") or ""),
        "elements": data.get("elements") or [],
        "body_text": str(data.get("body_text") or ""),
        "tech_stack": data.get("tech_stack") or {},
    }
    return page_data, str(result.text or "").strip()


# ---------------------------------------------------------------------------
# Build web_summary
# ---------------------------------------------------------------------------

_MAX_SUMMARY_CHARS = 8000  # ~2000 tokens (multi-page, richer content)


def build_web_summary(page_data: dict[str, Any], url: str) -> str:
    """
    Build a structured, LLM-friendly summary of scraped pages.
    Falls back to body_text when elements array is empty (JS SPAs).
    Capped at ~2000 tokens so it fits cleanly in prompts.
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
    for el in elements[:60]:
        if not isinstance(el, dict):
            continue
        t = str(el.get("type") or "").strip()
        c = str(el.get("content") or "").strip()
        if t and c:
            content_lines.append(f"- {t}: {c[:200]}")
        if len(content_lines) >= 30:
            break

    if content_lines:
        lines.append("Key content:")
        lines.extend(content_lines)
    else:
        # JS SPA fallback: use body_text when elements extraction failed
        body_text = str(page_data.get("body_text") or "").strip()
        if body_text:
            lines.append("Page text (body_text fallback):")
            lines.append(body_text[:2000])

    summary = "\n".join(lines)
    return summary[:_MAX_SUMMARY_CHARS]


# ---------------------------------------------------------------------------
# Pre-compute helpers for RCA (derive acquisition channel)
# ---------------------------------------------------------------------------

def _derive_acquisition_channel(scale_answers: dict[str, Any]) -> str:
    """Decode buyer_behavior into a clear acquisition channel label."""
    buyer = str(scale_answers.get("buyer_behavior") or "").lower()
    if any(k in buyer for k in ("search", "google", "seo", "ai tool")):
        return "Inbound/SEO — website IS the funnel"
    if any(k in buyer for k in ("referral", "word", "peer", "colleague", "recommendation")):
        return "Referral/Word-of-mouth — website is a brochure, NOT the funnel"
    if any(k in buyer for k in ("don't know", "unaware", "zero awareness", "don't know this", "category")):
        return "Zero Awareness — buyers don't know the category exists yet"
    if any(k in buyer for k in ("compare", "competitor", "review", "comparison")):
        return "Comparison/Review-driven"
    if any(k in buyer for k in ("marketplace", "platform", "amazon", "flipkart", "listing")):
        return "Marketplace"
    if any(k in buyer for k in ("sales rep", "outbound", "cold", "sales-led", "sales team")):
        return "Outbound/Sales-led"
    return f"Direct — {buyer[:120]}" if buyer else "Unknown"


def _extract_website_signals(web_summary: str) -> str:
    """Extract key signals from web_summary for the RCA prompt."""
    if not web_summary:
        return "No website data available"
    lines = web_summary.split("\n")
    signals = []
    for line in lines[:20]:
        line = line.strip()
        if line and not line.startswith("Website:"):
            signals.append(line)
        if len(signals) >= 8:
            break
    return "\n".join(signals) if signals else "Minimal data scraped"


def _find_contradictions(scale_answers: dict[str, Any], web_summary: str) -> str:
    """
    Compare what the founder claims (scale_answers) vs. what the website shows.
    Returns a short contradiction string, or 'None detected'.
    """
    assets = str(scale_answers.get("existing_assets") or "").lower()
    summary_low = web_summary.lower()
    contradictions = []

    if "testimonial" in assets and "testimonial" not in summary_low:
        contradictions.append("Claims testimonials but none visible on website")
    if "case stud" in assets and "case stud" not in summary_low:
        contradictions.append("Claims case studies but none found on website")
    if "pricing" in assets and "pricing" not in summary_low and "price" not in summary_low:
        contradictions.append("Claims pricing page but none detected in crawl")
    if "blog" in assets and "blog" not in summary_low:
        contradictions.append("Claims blog content but none found on website")

    return "; ".join(contradictions) if contradictions else "None detected"


# ---------------------------------------------------------------------------
# Generate business profile
# ---------------------------------------------------------------------------

# Fallback prompt if not found in database
_BUSINESS_PROFILE_PROMPT_DEFAULT = """\
You are a Business Profile Extractor.

Given landing page content, infer a concise business profile using evidence from the text.
Avoid speculation — base inferences only on clear signals (copy, pricing, product types, CTAs,
geography hints, language, categories, etc.).

Output format (strict)
Return a compact table with two columns: Attribute and Inference

Include only these attributes:
  Market (category + positioning)
  Operation Type (e.g., B2C, B2B, Hybrid + primary)
  Region (country/geo signals with brief justification)
  Scope (local, regional, global, or local-to-global)
  Business Model (1-line explanation of how it makes money and who pays)

Rules:
  Keep each inference 1 line max
  Add short evidence hints in parentheses when useful
  Do not invent missing data; if unclear, say "Unclear (insufficient evidence)"
  Prefer clarity over completeness
"""

# ---------------------------------------------------------------------------
# Generate RCA questions — v2.0 prompt
# ---------------------------------------------------------------------------

_RCA_QUESTIONS_PROMPT_DEFAULT = """\
You are a world-class business growth diagnostician. You have done thousands of founder intakes.
In 3 questions, you will pinpoint exactly WHY this founder hasn't hit their goal yet.

The founder reads your question and thinks: "They know exactly what I'm struggling with."

━━━ WHAT YOU RECEIVE ━━━
- GOAL: outcome + exact task they want to accomplish
- DOMAIN: their industry/business category
- ACQUISITION_CHANNEL: pre-decoded — how buyers actually find them
- BUYING_PROCESS: how customers buy (self-serve / demo / sales-led / etc.)
- SALES_CYCLE: time from discovery to paying
- REVENUE_MODEL: how they make money
- EXISTING_ASSETS: marketing assets they say they have
- CONTRADICTIONS: mismatches between what they claim vs. what their website shows
- WEBSITE_SIGNALS: pre-extracted facts — what exists and what is missing on homepage
- WEBSITE_EVIDENCE: full scraped homepage data
- BUSINESS_PROFILE: AI-generated business summary

━━━ STEP 1 — SILENT DIAGNOSIS (inside <thinking> tags, be brief) ━━━

A. ACQUISITION_CHANNEL changes everything (trust this field — it is pre-decoded. Ignore BUYER_BEHAVIOR raw text, use ACQUISITION_CHANNEL only):
   • Inbound/SEO → website IS the funnel. Ask about conversion, content, CTAs.
   • Referral/Word-of-mouth → website is a brochure. Ask about referral activation, follow-up, client conversations. NEVER ask about CTAs or traffic.
   • Outbound/Sales-led → pipeline and outreach are the levers.
   • Zero Awareness → education and channel building is the problem.
   • Marketplace → listing quality, reviews, platform algorithm.
   • Comparison/Review-driven → positioning vs competitors and trust signals.

B. CONTRADICTIONS are the sharpest signal. If they claim testimonials but website shows none — they have proof they're not using. Build a question from this if it exists.

C. CROSS-REFERENCE EXISTING_ASSETS + WEBSITE_SIGNALS + BUYING_PROCESS:
   • Has assets but website doesn't show them → hidden proof, ask why
   • Nothing + long sales cycle → broken pipeline/nurture
   • Self-serve + no pricing → checkout friction
   • Demo-first + no CTA → weak entry point
   • No traffic mechanism + any channel → zero discovery

D. PICK TOP 3 FAILURE MODES:
   [A] WRONG TARGET — messaging attracts wrong or no specific buyer
   [B] NO PROOF — no visible results/testimonials for their buyer type
   [C] WEAK ENTRY POINT — CTA too high-commitment for their sales motion
   [D] NO TRAFFIC ENGINE — no mechanism for buyers to discover them
   [E] BROKEN PIPELINE — leads come in but ghost during follow-up
   [F] COMMODITY TRAP — looks identical to competitors, no differentiation
   [G] CHECKOUT FRICTION — buyers can't self-qualify or easily purchase
   [H] CHANNEL MISMATCH — using website tactics but buyers come via referral/outbound
   [I] ZERO AWARENESS — buyers don't know the category or solution exists
   [J] CHURN/RETENTION — acquires customers but loses them before ROI
   [K] FULFILLMENT BOTTLENECK — selling works but delivery is breaking operations
   [L] HIDDEN PROOF — has results/assets but isn't using them publicly

━━━ STEP 2 — WRITE 3 QUESTIONS ━━━

━━ QUESTION LENGTH — THIS IS CRITICAL ━━
Questions must be SHORT. Max 6–8 words. Like a blunt friend texting you, not a consultant survey.
The question is just the hook. The OPTIONS carry the diagnostic depth.

WRONG (too long, formal, survey-like):
  "You have no case studies visible on your website — why haven't your past clients become proof of your work?"

RIGHT (short, punchy, human):
  "Why aren't past clients vouching for you?"
  "No testimonials — what's actually blocking you?"
  "Where do interested leads go cold?"
  "Why isn't your pricing on the site?"
  "What's stopping referrals from happening?"

━━ ANCHOR RULE ━━
Each question must be triggered by a specific signal from WEBSITE_SIGNALS, CONTRADICTIONS, EXISTING_ASSETS, BUYING_PROCESS, or SALES_CYCLE.
That signal is the REASON this question exists for THIS founder — not for every founder.
Inversion check: remove the context from the question. If the question still makes sense for any random business → it is generic, rewrite it.
IMPORTANT: The anchor signal must appear IN the question text itself — not hidden in the options.
WRONG: "Why aren't past clients vouching for you?" → generic, works for any business
RIGHT: "No testimonials on your site — why haven't clients reviewed you?" → signal is IN the question

━━ NO OVERLAP ━━
All 3 questions must address DIFFERENT failure modes. Zero thematic overlap.

━━ ACTIONABILITY ━━
Each answer must change what you'd recommend. If every answer leads to the same advice → useless question.

━━━ OPTIONS FORMAT ━━━
Exactly 4 options. Max 8 words each. Fragments, not full sentences.

A, B, C: Brutally specific to THIS founder's domain and situation. A founder reading them thinks "that's literally my situation" for one of them.

Option D: An internal/operational blocker — NEVER "Something else / not sure".
Examples:
  • "Know I need it — just keep avoiding it"
  • "No one on the team owns this"
  • "Too buried in delivery to work on this"
  • "Haven't figured out the right approach yet"

━━━ QUALITY BAR ━━━
FAILING:
  Q: "What stops leads from converting on your site?"
  Options: Pricing unclear, No trust, Bad CTA, Something else
  → Long question. Vague options. Generic Option D. Fails inversion test.

PASSING:
  Q: "No testimonials on your site — why haven't clients reviewed you?"
  A. Results exist — I just never asked for a review
  B. Too early — results aren't strong enough yet
  C. Different niche each time — hard to package
  D. Know I need it — just keep avoiding it
  → Short. Brutal. Anchored (no testimonials signal is IN the question). Options are domain-specific. Option D is real.

━━━ HARD CONSTRAINTS ━━━
❌ No questions about: target audience, budget, timeline, years in business, team size
❌ No questions that inputs already answer
❌ No jargon: leverage, optimize, synergy, scale, streamline, robust
❌ No generic options that fit any business
❌ If Referral or Outbound channel → never ask about website CTAs or traffic

━━━ OUTPUT ━━━
<thinking> block first (brief — just CH, CONTRA, FM, Q1/Q2/Q3 draft in one line each).
Then immediately the JSON array. No markdown fences. No extra text.

<thinking>
CH:[one word from ACQUISITION_CHANNEL]|CONTRA:[signal or none]|FM:[X],[Y],[Z]
Q1:[FM letter]|"exact anchor signal text"|"question draft ≤8 words"
Q2:[FM letter]|"exact anchor signal text"|"question draft ≤8 words"
Q3:[FM letter]|"exact anchor signal text"|"question draft ≤8 words"
</thinking>
[
  {
    "question": "Short punchy question?",
    "options": ["Specific A", "Specific B", "Specific C", "Operational blocker D"]
  },
  {
    "question": "Short punchy question?",
    "options": ["Specific A", "Specific B", "Specific C", "Operational blocker D"]
  },
  {
    "question": "Short punchy question?",
    "options": ["Specific A", "Specific B", "Specific C", "Operational blocker D"]
  }
]
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
    """Generate RCA questions using onboarding context, including pre-computed fields."""
    raw = ""
    sa = scale_answers or {}
    try:
        system_prompt = await _get_rca_questions_prompt()

        # Pre-compute fields
        acquisition_channel = _derive_acquisition_channel(sa)
        website_signals = _extract_website_signals(web_summary)
        contradictions = _find_contradictions(sa, web_summary)

        # Build structured user message that matches the new prompt's "WHAT YOU RECEIVE" fields
        user_message = "\n".join([
            f"GOAL: {str(outcome or '').strip()} — {str(task or '').strip()}",
            f"DOMAIN: {str(domain or '').strip()}",
            f"ACQUISITION_CHANNEL: {acquisition_channel}",
            f"BUYING_PROCESS: {str(sa.get('buying_process') or 'Not specified')}",
            f"SALES_CYCLE: {str(sa.get('sales_cycle') or 'Not specified')}",
            f"REVENUE_MODEL: {str(sa.get('revenue_model') or 'Not specified')}",
            f"EXISTING_ASSETS: {str(sa.get('existing_assets') or 'Not specified')}",
            f"CONTRADICTIONS: {contradictions}",
            f"WEBSITE_SIGNALS:\n{website_signals}",
            f"WEBSITE_EVIDENCE:\n{str(web_summary or '').strip()[:3000]}",
            f"BUSINESS_PROFILE:\n{str(business_profile or '').strip()[:1000]}",
            f"max_questions: {int(max_questions or 3)}",
        ])

        result = await _ai.complete(
            model="anthropic/claude-sonnet-4-6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=2500,
        )
        raw = str(result.get("message") or "").strip()
        logger.info("generate_rca_questions raw_output", raw_output=raw[:4000])

        # Strip <thinking> block before parsing JSON
        json_str = raw
        if "<thinking>" in json_str and "</thinking>" in json_str:
            json_str = json_str[json_str.index("</thinking>") + len("</thinking>"):].strip()

        parsed = json.loads(_extract_json_value(json_str)) if json_str else {}
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
    from app.repositories import onboarding_repository as onboarding_repo
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
