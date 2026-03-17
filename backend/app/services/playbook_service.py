"""
═══════════════════════════════════════════════════════════════
PLAYBOOK SERVICE — 5-Agent AI Growth Playbook Engine
═══════════════════════════════════════════════════════════════
Orchestrates a sequential+parallel agent pipeline to produce
a personalised AI growth playbook from user context.

Flow:
  Input (crawl + Q&A answers)
       ↓
  PHASE 0 — Gap Questions (if context is incomplete)
       ↓
  AGENT 1 — Context Parser  → Business Context Brief
       ↓
  AGENT 2 — ICP Analyst     → ICP Card + Gap Questions
       ↓
  User answers gap questions
       ↓
  AGENT 3 — Playbook Architect → 10-step Playbook
       ↓  (parallel)
  AGENT 4 — Tool Intelligence  (Agent 1 + Agent 3)
  AGENT 5 — Website Critic     (Crawl + Agent 2)

All agents use Claude Opus 4.6 via OpenRouter.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.services.model_router import get_model_config, estimate_cost_inr

logger = structlog.get_logger()

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


# ══════════════════════════════════════════════════════════════
#  SYSTEM PROMPTS — EXACT USER-PROVIDED TEXT (DO NOT MODIFY)
# ══════════════════════════════════════════════════════════════

PHASE0_PROMPT = """
You are a smart intake specialist. You have been given company context and founder answers.


Your job: identify what is GENUINELY missing that would change the playbook — and ask only
those questions. Maximum 3. If you can proceed with fewer, ask fewer. 1 question is fine.


Rules:
— Never ask what is already answered in the context
— Only ask if the answer directly changes a playbook step
— Every question gets 4 realistic options + Option E (type your own)


Output EXACTLY this format and nothing else:


────────────────────────────────────────────────
Before I run your playbook engine, I need clarity on [X] thing(s) the data didn't tell me:


Q1 — [specific question about THIS business]
↳ Why this matters: [one line — what shifts in the playbook based on the answer]


  A) [most common real scenario]
  B) [second realistic scenario]
  C) [third realistic scenario]
  D) [fourth realistic scenario]
  E) None of these — my answer is: ___


[Q2 and Q3 only if genuinely needed, same format]


────────────────────────────────────────────────
Reply: Q1-A, Q2-C etc. Then I build your playbook.
────────────────────────────────────────────────


Stop here. Wait for answers. Do not start any agents.
""".strip()


AGENT1_PROMPT = """
You are the Context Parser — a precision intake specialist.


YOUR ONLY JOB: Receive raw user inputs and output a clean, structured Business Context Brief
that all downstream agents can use.


YOU DO NOT: Give advice. Recommend tools. Build playbooks. Audit websites.
YOU DO: Parse, enrich, structure, and flag gaps.


━━━ OUTPUT CONTRACT ━━━
Always produce this exact structure. Never skip a section.


## BUSINESS CONTEXT BRIEF


**COMPANY SNAPSHOT**
- Name: [extract from data or infer from URL]
- Industry: [specific — not generic]
- Business Model: [B2B / B2C / B2B2C / Marketplace / SaaS / Services / Other]
- Primary Market: [geography + customer segment]
- Revenue Model: [subscription / transaction / project / commission / ad-supported]


**GOAL CLASSIFICATION**
- Primary Goal: [what they want to achieve — one specific sentence]
- Task Priority Order: [list their tasks by urgency, most critical first]
- Why this order: [one sentence — given their stage and constraint]


**BUYER SITUATION**
- Stage: [Idea / Early Traction / Growth Mode / Established — + one implication]
- Current Stack: [tools they have + what they can actually do with them]
- Stack Gap: [what tools or capabilities are missing to execute their goal]
- Channel Strength: [what's working now]
- Constraint: [Time / Money / Clarity / Validation / Tech — + one-line impact on execution]


**WEBSITE INTELLIGENCE**
- Primary CTA: [exact text, or "None detected"]
- ICP Alignment: [HIGH / MEDIUM / LOW]
- SEO Signals: [H1: Y/N | Meta: Y/N | Sitemap: Y/N | Schema: Y/N]
- Biggest Website Risk: [one specific conversion killer]


**INFERRED GAPS** [2-3 things not stated but clearly implied by the data]
- Gap 1: [gap + why it matters]
- Gap 2:
- Gap 3:


**DATA QUALITY**
- Confidence: [HIGH / MEDIUM / LOW]
- Missing Data: [anything unclear or contradictory]


━━━ GUARDRAILS ━━━
- Empty crawl data: flag as critical risk before continuing
- Never invent data. If unknown: state "Unknown — [what would confirm this]"
- Tasks spanning 2+ unrelated domains: flag as "Scope too broad — suggest prioritising one"
""".strip()


AGENT2_PROMPT = """
You are the ICP Analyst — a buyer psychology specialist.


YOUR ONLY JOB: Take a Business Context Brief and produce a deep, specific Ideal Customer
Profile card that any agent or salesperson can use immediately.


YOU DO NOT: Create playbook steps. Recommend tools. Audit websites.
YOU DO: Build the most accurate, specific buyer intelligence possible.


━━━ QUALITY BAR ━━━
FAIL: "Business owner who wants to grow revenue."
PASS: "D2C skincare founder, 12 months post-launch, just hit 500 daily orders, 23% RTO
     eating margin, just lost a major influencer deal because of a late delivery."


━━━ OUTPUT CONTRACT ━━━


## ICP CARD: [Company Name]


**PRIMARY BUYER**
- Title / Role:
- Company Type:
- Company Size:
- Revenue Stage:
- Geography:
- Tech Sophistication: [Low / Medium / High]


**PSYCHOGRAPHIC PROFILE**
- What they worry about at 2am: [one specific sentence — not "growth concerns"]
- What "winning" looks like in 90 days: [specific and measurable]
- What they've already tried: [and the real reason it didn't work]
- Their relationship with AI/new tools: [Skeptic / Curious / Early Adopter / Power User]


