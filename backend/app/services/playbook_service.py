"""
═══════════════════════════════════════════════════════════════
PLAYBOOK SERVICE — Onboarding playbook generation
═══════════════════════════════════════════════════════════════
Single-prompt streaming flow: one LLM call produces context_brief,
website_audit, and playbook sections split by section delimiters.
LLM calls go through OpenRouter (see config for model ids).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.services.ai_helper import ai_helper as _ai
from app.services.token_usage_service import log_onboarding_token_usage, STAGE_PLAYBOOK_STREAM

logger = structlog.get_logger()

# ══════════════════════════════════════════════════════════════
#  TOON-STYLE COMPACT SERIALISATION HELPERS
# ══════════════════════════════════════════════════════════════

_SEP = "|"


def _tv(value: Any, sep: str = _SEP) -> str:
    if value is None:
        return "-"
    s = str(value).replace("\n", " ").replace("\r", "").strip()
    return s.replace(sep, ";") if sep in s else s


def _toon_table(label: str, headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header_str = _SEP.join(headers)
    row_lines = [_SEP.join(_tv(cell) for cell in row) for row in rows]
    return f"{label}[{len(rows)}]{{{header_str}}}:\n" + "\n".join(row_lines)


def _toon_inline(label: str, pairs: list[tuple[str, Any]]) -> str:
    parts = [f"{k}:{_tv(v)}" for k, v in pairs if v]
    return f"{label}: " + " | ".join(parts) if parts else ""


def build_tools_toon(all_tools: list[dict[str, Any]]) -> str:
    """Convert a list of tool dicts into a TOON tabular block for the playbook prompt."""
    if not all_tools:
        return ""
    seen: set[str] = set()
    rows: list[list[Any]] = []
    for tool in all_tools:
        name = tool.get("name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        free = tool.get("free")
        price = "Free" if free is True else ("Paid" if free is False else "?")
        rows.append([
            name, tool.get("category", ""), price,
            tool.get("description", ""), tool.get("why_recommended", ""),
            tool.get("issue_solved", ""), tool.get("ease_of_use", ""),
        ])
    return _toon_table("TOOLS", ["name", "type", "price", "desc", "why", "solves", "ease"], rows)


# ══════════════════════════════════════════════════════════════
#  BUILD USER INPUT CONTEXT
# ══════════════════════════════════════════════════════════════

def _build_playbook_input(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: str | dict[str, Any],
    scale_answers: dict[str, Any],
    gap_answers: str = "",
    rca_handoff: str = "",
) -> str:
    label_map = {
        "buying_process": "BuyProcess", "revenue_model": "RevModel",
        "sales_cycle": "SalesCycle", "existing_assets": "Assets",
        "buyer_behavior": "BuyerDiscovery", "current_stack": "Stack",
    }
    parts = [
        f"GOAL: {outcome_label}",
        f"DOMAIN: {domain}",
        (
            f"TASK (PRIMARY FOCUS — THE ENTIRE PLAYBOOK MUST BE BUILT AROUND THIS SPECIFIC TASK): {task}\n"
            f"⚠️ RULE: Every step, every tool, every example must directly serve '{task}'. "
            f"Website/crawl data is background context only — it NEVER changes this task focus."
        ),
    ]
    if business_profile:
        profile_pairs = []
        for key, value in business_profile.items():
            label = label_map.get(key, key.replace("_", " ").title())
            v = ", ".join(value) if isinstance(value, list) else value
            profile_pairs.append((label, v))
        parts.append(_toon_inline("PROFILE", profile_pairs))
    if rca_handoff:
        parts.append(f"\nDIAGNOSTIC_FINDINGS:\n{rca_handoff}")
    elif rca_history:
        rca_rows = [[qa.get("question", ""), qa.get("answer", "")] for qa in rca_history]
        parts.append("\n" + _toon_table("RCA", ["Q", "A"], rca_rows))
    if rca_summary:
        parts.append(f"\nROOT_CAUSE:\n{rca_summary}")
    if isinstance(crawl_summary, str):
        crawl_text = crawl_summary.strip()
        if crawl_text:
            parts.append(f"\nCRAWL:\n{crawl_text}")
    elif isinstance(crawl_summary, dict) and crawl_summary.get("points"):
        pts = crawl_summary["points"]
        parts.append("\nCRAWL[{}]:\n".format(len(pts)) + "\n".join(str(p) for p in pts))
    if gap_answers:
        parts.append(f"\nGAP_ANSWERS:\n{gap_answers}")
    return "\n".join(p for p in parts if p)


# ══════════════════════════════════════════════════════════════
#  SINGLE PROMPT FLOW — One streaming LLM call
#  Prompt fetched from prompts table (slug: "playbook").
#  Output split by section delimiters into context_brief,
#  website_audit, and playbook.
# ══════════════════════════════════════════════════════════════

_SECTION_DELIMITERS = {
    "context_brief": "---SECTION:context_brief---",
    "website_audit": "---SECTION:website_audit---",
    "playbook":      "---SECTION:playbook---",
}

_PLAYBOOK_PROMPT_DEFAULT = """\
You are a world-class Growth Advisor and Systems Architect.
You just spent two hours studying this business's specific bottlenecks.

Your goal: deliver a surgical, 3-step execution plan that proves your expertise, gives the founder an instant win, and reveals the exact advanced system they need to scale.

This is NOT a generic consulting report. It IS a highly specific, psychological "Domino" sequence:
  Step 1 = instant win (10 minutes, proves the diagnosis was right)
  Step 2 = manual process blueprint (this week, builds understanding)
  Step 3 = scale-up architecture (this month, automates everything)

═══ INPUTS ═══
The user message contains structured context with these labels:
  GOAL             → the broader outcome category
  DOMAIN           → company domain
  TASK             → USER_TASK — THE ENTIRE PLAYBOOK MUST SERVE THIS TASK ONLY
  PROFILE          → scale answers (buying_process, revenue_model, sales_cycle,
                                    existing_assets, buyer_behavior, current_stack)
  DIAGNOSTIC_FINDINGS / RCA → the 3 RCA questions + founder's chosen answers
  ROOT_CAUSE       → RCA summary if available
  CRAWL            → task-filtered website context (what buyers see)
  GAP_ANSWERS      → any additional answers from gap questions
  TOOL LIST        → recommended tools (use these in Step 3)

═══ RULE 1 — TUNNEL VISION ON TASK ═══
Your entire playbook MUST focus 100% on solving TASK.
  Task = Sales Ops → ignore their SEO.
  Task = HR automation → ignore their pricing page.
  Task = Retention → ignore their acquisition funnel.

If a step doesn't directly move TASK forward → DELETE IT.

═══ RULE 2 — BUSINESS MODEL LOCK ═══
SaaS/AI Platform → activation, trial-to-paid, retention, PLG loops.
  NEVER: booking links, Calendly, agency outreach, service-delivery flows.
Service/Agency → pipeline, proposals, referrals, case studies.
  NEVER: PLG tactics, freemium conversion, product activation.
D2C/E-commerce → CAC, AOV, LTV, repeat purchase, retention flows.
  NEVER: enterprise sales, B2B outreach, long sales cycles.
Marketplace → GMV, liquidity, listing quality, take rate.
  NEVER: single-sided growth tactics.

═══ RULE 3 — SPECIFICITY TEST ═══
If you can swap this company's name for a competitor's and the playbook still makes sense → IT IS TOO GENERIC. REWRITE using their exact:
  • Website copy (from CRAWL)
  • RCA answers (what THEY said was their bottleneck)
  • Audit findings (what the buyer actually sees)

═══ RULE 4 — NEVER DESCRIBE WHAT THEY ALREADY KNOW ═══
No corporate recaps. No "Your company does X." Skip to the instruction.
The Diagnosis synthesizes RCA + audit — it reveals WHY they're stuck.
Everything after is action.

═══ VOICE ═══
Razor-sharp, blunt, highly competent friend over coffee.
No jargon: synergize, leverage, optimize, scale, streamline, robust.
Max 1500 words. Dense, punchy, scannable.
Use their industry's actual vocabulary.

═══ OUTPUT FORMAT ═══

Start your response with: ---SECTION:playbook---

Then output:

# The "[Specific Outcome for this TASK]" Playbook

**The Diagnosis:**
[Exactly 2 sentences. Synthesize DIAGNOSTIC_FINDINGS + CRAWL observations.
 Tell them WHY they're failing at TASK. Reference their actual RCA answer + one specific site finding.
 Example: "You have demo traffic, but your follow-up is manual — meanwhile the site has no testimonials above the fold, so cold leads don't even book. Both leaks, one cause: no systematic trust layer."]

---

### STEP 1: The 10-Minute Fix (Instant Win)

**Goal:** [What this achieves immediately — one line]

**What to do right now:** [ONE specific action, under 15 minutes. No new tools.]