**JOBS-TO-BE-DONE**
- Functional Job: [the task they're hiring this product/service for]
- Emotional Job: [how they want to feel — be specific]
- Social Job: [how they want to be seen by peers / board / team]


**BUYING TRIGGERS** [3 specific events that make them search for a solution TODAY]
- Trigger 1: [event + why it creates urgency right now]
- Trigger 2:
- Trigger 3:


**TOP 3 OBJECTIONS** [with the real reason behind each stated objection]
- "[stated objection]" → Real reason:
- "[stated objection]" → Real reason:
- "[stated objection]" → Real reason:


**HOW TO REACH THEM**
- Where they spend time online:
- Content format they trust:
- Tone that converts: [Formal / Peer-to-peer / Data-driven / Story-led / Outcome-first]
- Channels ranked by trust (1 = highest):


**WHAT NOT TO SAY**
- Don't say:
- Don't lead with:
- Don't use:


**ICP MATCH SCORE**: [X/10]
[One line: why this score + one thing that would improve it]


━━━ GUARDRAILS ━━━
- LOW confidence Brief: produce ICP but mark uncertain fields [NEEDS VALIDATION]
- B2B + B2C product: always produce a SECONDARY BUYER profile below the primary
- Never write "business owners" without a specific modifier
""".strip()


AGENT3_PROMPT = """
You are the Playbook Architect — a sharp growth strategist who writes like a founder,
not a consultant.


YOUR ONLY JOB: Build a 10-step playbook this team executes starting Monday.
Not theory. Not strategy documents. Execution.


YOU DO NOT: Define ICP. Audit websites. Write general advice.
YOU DO: Build step-by-step execution with company-specific examples and non-obvious edges.
YOU DO: Use REAL tool names from the CURATED TOOL CATALOG provided (if available).
         When a step needs a tool, pick the best match from the catalog and name it explicitly.
         If no catalog tool fits a step, use a descriptive placeholder like "[a tool for X]".


━━━ STUDY THIS EXACT STYLE AND MATCH IT ━━━


THE "D2C MARGIN RECOVERY" PLAYBOOK


1. The "RTO-Impact" Scoring Sheet


WHAT TO DO
Build a lead list filtered by Negative Logistics Signals. Don't just look for D2C brands —
look for brands currently failing. Search Twitter, Instagram comments, and Google Reviews
for: "Delivery delayed," "Wrong item," "RTO," "Customer support not responding."


TOOL + AI SHORTCUT
Use Apollo.io to export brands in the ₹10Cr–₹50Cr range.
Prompt: "I have a list of D2C brands [Paste List]. Categorize them by likely RTO pain
points in Skincare and Fashion. Write a specific Pain Signal for each based on the
complexity of shipping liquids or high-return apparel."


REAL EXAMPLE
Target Minimalist or Snitch. If you see a spike in "Where is my order" comments on their
latest Instagram post — they move to Tier A immediately.


THE EDGE
The "Logistic Debt" Angle: Brands hiring for multiple Customer Support roles are drowning
in delivery complaints. Use LinkedIn Jobs to find brands hiring 3+ support agents —
that's your Tier A.


━━━ THIS IS YOUR QUALITY BAR ━━━


FAIL: Step 3 — Write Outreach Messages
PASS: 3. The "Trigger-Match Message System"


FAIL: "For example, target a D2C skincare brand..."
PASS: "Target Minimalist or Snitch. If you see 'Where is my order' spike on their
latest Instagram post..."


FAIL: "Send messages at the right time."
PASS: The "Weekend Send": D2C founders review weekly numbers on Saturday mornings —
they're most raw about logistics losses then. Send at 9am.


FAIL: Generic AI prompt that could be for any company
PASS: Prompt specific to THIS company + ICP that would not work for a different company


━━━ OUTPUT FORMAT — FOLLOW EXACTLY ━━━


THE "[OUTCOME IN CAPS]" PLAYBOOK
[Name the playbook after the main outcome for THIS business — not the company name]


[2-3 lines: The One Lever — the single unlock this entire playbook is built around]


---


[N]. The "[Memorable Step Name in Quotes]"


WHAT TO DO
[2-3 lines. Specific action. Smart friend tone — not a report. Always present.]


TOOL + AI SHORTCUT
[Only when a tool or AI genuinely saves time on this step]
[Tool name] — [one line how to use it here]
Prompt: "[Exact copy-paste prompt — specific to this company and ICP. Not generic.]"


REAL EXAMPLE
[Only when a real example makes the action clearer than explanation]
[Name actual brands/companies from their industry. 2-3 lines.]
[If it fits any company — rewrite until it only fits this one.]


THE EDGE
[Only when there is a real non-obvious insight]
The "[Name the technique]": [2-3 lines. Timing trick, psychology angle, tactical detail.
If it's googleable in 3 clicks — find a better one.]


[Repeat for all 10 steps]


---


WEEK 1 EXECUTION CHECKLIST
Monday: [specific action — not "do outreach"]
Tuesday: [specific action]
Wednesday: [specific action]
Thursday: [specific action]
Friday: [specific action]


One line that earns the next conversation:
"[One sentence. What a top consultant says at the end of a paid engagement.
Not a pitch. A truth that makes them want more.]"


━━━ RULES YOU NEVER BREAK ━━━
— Playbook name = the outcome, never the company name
— Every step = named technique in quotes
— WHAT TO DO always present. TOOL, REAL EXAMPLE, THE EDGE earn their place.
— Steps must be a chain — each builds on the last
— Simple English. Founder reads on phone at 10pm. Understands immediately.
— If any step could apply to a different company — rewrite it.
— Exactly 10 steps. No more, no less.
""".strip()


AGENT4_PROMPT = """
You are the Tool Intelligence Agent — a product selection specialist.


YOUR ONLY JOB: Match the best tool to each playbook step for THIS company at THIS stage.


YOU DO NOT: Create steps. Define ICP. Audit websites. Give general tool reviews.
YOU DO: Answer "which tool, and why specifically for this company, at this stage, with this stack."


━━━ 4-CRITERIA DECISION FRAMEWORK ━━━
1. STAGE FIT — Right complexity for where they are NOW?
2. STACK FIT — Works with or replaces existing tools?
3. ROI SPEED — How fast do they see value?
4. SWITCHING COST — How painful to leave when they grow?


Never recommend a tool because it's popular.
Only recommend if it passes all 4 checks.


━━━ OUTPUT CONTRACT ━━━


## TOOL RECOMMENDATION MATRIX: [Company Name]


**CURRENT STACK AUDIT**
- What they have: [from context]
- What's actually usable vs just installed:
- Critical gaps for this playbook:
- Redundancy warnings:


---


STEP [N] → [Tool Name]
What it does here: [specific to this step for this company]
Why not [obvious alternative]: [name it and explain why it loses here]
Free tier: [Yes up to X / No / Trial only]
Setup to first value: [realistic time]
Watch out for: [one gotcha specific to this company type]


[Repeat for each step]


---


TOTAL COST ESTIMATE
- Free only stack: [which steps are covered]
- Lean stack under ₹15,000/month: [which tools]
- Full stack: [which tools + total]


━━━ GUARDRAILS ━━━
- One tool per step maximum
- If one tool covers multiple steps — say so, don't force separate tools
- Biggest constraint = Money → every recommended tool must have a free tier
""".strip()


AGENT5_PROMPT = """
You are the Website Critic — a conversion analyst.


YOUR ONLY JOB: Audit the website through the ICP's eyes and tell the owner exactly
what's failing and what to fix.


Every finding must name a SPECIFIC element from the website.
No evidence = delete the finding.


FAIL: "The website lacks social proof."
PASS: "Homepage has no testimonials above the fold. The only trust signal is award logos
buried below 3 scroll depths. A first-time visitor leaves before seeing them."


━━━ OUTPUT CONTRACT ━━━


## WEBSITE AUDIT: [Company Name]


VERDICT [one honest sentence]


HEALTH SCORE
| What              | Score /10 | Evidence                    |
|---|---|---|
| SEO               |           |                             |
| ICP Message Match |           |                             |
| CTA Clarity       |           |                             |
| Social Proof      |           |                             |
| Conversion Path   |           |                             |
| Trust Signals     |           |                             |


Overall: [X/10]


ICP MISMATCHES
[What site says vs what ICP needs to see + Revenue impact: HIGH / MEDIUM / LOW]


QUICK WINS [zero dev, under 1 week]
1. [Exact element + exactly what to change it to]
2.
3.


STRATEGIC FIXES [1-4 weeks, some dev]
1.
2.


THE ONE THING
[If they do only one fix — what is it, why first, what does success look like]


━━━ GUARDRAILS ━━━
- Empty corpus: CRITICAL WARNING before any analysis
- Never assume what's on pages not in the corpus
- Quick Wins must be genuinely no-dev. If it needs a developer — Strategic Fixes.
""".strip()


# ══════════════════════════════════════════════════════════════
#  HELPER — Call Claude Opus via OpenRouter
# ══════════════════════════════════════════════════════════════

async def _call_claude(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    task: str = "",
) -> dict[str, Any]:
    """
    Call LLM via the model router.
    If `task` is provided, the model router selects the appropriate tier.
    Otherwise falls back to the default OpenRouter/GLM-5 config.
    Returns {"content": str, "usage": dict, "latency_ms": int, "model": str}.
    """
    if task:
        mc = get_model_config(task, temperature=temperature, max_tokens=max_tokens)
    else:
        settings = get_settings()
        from app.services.model_router import ModelConfig
        mc = ModelConfig(
            model=settings.OPENROUTER_MODEL,
            provider="openrouter",
            api_key=settings.OPENROUTER_API_KEY,
            base_url=OPENROUTER_CHAT_URL,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=120.0,
        )

    payload = {
        "model": mc.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": mc.temperature,
        "max_tokens": mc.max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {mc.api_key}",
        "Content-Type": "application/json",
    }
    if mc.provider == "openrouter":
        headers["HTTP-Referer"] = mc.referer
        headers["X-Title"] = mc.title

    t0 = time.perf_counter()
    max_retries = 3
    async with httpx.AsyncClient(timeout=mc.timeout) as client:
        for attempt in range(max_retries):
            resp = await client.post(mc.base_url, json=payload, headers=headers)
            if resp.status_code == 429 and attempt < max_retries - 1:
                wait = 2 ** attempt + 1  # 2s, 3s, 5s
                logger.warning("Rate limit 429, retrying", attempt=attempt + 1, wait_s=wait, provider=mc.provider)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break

    latency_ms = int((time.perf_counter() - t0) * 1000)
    data = resp.json()

    content = data["choices"][0]["message"]["content"]
    # GLM-5 reasoning models may return reasoning separately
    if not content or not content.strip():
        content = data["choices"][0]["message"].get("reasoning", "")
    usage = data.get("usage", {})

    logger.info(
        "LLM call completed",
        model=mc.model,
        provider=mc.provider,
        task=task,
        latency_ms=latency_ms,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
    )

    return {"content": content, "usage": usage, "latency_ms": latency_ms, "model": mc.model}


async def _call_claude_stream(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    task: str = "",
):
    """
    Streaming version of _call_claude. Yields text chunks as they arrive.
    After the stream ends, yields a final dict with usage/latency metadata.
    """
    import json as _json

    if task:
        mc = get_model_config(task, temperature=temperature, max_tokens=max_tokens)
    else:
        settings = get_settings()
        from app.services.model_router import ModelConfig
        mc = ModelConfig(
            model=settings.OPENROUTER_MODEL,
            provider="openrouter",
            api_key=settings.OPENROUTER_API_KEY,
            base_url=OPENROUTER_CHAT_URL,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=120.0,
        )

    payload = {
        "model": mc.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": mc.temperature,
        "max_tokens": mc.max_tokens,
        "stream": True,
    }

    headers = {
        "Authorization": f"Bearer {mc.api_key}",
        "Content-Type": "application/json",
    }
    if mc.provider == "openrouter":
        headers["HTTP-Referer"] = mc.referer
        headers["X-Title"] = mc.title

    t0 = time.perf_counter()
    full_content = []

    async with httpx.AsyncClient(timeout=mc.timeout) as client:
        async with client.stream("POST", mc.base_url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        full_content.append(text)
                        yield text
                except Exception:
                    continue

    latency_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "LLM streaming call completed",
        model=mc.model,
        provider=mc.provider,
        task=task,
        latency_ms=latency_ms,
    )
    # Yield final metadata dict so the caller can collect it
    yield {
        "_meta": True,
        "content": "".join(full_content),
        "latency_ms": latency_ms,
        "model": mc.model,
        "usage": {},
    }


# ══════════════════════════════════════════════════════════════
#  BUILD USER INPUT CONTEXT — Assembles all session data
# ══════════════════════════════════════════════════════════════

def _build_playbook_input(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: dict[str, Any],
    scale_answers: dict[str, Any],
    gap_answers: str = "",
) -> str:
    """
    Assemble the full user context that is fed into each agent.
    """
    parts = [
        "═══ FOUNDER ANSWERS ═══",
        f"Goal (Q1): {outcome_label}",
        f"Domain (Q2): {domain}",
        f"Task (Q3): {task}",
    ]

    # Scale question answers
    if business_profile:
        parts.append("\n═══ BUSINESS PROFILE (Scale Questions) ═══")
        label_map = {
            "buying_process": "How Customers Buy",
            "revenue_model": "Revenue Model",
            "sales_cycle": "Sales Cycle Length",
            "existing_assets": "Existing Marketing Assets",
            "buyer_behavior": "Buyer Discovery Behavior",
            "current_stack": "Current Tech Stack",
        }
        for key, value in business_profile.items():
            label = label_map.get(key, key.replace("_", " ").title())
            if isinstance(value, list):
                parts.append(f"  • {label}: {', '.join(value)}")
            else:
                parts.append(f"  • {label}: {value}")

    # RCA diagnostic history
    if rca_history:
        parts.append("\n═══ DIAGNOSTIC Q&A (RCA Deep-Dive) ═══")
        for i, qa in enumerate(rca_history, 1):
            parts.append(f"  Q{i}: {qa.get('question', '')}")
            parts.append(f"  A{i}: {qa.get('answer', '')}")

    # RCA summary
    if rca_summary:
        parts.append(f"\n═══ ROOT CAUSE DIAGNOSIS ═══\n{rca_summary}")

    # Crawl data
    if crawl_summary and crawl_summary.get("points"):
        parts.append("\n═══ WEBSITE CRAWL DATA ═══")
        for pt in crawl_summary["points"]:
            parts.append(f"  • {pt}")

    # Gap answers (from Phase 0 or Agent 2)
    if gap_answers:
        parts.append(f"\n═══ GAP QUESTION ANSWERS ═══\n{gap_answers}")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════
#  PHASE 0 — Gap Questions (pre-playbook)
# ══════════════════════════════════════════════════════════════

async def run_phase0_gap_questions(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: dict[str, Any],
) -> dict[str, Any]:
    """
    Phase 0: Identify what is GENUINELY missing from the context.
    Returns gap questions (max 3) or empty if context is sufficient.
    """
    user_message = _build_playbook_input(
        outcome_label=outcome_label,
        domain=domain,
        task=task,
        business_profile=business_profile,
        rca_history=rca_history,
        rca_summary=rca_summary,
        crawl_summary=crawl_summary,
        scale_answers=business_profile,
    )

    result = await _call_claude(
        system_prompt=PHASE0_PROMPT,
        user_message=user_message,
        temperature=0.5,
        max_tokens=1500,
    )

    logger.info(
        "Phase 0 gap questions generated",
        latency_ms=result["latency_ms"],
    )

    return {
        "gap_questions_text": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


# ══════════════════════════════════════════════════════════════
#  AGENT 1 OUTPUT VALIDATION
# ══════════════════════════════════════════════════════════════

def _validate_agent1_output(content: str) -> bool:
    """
    Validate that Agent 1's output contains the key sections
    expected by Agent 2. Returns True if output looks valid.
    """
    required_markers = [
        "COMPANY SNAPSHOT",
        "GOAL CLASSIFICATION",
        "BUYER SITUATION",
    ]
    return all(marker in content for marker in required_markers)


# ══════════════════════════════════════════════════════════════
#  AGENT 1 — Context Parser
# ══════════════════════════════════════════════════════════════

async def run_agent1_context_parser(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: dict[str, Any],
    gap_answers: str = "",
) -> dict[str, Any]:
    """
    Agent 1: Parse raw input into a structured Business Context Brief.
    """
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
    )

    result = await _call_claude(
        system_prompt=AGENT1_PROMPT,
        user_message=user_message,
        temperature=0.4,
        max_tokens=3000,
        task="playbook_agent1",
    )

    # Validate Agent 1 structured output — retry with premium model if bad
    if not _validate_agent1_output(result["content"]):
        logger.warning(
            "Agent 1 output validation failed on cheap model, retrying with premium",
            model=result.get("model", ""),
        )
        result = await _call_claude(
            system_prompt=AGENT1_PROMPT,
            user_message=user_message,
            temperature=0.4,
            max_tokens=3000,
            # No task = defaults to premium OpenRouter model
        )

    logger.info(
        "Agent 1 (Context Parser) completed",
        latency_ms=result["latency_ms"],
        model=result.get("model", ""),
    )

    return {
        "agent": "agent1_context_parser",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


# ══════════════════════════════════════════════════════════════
#  AGENT 2 — ICP Analyst + Gap Questions
# ══════════════════════════════════════════════════════════════

async def run_agent2_icp_analyst(
    agent1_output: str,
) -> dict[str, Any]:
    """
    Agent 2: Build ICP Card from Agent 1's Business Context Brief.
    Also generates gap questions if critical info is missing.
    Input: Agent 1 output.
    """
    user_message = (
        "Here is the Business Context Brief from the Context Parser:\n\n"
        f"{agent1_output}\n\n"
        "Build the ICP Card. Do NOT produce gap questions — proceed with reasonable "
        "assumptions for any missing information. We have enough context to build the playbook."
    )

    result = await _call_claude(
        system_prompt=AGENT2_PROMPT,
        user_message=user_message,
        temperature=0.6,
        max_tokens=4000,
        task="playbook_agent2",
    )

    logger.info(
        "Agent 2 (ICP Analyst) completed",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent": "agent2_icp_analyst",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


# ══════════════════════════════════════════════════════════════
#  AGENT 3 — Playbook Architect
# ══════════════════════════════════════════════════════════════

async def run_agent3_playbook_architect(
    agent1_output: str,
    agent2_output: str,
    gap_answers: str = "",
    curated_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Agent 3: Build the 10-step execution playbook.
    Input: Agent 1 output + Agent 2 output + gap answers + curated tool catalog.
    """
    user_message = (
        "═══ BUSINESS CONTEXT BRIEF (Agent 1) ═══\n"
        f"{agent1_output}\n\n"
        "═══ ICP CARD (Agent 2) ═══\n"
        f"{agent2_output}\n\n"
    )
    if gap_answers:
        user_message += (
            "═══ GAP QUESTION ANSWERS ═══\n"
            f"{gap_answers}\n\n"
        )
    if curated_tools:
        user_message += "═══ CURATED TOOL CATALOG (use these by name in TOOL + AI SHORTCUT sections) ═══\n"
        for i, tool in enumerate(curated_tools[:15], 1):
            name = tool.get("name", "Unknown")
            desc = tool.get("description", "")[:120]
            best_use = tool.get("best_use_case", "")[:80]
            user_message += f"{i}. {name} — {desc}"
            if best_use:
                user_message += f" | Best for: {best_use}"
            user_message += "\n"
        user_message += "\n"
    user_message += (
        "Build the 10-step playbook now. Follow the exact output format. "
        "Every step must be specific to THIS company — nothing generic. "
        "You MUST include all 10 steps — do NOT stop early. Exactly 10 numbered steps."
    )

    result = await _call_claude(
        system_prompt=AGENT3_PROMPT,
        user_message=user_message,
        temperature=0.7,
        max_tokens=4500,
    )

    logger.info(
        "Agent 3 (Playbook Architect) completed",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent": "agent3_playbook_architect",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


# ══════════════════════════════════════════════════════════════
#  AGENT 4 — Tool Intelligence (parallel with Agent 5)
# ══════════════════════════════════════════════════════════════

async def run_agent4_tool_intelligence(
    agent1_output: str,
    agent3_output: str,
    curated_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Agent 4: Match best tool to each playbook step.
    Input: Agent 1 output + Agent 3 playbook + curated tool catalog.
    """
    user_message = (
        "═══ BUSINESS CONTEXT BRIEF (Agent 1) ═══\n"
        f"{agent1_output}\n\n"
        "═══ 10-STEP PLAYBOOK (Agent 3) ═══\n"
        f"{agent3_output}\n\n"
    )

    if curated_tools:
        user_message += "═══ CURATED TOOL CATALOG (verified, with ratings) ═══\n"
        user_message += (
            "IMPORTANT: Prefer tools from this catalog — they are verified with real user ratings. "
            "Use the exact tool name from the catalog. Only suggest tools outside this list if "
            "no catalog tool fits a step.\n\n"
        )
        for i, tool in enumerate(curated_tools[:20], 1):
            name = tool.get("name", "Unknown")
            desc = tool.get("description", "")[:150]
            cat = tool.get("category", "")
            rating = tool.get("rating", "")
            url = tool.get("url", "")
            best_use = tool.get("best_use_case", "") or tool.get("why_relevant", "")
            parts = [f"{i}. **{name}**"]
            if cat:
                parts.append(f"Category: {cat}")
            if rating:
                parts.append(f"Rating: {rating}/5")
            if desc:
                parts.append(f"Description: {desc}")
            if best_use:
                parts.append(f"Best for: {best_use[:100]}")
            if url:
                parts.append(f"URL: {url}")
            user_message += " | ".join(parts) + "\n"
        user_message += "\n"

    user_message += "Match the best tool for each playbook step. Follow the exact output format."

    result = await _call_claude(
        system_prompt=AGENT4_PROMPT,
        user_message=user_message,
        temperature=0.5,
        max_tokens=4000,
    )

    logger.info(
        "Agent 4 (Tool Intelligence) completed",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent": "agent4_tool_intelligence",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


# ══════════════════════════════════════════════════════════════
#  AGENT 5 — Website Critic (parallel with Agent 4)
# ══════════════════════════════════════════════════════════════

async def run_agent5_website_critic(
    crawl_summary: dict[str, Any],
    agent2_output: str,
    crawl_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Agent 5: Audit the website through the ICP's eyes.
    Input: Full crawl data + Agent 2 ICP Card.
    """
    parts: list[str] = []

    # Build rich crawl context from crawl_raw (detailed data)
    if crawl_raw:
        hp = crawl_raw.get("homepage", {})
        if hp.get("title"):
            parts.append(f"Homepage Title: {hp['title']}")
        if hp.get("meta_desc"):
            parts.append(f"Meta Description: {hp['meta_desc']}")
        if hp.get("h1s"):
            parts.append(f"H1 Headlines: {', '.join(hp['h1s'][:5])}")
        if hp.get("headings"):
            parts.append(f"Sub-headings: {', '.join(hp['headings'][:10])}")
        if hp.get("nav_links"):
            nav_labels = [n.get("text", "") for n in hp["nav_links"][:10] if isinstance(n, dict)]
            if nav_labels:
                parts.append(f"Navigation Links: {', '.join(nav_labels)}")

        tech = crawl_raw.get("tech_signals", [])
        if tech:
            parts.append(f"Tech Stack: {', '.join(tech[:12])}")

        ctas = crawl_raw.get("cta_patterns", [])
        if ctas:
            parts.append(f"CTAs Found: {', '.join(ctas[:8])}")

        socials = crawl_raw.get("social_links", [])
        if socials:
            parts.append(f"Social Links: {', '.join(socials[:6])}")

        seo = crawl_raw.get("seo_basics", {})
        seo_notes = []
        if seo.get("has_meta"):
            seo_notes.append("Has meta tags")
        else:
            seo_notes.append("Missing meta tags")
        if seo.get("has_viewport"):
            seo_notes.append("Mobile viewport set")
        else:
            seo_notes.append("No mobile viewport")
        if seo.get("has_sitemap"):
            seo_notes.append("Sitemap detected")
        else:
            seo_notes.append("No sitemap")
        if seo_notes:
            parts.append(f"SEO Basics: {', '.join(seo_notes)}")

        schema = crawl_raw.get("schema_markup", [])
        if schema:
            parts.append(f"Schema Markup: {', '.join(str(s) for s in schema[:5])}")

        pages = crawl_raw.get("pages_crawled", [])
        if pages:
            parts.append(f"\nPages Crawled ({len(pages)}):")
            for p in pages[:8]:
                content = p.get("key_content", "")[:500]
                parts.append(f"  [{p.get('type', 'page')}] {p.get('url', '')}")
                if content:
                    parts.append(f"    Content: {content}")

    # Fallback to summary if no raw data
    if not parts:
        if crawl_summary and crawl_summary.get("points"):
            parts = [f"  • {pt}" for pt in crawl_summary["points"]]
        else:
            parts = ["(No crawl data available — CRITICAL WARNING)"]

    crawl_text = "\n".join(parts)

    user_message = (
        "═══ WEBSITE CRAWL DATA ═══\n"
        f"{crawl_text}\n\n"
        "═══ ICP CARD (Agent 2) ═══\n"
        f"{agent2_output}\n\n"
        "Audit this website through the ICP's eyes. Follow the exact output format. "
        "Every finding must reference a SPECIFIC element from the crawl data."
    )

    result = await _call_claude(
        system_prompt=AGENT5_PROMPT,
        user_message=user_message,
        temperature=0.5,
        max_tokens=4000,
    )

    logger.info(
        "Agent 5 (Website Critic) completed",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent": "agent5_website_critic",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


# ══════════════════════════════════════════════════════════════
#  ORCHESTRATOR — Full Pipeline Execution
# ══════════════════════════════════════════════════════════════

async def run_full_playbook_pipeline(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: dict[str, Any],
    gap_answers: str = "",
    cached_agent1_output: str = "",
    cached_agent2_output: str = "",
    curated_tools: list[dict[str, Any]] | None = None,
    crawl_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run the complete 5-agent pipeline:
      Agent 1 → Agent 2 → (wait for gap answers if needed) → Agent 3 → Agent 4 + 5 (parallel)

    This is the FULL pipeline called AFTER gap answers are collected.
    If cached_agent1_output and cached_agent2_output are provided (from /start),
    Agent 1 and 2 are skipped to avoid double-execution.
    Returns all agent outputs + total timing.
    """
    t0 = time.perf_counter()
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _accum_usage(result: dict) -> None:
        u = result.get("usage", {})
        total_usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        total_usage["completion_tokens"] += u.get("completion_tokens", 0)

    # ── Step 1: Agent 1 — Context Parser (skip if cached) ────
    if cached_agent1_output:
        agent1 = {"agent": "agent1_context_parser", "output": cached_agent1_output, "usage": {}, "latency_ms": 0}
        logger.info("Agent 1 skipped — using cached output from /start")
    else:
        agent1 = await run_agent1_context_parser(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=crawl_summary,
            gap_answers=gap_answers,
        )
    _accum_usage(agent1)

    # ── Step 2: Agent 2 — ICP Analyst (skip if cached) ────────
    if cached_agent2_output:
        agent2 = {"agent": "agent2_icp_analyst", "output": cached_agent2_output, "usage": {}, "latency_ms": 0}
        logger.info("Agent 2 skipped — using cached output from /start")
    else:
        agent2 = await run_agent2_icp_analyst(agent1_output=agent1["output"])
    _accum_usage(agent2)

    # ── Step 3: Agent 3 + Agent 5 in parallel ──────────────────
    # Agent 5 only needs crawl_summary + agent2_output (both ready now)
    # so it runs alongside Agent 3 instead of waiting for it.
    agent3_task = run_agent3_playbook_architect(
        agent1_output=agent1["output"],
        agent2_output=agent2["output"],
        gap_answers=gap_answers,
        curated_tools=curated_tools,
    )
    agent5_task = run_agent5_website_critic(
        crawl_summary=crawl_summary,
        agent2_output=agent2["output"],
        crawl_raw=crawl_raw,
    )
    agent3, agent5 = await asyncio.gather(agent3_task, agent5_task)
    _accum_usage(agent3)
    _accum_usage(agent5)

    # ── Step 4: Agent 4 (needs Agent 3 output) ────────────────
    agent4 = await run_agent4_tool_intelligence(
        agent1_output=agent1["output"],
        agent3_output=agent3["output"],
        curated_tools=curated_tools,
    )
    _accum_usage(agent4)

    total_ms = int((time.perf_counter() - t0) * 1000)

    pipeline_cost = estimate_cost_inr(
        total_usage["prompt_tokens"],
        total_usage["completion_tokens"],
    )

    logger.info(
        "Full playbook pipeline completed",
        total_latency_ms=total_ms,
        total_prompt_tokens=total_usage["prompt_tokens"],
        total_completion_tokens=total_usage["completion_tokens"],
        estimated_cost_inr=round(pipeline_cost, 4),
    )

    return {
        "agent1_context_brief": agent1["output"],
        "agent2_icp_card": agent2["output"],
        "agent3_playbook": agent3["output"],
        "agent4_tool_matrix": agent4["output"],
        "agent5_website_audit": agent5["output"],
        "total_latency_ms": total_ms,
        "total_usage": total_usage,
        "estimated_cost_inr": pipeline_cost,
        "agent_latencies": {
            "agent1": agent1["latency_ms"],
            "agent2": agent2["latency_ms"],
            "agent3": agent3["latency_ms"],
            "agent4": agent4["latency_ms"],
            "agent5": agent5["latency_ms"],
        },
    }


# ══════════════════════════════════════════════════════════════
#  STREAMING PIPELINE — SSE generator for /playbook/stream
# ══════════════════════════════════════════════════════════════

async def run_playbook_pipeline_stream(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: dict[str, Any],
    gap_answers: str = "",
    cached_agent1_output: str = "",
    cached_agent2_output: str = "",
    curated_tools: list[dict[str, Any]] | None = None,
    crawl_raw: dict[str, Any] | None = None,
):
    """
    Streaming version of the pipeline.
    Yields SSE-formatted events as strings:
      event: status    → progress updates
      event: chunk     → Agent 3 text chunks
      event: result    → JSON blobs (agent4, agent5)
      event: done      → final summary
    """
    import json as _json

    t0 = time.perf_counter()

    def _sse(event: str, data: str) -> str:
        return f"event: {event}\ndata: {data}\n\n"

    # ── Agent 1 (cached) ──────────────────────────────────────
    yield _sse("status", "Preparing context...")
    agent1_output = cached_agent1_output
    if not agent1_output:
        agent1 = await run_agent1_context_parser(
            outcome_label=outcome_label, domain=domain, task=task,
            business_profile=business_profile, rca_history=rca_history,
            rca_summary=rca_summary, crawl_summary=crawl_summary,
            gap_answers=gap_answers,
        )
        agent1_output = agent1["output"]

    # ── Agent 2 (cached) ──────────────────────────────────────
    agent2_output = cached_agent2_output
    if not agent2_output:
        agent2 = await run_agent2_icp_analyst(agent1_output=agent1_output)
        agent2_output = agent2["output"]

    yield _sse("status", "Building your playbook...")

    # ── Agent 5 — kick off in background ──────────────────────
    agent5_task = asyncio.create_task(run_agent5_website_critic(
        crawl_summary=crawl_summary,
        agent2_output=agent2_output,
        crawl_raw=crawl_raw,
    ))

    # ── Agent 3 — stream output ───────────────────────────────
    a3_user_message = (
        "═══ BUSINESS CONTEXT BRIEF (Agent 1) ═══\n"
        f"{agent1_output}\n\n"
        "═══ ICP CARD (Agent 2) ═══\n"
        f"{agent2_output}\n\n"
    )
    if gap_answers:
        a3_user_message += (
            "═══ GAP QUESTION ANSWERS ═══\n"
            f"{gap_answers}\n\n"
        )
    if curated_tools:
        a3_user_message += "═══ CURATED TOOL CATALOG (use these by name in TOOL + AI SHORTCUT sections) ═══\n"
        for i, tool in enumerate(curated_tools[:15], 1):
            name = tool.get("name", "Unknown")
            desc = tool.get("description", "")[:120]
            best_use = tool.get("best_use_case", "")[:80]
            a3_user_message += f"{i}. {name} — {desc}"
            if best_use:
                a3_user_message += f" | Best for: {best_use}"
            a3_user_message += "\n"
        a3_user_message += "\n"
    a3_user_message += (
        "Build the 10-step playbook now. Follow the exact output format. "
        "Every step must be specific to THIS company — nothing generic. "
        "You MUST include all 10 steps — do NOT stop early. Exactly 10 numbered steps."
    )

    agent3_content = ""
    agent3_latency = 0
    async for chunk in _call_claude_stream(
        system_prompt=AGENT3_PROMPT,
        user_message=a3_user_message,
        temperature=0.7,
        max_tokens=4500,
    ):
        if isinstance(chunk, dict) and chunk.get("_meta"):
            agent3_content = chunk["content"]
            agent3_latency = chunk["latency_ms"]
        else:
            yield _sse("chunk", chunk)

    yield _sse("status", "Matching tools & auditing website...")

    # ── Agent 5 — await result ────────────────────────────────
    agent5 = await agent5_task

    # ── Agent 4 — needs Agent 3 output ────────────────────────
    agent4 = await run_agent4_tool_intelligence(
        agent1_output=agent1_output,
        agent3_output=agent3_content,
        curated_tools=curated_tools,
    )

    total_ms = int((time.perf_counter() - t0) * 1000)

    # ── Send final results ────────────────────────────────────
    yield _sse("result", _json.dumps({
        "agent1_context_brief": agent1_output,
        "agent2_icp_card": agent2_output,
        "agent3_playbook": agent3_content,
        "agent4_tool_matrix": agent4["output"],
        "agent5_website_audit": agent5["output"],
        "total_latency_ms": total_ms,
        "agent_latencies": {
            "agent3": agent3_latency,
            "agent4": agent4["latency_ms"],
            "agent5": agent5["latency_ms"],
        },
    }))

    yield _sse("done", "complete")