**The Exact Script/Action:**
[Give them the exact text to paste, exact setting to change, or exact prompt to run.
 Copy-paste ready. Monospace if it's copy.]

**Done When:** [Binary yes/no condition.]

---

### STEP 2: The Process Blueprint (Manual Workflow)

**Goal:** [How to standardize the fix — one line]

**The Strategy:** [Step-by-step workflow. What to do + how the data should flow.]

**The Bottleneck:** [Why doing this manually breaks at scale. Sets up Step 3.]

**Template/Framework Needed:** [Name one specific artifact — e.g., "3-touch re-engagement script sequence."]

---

### STEP 3: The Ultimate Scale-Up (System Architecture)

**Goal:** [Fully automate / permanently solve TASK]

**The Architecture:** [Name specific tools from the TOOL LIST first, then your own knowledge.
 E.g., Make.com + Vapi + HubSpot, or LangChain + Twilio + Postgres.]

**How it Works:** [Automated data flow in 2-3 lines.
 E.g., "Lead drops off → webhook → personalized AI voice call → objection logged → sequence triggered."]

**The ROI:** [What changes when this runs. Be specific.]

---

**The Hard Truth:** [ONE blunt closing sentence. Not a pitch. A fact that forces a decision.
 Example: "You can keep losing 40% of demo leads to silent follow-ups, or you can plug the leak today — the process is above."]

═══ SELF-CHECK BEFORE RETURNING ═══
☐ Does every step directly serve TASK?
☐ Does the Diagnosis reference a specific RCA answer?
☐ Does the Diagnosis reference a specific site/crawl finding?
☐ Would swapping the company name break the playbook? (If no → rewrite)
☐ Are Step 1 and Step 3 solving the SAME problem at different scales?
☐ Does Step 3 name specific tools (not categories)?
☐ Is the Hard Truth a fact, not a pitch?
☐ Under 1500 words?

If any check fails → rewrite before output.
"""


def _split_sections(full_text: str) -> dict[str, str]:
    """
    Split the single-prompt output into sections using delimiters.
    Returns {context_brief, website_audit, playbook}.
    If no delimiters are found (new-style single-section output), the entire
    text goes into 'playbook' so downstream code always has something to show.
    """
    sections: dict[str, str] = {"context_brief": "", "website_audit": "", "playbook": ""}

    # Build ordered list of (section_key, delimiter, position)
    positions = []
    for key, delimiter in _SECTION_DELIMITERS.items():
        idx = full_text.find(delimiter)
        if idx != -1:
            positions.append((idx, key, delimiter))
    positions.sort()

    # No delimiters found → entire output is the playbook
    if not positions:
        sections["playbook"] = full_text.strip()
        return sections

    for i, (idx, key, delimiter) in enumerate(positions):
        start = idx + len(delimiter)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(full_text)
        sections[key] = full_text[start:end].strip()

    return sections


async def run_single_prompt_stream(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: str | dict[str, Any],
    recommended_tools: str = "",
    gap_answers: str = "",
    rca_handoff: str = "",
    on_token=None,
    onboarding_id: str = "",
) -> dict[str, Any]:
    """
    Single-prompt playbook generation.

    Fetches the system prompt from the prompts table (slug: "playbook"),
    sends one streaming LLM call, and splits the response by section
    delimiters into context_brief, website_audit, and playbook.

    Returns:
        {
            context_brief: str,
            website_audit: str,
            playbook: str,
            latency_ms: int,
            usage: dict,
        }
    """
    from app.services.prompts_service import get_prompt

    system_prompt = await get_prompt("playbook", default=_PLAYBOOK_PROMPT_DEFAULT)
    if not system_prompt:
        raise RuntimeError("Prompt slug 'playbook' not found in prompts table")

    user_message = _build_playbook_input(
        outcome_label=outcome_label,
        domain=domain,
        task=task,
        business_profile=business_profile,
        rca_history=rca_history,
        rca_summary=rca_summary,
        crawl_summary=crawl_summary,
        scale_answers=business_profile,
        gap_answers=gap_answers,
        rca_handoff=rca_handoff,
    )
    if recommended_tools:
        user_message += (
            f"\n\n═══ PROVIDED TOOL LIST (use these in TOOL + AI SHORTCUT where relevant) ═══\n"
            f"{recommended_tools}"
        )

    settings = get_settings()
    model = settings.OPENROUTER_CLAUDE_MODEL
    t0 = time.perf_counter()

    result = await _ai.complete_stream(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.55,
        max_tokens=5000,
        on_token=on_token,
    )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    full_text = result.get("message", "")
    sections = _split_sections(full_text)

    usage = result.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)

    logger.info(
        "Single-prompt playbook stream completed",
        latency_ms=latency_ms,
        has_context_brief=bool(sections["context_brief"]),
        has_website_audit=bool(sections["website_audit"]),
        has_playbook=bool(sections["playbook"]),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    # Log token usage if onboarding_id is provided
    if onboarding_id:
        await log_onboarding_token_usage(
            onboarding_id=onboarding_id,
            stage=STAGE_PLAYBOOK_STREAM,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=True,
        )

    return {
        "context_brief": sections["context_brief"],
        "website_audit": sections["website_audit"],
        "playbook": sections["playbook"],
        "latency_ms": latency_ms,
        "usage": result.get("usage", {}),
    }
