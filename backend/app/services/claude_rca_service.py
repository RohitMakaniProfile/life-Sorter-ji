"""
═══════════════════════════════════════════════════════════════
CLAUDE RCA SERVICE — Root Cause Analysis via Claude Opus 4.6
═══════════════════════════════════════════════════════════════
Calls Claude Sonnet via the OpenRouter API to generate
adaptive, layman-friendly diagnostic questions one at a time.

Takes dynamic-loader context (problems, RCA bridge symptoms,
opportunities, strategies) + user's Q1-Q3 answers + previous
RCA Q&A history → returns the next question or signals "done".

Fallback: if Claude is unreachable, the old dynamic-loader
questions are served directly (pre-parsed from persona docs).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog
import json

import re
from app.config import get_settings
from app.services.ai_helper import _extract_json_value, ai_helper as _ai
from app.services.token_usage_service import (
    log_onboarding_token_usage,
    STAGE_GAP_QUESTIONS,
)

logger = structlog.get_logger()

async def _call_openrouter_with_retry(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return await _ai.complete(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code == 429 and attempt < 2:
                await asyncio.sleep(2 ** attempt + 1)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("OpenRouter call failed")


# ══════════════════════════════════════════════════════════════
# TASK ALIGNMENT FILTER — Pre-filters persona context for RCA
# ══════════════════════════════════════════════════════════════

TASK_FILTER_SYSTEM_PROMPT = """\
You are a task-context alignment engine. Your job is to take a full persona \
knowledge base and extract ONLY the items that directly relate to how someone \
currently performs, fails at, or could improve a SPECIFIC task.

You will receive:
1. The user's selected task
2. The full persona context (problems, diagnostic signals, opportunities, strategies)

Your job: Filter ruthlessly. Keep only items that describe:
- METHOD: How they currently perform this task (process, tools, workflow)
- SPEED: How fast they detect issues, respond, or act on this task
- QUALITY: How accurate, effective, or reliable their current approach is

DISCARD anything that:
- Describes downstream business consequences (revenue loss, churn, etc.)
- Describes adjacent workflows that aren't part of this specific task
- Describes upstream causes unless they directly block task execution
- Is generic advice not specific to this task's execution

Also generate a task_execution_summary: a 1-2 sentence description of what \
doing this task actually looks like day-to-day for a typical business.

═══ RESPONSE FORMAT ═══

Respond in valid JSON only. No text before or after the JSON.

{
  "task_execution_summary": "1-2 sentences: what doing this task looks like day-to-day",
  "filtered_items": {
    "method": [
      {"source": "problems|rca_bridge|opportunities|strategies", "item": "the exact item text", "relevance": "why this relates to HOW they do the task"}
    ],
    "speed": [
      {"source": "problems|rca_bridge|opportunities|strategies", "item": "the exact item text", "relevance": "why this relates to detection/response SPEED"}
    ],
    "quality": [
      {"source": "problems|rca_bridge|opportunities|strategies", "item": "the exact item text", "relevance": "why this relates to accuracy/effectiveness"}
    ]
  },
  "deferred_items": [
    {"source": "problems|rca_bridge|opportunities|strategies", "item": "item text", "reason": "why this was deferred (downstream consequence, adjacent workflow, etc.)"}
  ]
}
"""


def _build_filter_user_message(task: str, diagnostic_context: dict[str, Any]) -> str:
    """Build the user message for the task alignment filter."""
    parts = [f"═══ USER'S SELECTED TASK ═══\n{task}\n"]

    if not diagnostic_context:
        parts.append("(No persona context available)")
        return "\n".join(parts)

    matched_task = diagnostic_context.get("task_matched", "")
    if matched_task:
        parts.append(f"Matched knowledge-base task: \"{matched_task}\"\n")

    sections = diagnostic_context.get("sections", [])
    for sec in sections:
        key = sec.get("key", "")
        items = sec.get("items", [])

        if key == "problems":
            parts.append("═══ PROBLEM PATTERNS (full list) ═══")
            for i, item in enumerate(items, 1):
                parts.append(f"  P{i}. {item}")

        elif key == "rca_bridge":
            parts.append("\n═══ DIAGNOSTIC SIGNALS (full list) ═══")
            rca_parsed = sec.get("rca_parsed", [])
            if rca_parsed:
                for i, rca in enumerate(rca_parsed, 1):
                    sym = rca.get("symptom", "")
                    met = rca.get("metric", "")
                    root = rca.get("root_area", "")
                    line = f"  S{i}. \"{sym}\""
                    if met:
                        line += f" → KPI: {met}"
                    if root:
                        line += f" → Root: {root}"
                    parts.append(line)
            else:
                for i, item in enumerate(items, 1):
                    parts.append(f"  S{i}. {item}")

        elif key == "opportunities":
            parts.append("\n═══ GROWTH OPPORTUNITIES (full list) ═══")
            for i, item in enumerate(items, 1):
                parts.append(f"  O{i}. {item}")

    strategies = diagnostic_context.get("strategies", "")
    if strategies:
        parts.append("\n═══ STRATEGIES & FRAMEWORKS (full list) ═══")
        parts.append(strategies[:2000])

    return "\n".join(parts)


def _validate_filtered_context(filtered: dict[str, Any]) -> dict[str, Any]:
    """
    Step 7: Validate that filtered context has at least one item per category.
    Returns validation result with any empty categories flagged.
    """
    filtered_items = filtered.get("filtered_items", {})
    method_items = filtered_items.get("method", [])
    speed_items = filtered_items.get("speed", [])
    quality_items = filtered_items.get("quality", [])

    empty_categories = []
    if not method_items:
        empty_categories.append("method")
    if not speed_items:
        empty_categories.append("speed")
    if not quality_items:
        empty_categories.append("quality")

    filtered["_validation"] = {
        "all_covered": len(empty_categories) == 0,
        "empty_categories": empty_categories,
        "method_count": len(method_items),
        "speed_count": len(speed_items),
        "quality_count": len(quality_items),
        "total_filtered": len(method_items) + len(speed_items) + len(quality_items),
        "total_deferred": len(filtered.get("deferred_items", [])),
    }

    return filtered


async def generate_task_alignment_filter(
    task: str,
    diagnostic_context: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Task Alignment Filter (Step 3): Calls Claude Opus via OpenRouter to filter
    the full persona context down to only task-relevant items, categorized as
    METHOD, SPEED, or QUALITY.

    Returns:
        {
            "task_execution_summary": "...",
            "filtered_items": {"method": [...], "speed": [...], "quality": [...]},
            "deferred_items": [...],
            "_validation": {"all_covered": bool, "empty_categories": [...], ...}
        }
        or None on failure.
    """
    settings = get_settings()
    api_key = settings.OPENROUTER_API_KEY
    model = settings.OPENROUTER_CLAUDE_MODEL  # Sonnet — faster + reliable JSON

    if not api_key:
        logger.warning("OpenRouter API key not configured — skipping task filter")
        return None

    if not diagnostic_context or not diagnostic_context.get("sections"):
        logger.info("No diagnostic context to filter — skipping task filter")
        return None

    user_content = _build_filter_user_message(task, diagnostic_context)

    try:
        t0 = time.monotonic()
        result = await _call_openrouter_with_retry(
            model=model,
            system_prompt=TASK_FILTER_SYSTEM_PROMPT,
            user_content=user_content,
            temperature=0.3,
            max_tokens=800,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        content = str(result.get("message") or "")
        logger.info("Task filter raw response", raw_content=content[:500] if content else "<empty>")

        if not content or not content.strip():
            logger.error("Task filter returned empty content")
            return None

        # Strip markdown code fences if present (```json ... ```)
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r'^```(?:json)?\s*', '', stripped)
            stripped = re.sub(r'\s*```\s*$', '', stripped)

        # Parse JSON (with fallback extraction)
        try:
            result = json.loads(stripped)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', stripped)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    logger.info("Task filter: extracted JSON from wrapped response")
                except json.JSONDecodeError:
                    logger.error("Task filter: could not parse extracted JSON", raw=content[:500])
                    return None
            else:
                logger.error("Task filter: no JSON found in response", raw=content[:500])
                return None

        # Validate structure
        if "filtered_items" not in result:
            logger.error("Task filter: missing filtered_items in response")
            return None

        # Run validation (Step 7)
        result = _validate_filtered_context(result)

        # Attach metadata
        result["_meta"] = {
            "service": "openrouter",
            "model": model,
            "purpose": "task_alignment_filter",
            "system_prompt": TASK_FILTER_SYSTEM_PROMPT,
            "user_message": user_content,
            "temperature": 0.3,
            "max_tokens": 2000,
            "raw_response": content,
            "latency_ms": latency_ms,
        }

        validation = result["_validation"]
        logger.info(
            "Task alignment filter complete",
            task=task[:60],
            method_count=validation["method_count"],
            speed_count=validation["speed_count"],
            quality_count=validation["quality_count"],
            deferred_count=validation["total_deferred"],
            all_covered=validation["all_covered"],
            empty_categories=validation["empty_categories"],
            latency_ms=latency_ms,
        )

        return result

    except httpx.HTTPStatusError as e:
        logger.error("Task filter HTTP error", status_code=e.response.status_code, body=e.response.text[:300])
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("Task filter parse error", error=str(e))
        return None
    except httpx.RequestError as e:
        logger.error("Task filter request failed", error=str(e))
        return None


# ── System Prompt ──────────────────────────────────────────────
# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST PROMPT ACTIVE — Original backed up in:                 ║
# ║  backend/app/services/BACKUP_ORIGINAL_SYSTEM_PROMPT.txt      ║
# ╚═══════════════════════════════════════════════════════════════╝

SYSTEM_PROMPT = """\
# IKSHAN — System Prompt v2.0
## Protocol: ReAct (Primary) + Meta-Prompting + Structured Reasoning + Chain-of-Thought

---

## ═══ LAYER 0: META-PROMPTING — PERSONA CONSTRUCTION ═══

You are a meta-prompt engine. Before you interact with any user, you must first \
**construct your operating persona** dynamically based on the inputs you receive.

### Persona Assembly Rules:

GIVEN:
  → Q1 (business outcome the user cares about)
  → Q2 (specific domain they work in)
  → Q3 (exact task they need help with)
  → knowledge_base_context (injected RAG data)

CONSTRUCT persona as:
  Name        = "Ikshan"
  Archetype   = Business diagnostic advisor
  Calibration = ₹50-lakh/year consultant depth, but plain friendly language
  Voice       = Direct, insight-first, zero fluff
  Domain Lens = Dynamically shaped by Q2 (domain) + Q3 (task)

### Dynamic Persona Shaping:

Your expertise depth and vocabulary MUST adapt based on Q2 + Q3:

| If Q2 (domain) suggests...     | Then your persona lens becomes...                          |
|--------------------------------|-----------------------------------------------------------|
| E-commerce / D2C               | Unit economics, CAC/LTV, funnel diagnostics, AOV patterns |
| SaaS / Tech                    | MRR/ARR, churn cohorts, activation metrics, PLG signals   |
| Agency / Services              | Utilization rate, pipeline velocity, scope creep patterns  |
| Content / Creator              | Repurpose ratios, engagement decay curves, monetization    |
| HealthTech / EdTech            | Retention loops, compliance signals, outcome metrics       |

You do NOT announce this persona. You simply **become** it. The user should \
feel they're talking to someone who already lives inside their domain.

---

## ═══ LAYER 1: CHAIN-OF-THOUGHT — DIAGNOSTIC REASONING ENGINE ═══

Before generating ANY question or output, you MUST run an internal reasoning \
chain. This is your thinking scaffold — it is never shown to the user, but it \
governs everything you produce.

### Pre-Question CoT Template:

For every single question you are about to ask, reason through this chain INTERNALLY:

STEP 1 — SIGNAL IDENTIFICATION
  "From the knowledge base context, the strongest diagnostic signals for \
   this task are: [list 2-3 signals]"

STEP 2 — ROOT CAUSE HYPOTHESIS
  "Based on Q1 + Q2 + Q3, the most likely root-cause cluster is: \
   [hypothesis]. Because [reasoning from patterns/data]."

STEP 3 — INFORMATION GAP
  "To confirm or eliminate this hypothesis, I need to know: \
   [specific missing information]."

STEP 4 — INSIGHT SELECTION
  "The most surprising/useful stat or pattern I can embed in this \
   question is: [insight]. This earns trust because: [reason]."

STEP 5 — QUESTION CONSTRUCTION
  "The question that fills the gap WHILE teaching the insight is: \
   [draft question]."

STEP 6 — ANTI-PATTERN CHECK
  "Does this question sound like a generic survey? [yes/no] \
   Does it GIVE before it TAKES? [yes/no] \
   Would the user learn something even if they never answered? [yes/no]"
   → If any answer is wrong, regenerate from STEP 4.

### Diagnostic Narrowing CoT (after each user response):

STEP A — OBSERVATION INTAKE
  "The user answered: [response]. This tells me: [interpretation]."

STEP B — HYPOTHESIS UPDATE
  "This [confirms / weakens / eliminates] my hypothesis about [X]. \
   Updated root-cause probability: [revised hypothesis]."

STEP C — BRANCH DECISION
  "Should I: \
   (a) Go deeper on this root cause? → need [specific data point] \
   (b) Pivot to adjacent root cause? → because [signal mismatch] \
   (c) I have enough — ready to diagnose? → because [convergence signal]"

STEP D — NEXT ACTION
  "My next action is: [generate question / deliver micro-insight / produce report]"

---

## ═══ LAYER 2: ReAct LOOP — PRIMARY EXECUTION FLOW ═══

This is the master loop that governs the entire diagnostic conversation. \
Every turn follows this cycle:

  THOUGHT  →  ACTION  →  OBSERVATION  →  (repeat)

### Phase 1: INITIALIZATION (First Turn)

THOUGHT:
  "I have Q1=[outcome], Q2=[domain], Q3=[task]. \
   Knowledge base gives me: [problem patterns], [diagnostic signals], \
   [growth opportunities], [strategies], [RCA bridge data]. \
   My goal: identify the 1-2 root causes hiding behind the user's \
   visible symptoms. I need 4-6 precision questions to get there. \
   Starting with the highest-signal diagnostic dimension."

ACTION:
  → Generate Question Set (Round 1): 2-3 wide-form diagnostic questions
  → Each question follows the STRUCTURED OUTPUT FORMAT (see Layer 3)
  → Questions should cover DIFFERENT diagnostic dimensions (not overlap)

OBSERVATION:
  → Wait for user responses

### Phase 2: DIAGNOSTIC NARROWING (Middle Turns)

THOUGHT:
  "User responded: [answers]. \
   Running CoT diagnostic narrowing (Steps A-D from Layer 1). \
   Hypothesis update: [updated root cause probability]. \
   Information still missing: [gaps]. \
   Confidence level: [low/medium/high]."

ACTION — CHOOSE ONE:
  IF questions_asked < 3:
    → You MUST generate the next precision question. Do NOT signal complete.
    → Embed a micro-insight that shows diagnostic progress

  IF questions_asked == 3 AND confidence ≥ 70%:
    → Signal "complete" with a powerful summary

  IF questions_asked == 3 AND confidence < 70%:
    → Generate 1 final cross-referencing question (max 4 total)

  IF questions_asked >= 4:
    → You MUST signal "complete" NOW. No more questions.

OBSERVATION:
  → Intake user response → Update hypothesis → Re-enter THOUGHT

### Phase 3: DIAGNOSIS DELIVERY (Final Turn)

THOUGHT:
  "Root cause identified with high confidence: [root cause]. \
   Supporting evidence from user responses: [evidence chain]. \
   Best matching strategy from knowledge base: [strategy/framework]. \
   Tool recommendations available: [if applicable]."

ACTION:
  → Deliver structured diagnostic report
  → Include: root cause, evidence, impact estimate, \
     recommended actions (prioritized), relevant tools/frameworks
  → End with retention hook: "Want me to go deeper on [specific area]?"

OBSERVATION:
  → User either exits or continues deeper
  → If continues: re-enter Phase 2 with narrower scope

### Phase 4: EXCEPTION HANDLING

IF user response is vague or one-word:
  THOUGHT: "Low-signal response. I need to reframe to extract usable data."
  ACTION: → Offer 3-4 specific options (multiple choice style) \
            with insights embedded in each option

IF user goes off-topic:
  THOUGHT: "Drift detected. Gently redirect to diagnostic path."
  ACTION: → Acknowledge briefly, then bridge back with: \
            "That connects to something important — [bridge insight] — \
             which brings us to..."

IF user asks for immediate advice (skipping diagnosis):
  THOUGHT: "User wants speed. Give a quick-win insight, then re-earn \
            permission to diagnose properly."
  ACTION: → Deliver one actionable micro-insight from knowledge base \
          → Then: "That's the quick fix. Want me to find what's actually \
             causing this? Takes 3-4 questions."

---

## ═══ LAYER 3: STRUCTURED REASONING — OUTPUT SCHEMAS ═══

Every question you generate MUST follow this exact structure. No exceptions.

### Question Output Schema:

Respond in valid JSON only:

When asking a question:
{
  "status": "question",
  "acknowledgment": "1 sentence with a data-backed observation about their previous answer (skip for first question)",
  "insight": "MAX 12 words — one punchy stat/fact/pattern",
  "question": "1-2 sentences — direct, follows from insight",
  "options": ["Specific scenario A", "Specific scenario B", "Specific scenario C", "Something else"],
  "diagnostic_intent": "internal: what root-cause dimension this probes",
  "section": "problems|rca_bridge|opportunities|deepdive",
  "section_label": "Crisp, specific label (e.g., 'Lead Response Speed')",
  "cumulative_insight": "2-3 sentence compressed summary of ALL diagnostic findings so far (including this question's answer context). This is a RUNNING SUMMARY — each turn, rewrite it to capture the full diagnostic picture up to this point. Include: confirmed root causes, eliminated hypotheses, key data points from user answers. This replaces sending full Q&A history in the next turn."
}

When diagnostic is complete:
{
  "status": "complete",
  "acknowledgment": "1 sentence power insight — their 'aha' moment",
  "summary": "1 crisp sentence only: state the root cause in under 20 words. No preamble, no teaching — just the core issue.",
  "handoff": "Structured handoff for downstream agents. 5-7 bullet points capturing: (1) confirmed root cause, (2) key constraints/blockers from user answers, (3) current tools/process gaps, (4) business stage signals, (5) what the user explicitly said matters most. This replaces raw Q&A history — downstream agents will ONLY see this, so include every insight that would change a playbook step."
}

### Field-Level Rules:

**INSIGHT field:**
- MAXIMUM 10-12 words. Hard ceiling. No full sentences.
- Must be a concrete data point, benchmark, or pattern — not a truism.

GOOD:
  "67% of leads die after 30min+ response delay."
  "Top 10% repurpose each piece into 6-8 formats."
  "73% of bottlenecks are operations, not marketing."

BAD:
  "Customer acquisition is important for growth." (truism)
  "Many businesses struggle with content marketing..." (too long, too vague)

**QUESTION field:**
- 1-2 sentences maximum
- Must flow naturally from the insight

**OPTIONS field:**
- 3-4 concrete choices
- Phrased as recognizable situations, not abstract labels
- Always include "Something else" as the last option

GOOD OPTIONS:
  "We post consistently but engagement is flat"
  "We get spikes but can't sustain traffic between launches"

BAD OPTIONS:
  "Good" / "Average" / "Bad"

---

## ═══ ANTI-PATTERNS — HARD CONSTRAINTS ═══

These override everything. If your output matches any anti-pattern, STOP and regenerate.

### HARD RULE — MINIMUM 3 QUESTIONS (OVERRIDES CONFIDENCE LEVEL)
You MUST ask EXACTLY 3 diagnostic questions. That is the target. \
Do NOT signal "complete" before asking at least 3 questions — even if your \
confidence is high. The user's earlier Q1 (outcome), Q2 (domain), Q3 (task) \
do NOT count — your count starts from YOUR first diagnostic question. \
After 3 questions, you SHOULD signal completion unless the answers were \
genuinely ambiguous and you need ONE more question. Absolute maximum is 4. \
After 4, you MUST signal completion. ONE question per response. No exceptions.

### NEVER — Interrogation Style Questions
  "What channels are you using for customer acquisition?"
  "How do you track your conversion funnel?"
WHY: Zero value exchange. User gives data and gets nothing.

### NEVER — Insight Longer Than 12 Words
WHY: If you can't make it punchy, you don't understand the data well enough.

### NEVER — Generic/Truism Insights
  "Customer retention is important."
WHY: The user already knows this. You taught them nothing.

### NEVER — More Than 3 Questions Per Turn
If you're asking 4+ questions at once, you're surveying, not diagnosing.

### ALWAYS — The "Wow" Test
Before sending ANY question, verify:
  "Would the user learn something valuable even if they never answered this question?"
If NO → rewrite until the answer is YES.

---

## ═══ ReAct EXECUTION SUMMARY ═══

TURN 1:
  [THOUGHT]  Analyze Q1+Q2+Q3 + knowledge base → identify top diagnostic dimensions
  [ACTION]   Generate question 1 — wide-form, insight-embedded (ONE question only)

TURN 2:
  [OBSERVE]  Intake user answer
  [THOUGHT]  Run CoT narrowing → update hypotheses → identify gaps
  [ACTION]   Generate question 2 — precision follow-up (you MUST ask this, do NOT signal complete)

TURN 3:
  [OBSERVE]  Intake user answer
  [THOUGHT]  Run CoT narrowing → confidence check
  [ACTION]   Generate question 3 — the power-move closer. After this, signal "complete" with summary.

TURN 4 (only if answers were genuinely ambiguous after 3 questions):
  [OBSERVE]  Final answer
  [THOUGHT]  Confirm root cause → select best strategy from knowledge base
  [ACTION]   Signal "complete" with full diagnostic summary. MUST complete here.

---

## ═══ CRITICAL OUTPUT RULE ═══

Your ENTIRE response must be a single valid JSON object. \
NO text before the JSON. NO text after the JSON. NO markdown fences. \
NO reasoning, thinking, or commentary in your output — reasoning is INTERNAL ONLY. \
The JSON must start with { and end with }. Nothing else.

Protocol Version: 2.0 | Framework: ReAct + Meta-Prompting + Structured Reasoning + CoT
Designed for: Ikshan Business Intelligence SaaS
"""


def _build_user_context(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    diagnostic_context: dict[str, Any],
    rca_history: list[dict[str, str]],
    business_profile: dict[str, str] | None = None,
    crawl_summary: dict[str, Any] | None = None,
    gbp_data: dict[str, Any] | None = None,
    filtered_context: dict[str, Any] | None = None,
    task_execution_summary: str | None = None,
    rca_running_summary: str | None = None,
) -> str:
    """Build the rich user-context message sent alongside the system prompt."""
    parts = [
        "═══ USER PROFILE ═══",
        f"Outcome they want (Q1): {outcome_label}",
        f"Business domain  (Q2): {domain}",
        f"Specific task    (Q3): {task}",
    ]

    # ── Business scale profile (from scale questions) ──────────
    if business_profile:
        parts.append("\n═══ BUSINESS PROFILE (calibrate question depth to this) ═══")
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
            parts.append(f"  • {label}: {value}")
        parts.append(
            "\n→ Use this profile to calibrate your questions. "
            "A solo pre-revenue founder needs different questions than a 50-person team doing ₹50L/mo. "
            "Reference their scale naturally — e.g., 'Since you're a solo founder…' or "
            "'With a team of 20+, the bottleneck is usually…'"
        )

    # ── Crawl / website analysis summary ───────────────────────
    if crawl_summary and crawl_summary.get("points"):
        parts.append("\n═══ WEBSITE ANALYSIS (from crawling their actual business site) ═══")
        parts.append("IMPORTANT: Reference these findings in your first 1-2 questions.")
        parts.append("This is REAL data about THEIR business — use it to make questions personal.")
        for pt in crawl_summary["points"]:
            parts.append(f"  • {pt}")
        parts.append(
            "\n→ Your first question should connect to something from their website. "
            "E.g., 'I see you're doing X on your site — [stat about X] — how is that working?'"
        )

    # ── Google Business Profile data (reviews, ratings) ────────
    if gbp_data:
        parts.append("\n═══ GOOGLE BUSINESS PROFILE DATA (real customer reviews & ratings) ═══")
        parts.append("IMPORTANT: Use this review data to ground your questions in real customer perception.")
        if gbp_data.get("business_name"):
            parts.append(f"  • Business: {gbp_data['business_name']}")
        if gbp_data.get("rating"):
            parts.append(f"  • Rating: {gbp_data['rating']} / 5 ({gbp_data.get('total_reviews', '?')} reviews)")
        if gbp_data.get("category"):
            parts.append(f"  • Category: {gbp_data['category']}")
        if gbp_data.get("address"):
            parts.append(f"  • Location: {gbp_data['address']}")
        reviews = gbp_data.get("reviews", [])
        if reviews:
            parts.append(f"\n  Top {len(reviews)} customer reviews:")
            for i, rev in enumerate(reviews[:10], 1):
                stars = rev.get("rating", "?")
                text = rev.get("text", rev.get("snippet", ""))
                if text:
                    parts.append(f"    R{i}. [{stars}★] {text[:300]}")
            parts.append(
                "\n→ Analyze the sentiment and themes across reviews. "
                "Reference specific customer praise or complaints in your questions. "
                "E.g., 'I noticed customers mention X — how are you addressing that?'"
            )

    if not diagnostic_context:
        parts.append("\n(No domain-specific context available — use your general knowledge.)")
    elif filtered_context:
        # ── Task-Filtered Context (METHOD / SPEED / QUALITY) ───
        # The Task Alignment Filter pre-categorized the most relevant
        # items from the full persona doc into 3 dimensions.
        matched_task = diagnostic_context.get("task_matched", "")
        if matched_task:
            parts.append(f"\nMatched knowledge-base task: \"{matched_task}\"")

        if task_execution_summary:
            parts.append(f"\n═══ TASK EXECUTION SUMMARY ═══")
            parts.append(task_execution_summary)

        dimension_labels = {
            "METHOD": ("HOW TO DO IT — Approach & Process", "M"),
            "SPEED": ("HOW FAST — Efficiency & Velocity", "S"),
            "QUALITY": ("HOW WELL — Outcomes & Measurement", "Q"),
        }
        for dim_key, (dim_title, prefix) in dimension_labels.items():
            items = filtered_context.get(dim_key, [])
            parts.append(f"\n═══ {dim_title} ═══")
            if items:
                for i, item in enumerate(items, 1):
                    source = item.get("source", "")
                    text = item.get("text", "")
                    source_tag = f" [{source}]" if source else ""
                    parts.append(f"  {prefix}{i}.{source_tag} {text}")
            else:
                parts.append("  (No items in this dimension — ask broader questions here)")

        parts.append(
            "\n→ Focus your questions on these 3 dimensions. "
            "Each question should probe a different dimension (METHOD/SPEED/QUALITY) "
            "to build a complete diagnostic picture."
        )
    else:
        matched_task = diagnostic_context.get("task_matched", "")
        if matched_task:
            parts.append(f"\nMatched knowledge-base task: \"{matched_task}\"")

        # ── Full context from parsed doc ───────────────────────
        full_ctx = diagnostic_context.get("full_context", {})

        # Variants — shows related phrasings of this task
        variants = full_ctx.get("variants", "")
        if variants:
            parts.append(f"\n═══ TASK VARIANTS (how people describe this task) ═══")
            parts.append(variants[:400])

        # ── Section: Real-world Problems ───────────────────────
        sections = diagnostic_context.get("sections", [])
        for sec in sections:
            key = sec.get("key", "")
            label = sec.get("label", key)
            items = sec.get("items", [])

            if key == "problems":
                parts.append(f"\n═══ REAL-WORLD PROBLEM PATTERNS (mine these for insights to teach the user) ═══")
                parts.append("Each pattern below is a teaching opportunity. Reference specific ones in your insight field.")
                for i, item in enumerate(items, 1):
                    parts.append(f"  P{i}. {item}")

            elif key == "rca_bridge":
                parts.append(f"\n═══ DIAGNOSTIC SIGNALS — YOUR INSIGHT GOLDMINE (symptom → metric → root cause area) ═══")
                parts.append("CRITICAL: Use these metrics and KPIs in your 'insight' field. Quote specific numbers.")
                rca_parsed = sec.get("rca_parsed", [])
                if rca_parsed:
                    for i, rca in enumerate(rca_parsed, 1):
                        sym = rca.get("symptom", "")
                        met = rca.get("metric", "")
                        root = rca.get("root_area", "")
                        line = f"  S{i}. \"{sym}\""
                        if met:
                            line += f" → KPI: {met}"
                        if root:
                            line += f" → Root: {root}"
                        parts.append(line)
                else:
                    for i, item in enumerate(items, 1):
                        parts.append(f"  S{i}. {item}")

            elif key == "opportunities":
                parts.append(f"\n═══ GROWTH OPPORTUNITIES (teach the user what 'good' looks like) ═══")
                parts.append("Reference these as benchmarks: 'Top performers do X…'")
                for i, item in enumerate(items, 1):
                    parts.append(f"  O{i}. {item}")

        # ── Strategies & frameworks ────────────────────────────
        strategies = diagnostic_context.get("strategies", "")
        if strategies:
            parts.append(f"\n═══ PROVEN STRATEGIES & FRAMEWORKS (name-drop these in insights) ═══")
            parts.append("When you reference a framework by name, users feel they're learning from an expert.")
            parts.append(strategies[:2000])

    # ── Previous diagnostic context (compressed) ───────────────
    if rca_history:
        num_asked = len(rca_history)
        parts.append(f"\n═══ DIAGNOSTIC PROGRESS ({num_asked} question(s) asked) ═══")

        # Use running summary if available (compressed context), else fall back to raw history
        if rca_running_summary:
            parts.append(f"CUMULATIVE FINDINGS SO FAR:\n{rca_running_summary}")
            # Only send the LATEST Q&A raw — everything else is in the summary
            latest = rca_history[-1]
            parts.append(f"\nLATEST EXCHANGE (just answered):")
            parts.append(f"  Q{num_asked}: {latest['question']}")
            parts.append(f"  A{num_asked}: {latest['answer']}")
        else:
            # First question answered — no summary yet, send raw
            for i, qa in enumerate(rca_history, 1):
                parts.append(f"  RCA-Q{i}: {qa['question']}")
                parts.append(f"  RCA-A{i}: {qa['answer']}")

        remaining = max(0, 3 - num_asked)
        if remaining > 0:
            parts.append(
                f"\n→ You have asked {num_asked} diagnostic question(s). "
                f"You MUST ask at least {remaining} more before you can signal 'complete'. "
                "Generate the NEXT question. Build on the cumulative findings above. Drill deeper. "
                "REMEMBER: The 'insight' field is MANDATORY — teach them something from the knowledge base above. "
                "The 'cumulative_insight' field is MANDATORY — rewrite the running summary to include this turn's findings."
            )
        elif num_asked == 3:
            parts.append(
                "\n→ You have asked 3 questions — that is the TARGET number. "
                "You SHOULD now signal 'complete' with a strong summary + handoff. "
                "ONLY ask a 4th question if the answers were genuinely ambiguous "
                "and you cannot pinpoint the root cause without one more question. "
                "The 'insight' field is still MANDATORY for any question you ask."
            )
        else:
            parts.append(
                "\n→ You have asked 4 questions — that is the ABSOLUTE MAXIMUM. "
                "You MUST signal 'complete' NOW with a powerful summary + handoff. "
                "Do NOT ask another question."
            )
    else:
        parts.append(
            "\n→ This is the FIRST question. Start with a compelling insight — "
            "a stat or pattern from the knowledge base that immediately "
            "makes the user think 'huh, I didn't know that.' Then ask "
            "your diagnostic question. The 'insight' field MUST contain "
            "a specific, educational teaching moment. "
            "The 'cumulative_insight' field MUST capture what Q1/Q2/Q3 already tell you about this business."
        )

    return "\n".join(parts)


async def generate_next_rca_question(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    diagnostic_context: dict[str, Any],
    rca_history: list[dict[str, str]],
    business_profile: dict[str, str] | None = None,
    crawl_summary: dict[str, Any] | None = None,
    gbp_data: dict[str, Any] | None = None,
    filtered_context: dict[str, Any] | None = None,
    task_execution_summary: str | None = None,
    rca_running_summary: str | None = None,
) -> Optional[dict[str, Any]]:
    """
    Call Claude via OpenRouter to get the next adaptive RCA question.

    Returns a dict with either:
      {"status": "question", "question": ..., "options": [...], "cumulative_insight": ..., ...}
      {"status": "complete", "summary": ..., "handoff": ...}
      None on failure (caller should fall back to static questions)
    """
    settings = get_settings()
    api_key = settings.OPENROUTER_API_KEY
    model = settings.OPENROUTER_CLAUDE_MODEL  # Sonnet — faster + reliable JSON

    if not api_key:
        logger.warning("OpenRouter API key not configured — falling back")
        return None

    user_content = _build_user_context(
        outcome, outcome_label, domain, task, diagnostic_context, rca_history,
        business_profile=business_profile,
        crawl_summary=crawl_summary,
        gbp_data=gbp_data,
        filtered_context=filtered_context,
        task_execution_summary=task_execution_summary,
        rca_running_summary=rca_running_summary,
    )

    try:
        t0 = time.monotonic()
        result = await _call_openrouter_with_retry(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            user_content=user_content,
            temperature=0.7,
            max_tokens=4000,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        content = str(result.get("message") or "")
        logger.info("RCA raw response", raw_content=content[:500] if content else "<empty>")

        if not content or not content.strip():
            logger.error("RCA model returned empty content")
            return None

        # Try direct JSON parse first, then extract JSON from text
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Model may have wrapped JSON in reasoning text — extract it
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    logger.info("Extracted JSON from wrapped response")
                except json.JSONDecodeError:
                    # Try finding the last complete JSON object
                    all_matches = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content))
                    parsed = False
                    for m in reversed(all_matches):
                        try:
                            result = json.loads(m.group())
                            if result.get("status") in ("question", "complete"):
                                logger.info("Extracted JSON from nested response")
                                parsed = True
                                break
                        except json.JSONDecodeError:
                            continue
                    if not parsed:
                        logger.error("Could not parse extracted JSON", raw=content[:500])
                        return None
            else:
                logger.error("No JSON found in response", raw=content[:500])
                return None

        # Validate expected fields
        if result.get("status") not in ("question", "complete"):
            logger.error("Unexpected Claude response status", raw=content[:300])
            return None

        # Attach metadata for context pool
        result["_meta"] = {
            "service": "openrouter",
            "model": model,
            "purpose": "rca_question",
            "system_prompt": SYSTEM_PROMPT,
            "user_message": user_content,
            "temperature": 0.7,
            "max_tokens": 900,
            "raw_response": content,
            "latency_ms": latency_ms,
        }

        logger.info(
            "Claude RCA response",
            status=result["status"],
            question=result.get("question", "")[:80],
            num_options=len(result.get("options", [])),
        )
        return result

    except httpx.HTTPStatusError as e:
        logger.error(
            "OpenRouter HTTP error",
            status_code=e.response.status_code,
            body=e.response.text[:300],
        )
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("Claude response parse error", error=str(e))
        return None
    except httpx.RequestError as e:
        logger.error("OpenRouter request failed", error=str(e))
        return None



# ══════════════════════════════════════════════════════════════
#  GAP QUESTIONS — Pre-playbook clarifying questions
# ══════════════════════════════════════════════════════════════

_GAP_QUESTIONS_PROMPT_DEFAULT = """
You are a smart intake specialist. You have been given company context and founder answers.

Your job: identify what is GENUINELY missing that would change the playbook — and ask only
those questions. Maximum 3. If you can proceed with fewer, ask fewer. 1 question is fine.
If you have enough context, return NO questions.

Rules:
— Never ask what is already answered in the context
— Only ask if the answer directly changes a playbook step
— Every question gets 4 realistic options + Option E (type your own)

Output JSON format:
{
  "questions": [
    {
      "id": "Q1",
      "label": "Short label",
      "question": "The specific question about THIS business",
      "why_matters": "One line — what shifts in the playbook based on the answer",
      "options": ["Option A text", "Option B text", "Option C text", "Option D text", "None of these — my answer is: ___"]
    }
  ]
}

If no questions are needed, return: {"questions": []}

Only return valid JSON. No markdown, no explanation outside the JSON.
""".strip()


def _parse_gap_questions_markdown(content: str) -> list[dict[str, Any]]:
    """
    Fallback parser for gap questions when LLM returns markdown instead of JSON.
    Extracts questions from format like:
      Q1 — Label: Question text
      ↳ Why this matters: reason
      A) option text
      B) option text
      ...
    """
    import re

    questions: list[dict[str, Any]] = []

    # Split by Q1, Q2, Q3 markers
    q_pattern = re.compile(r'Q(\d+)\s*[—–\-]\s*(.+?)(?=Q\d+\s*[—–\-]|$)', re.DOTALL)
    matches = q_pattern.findall(content)

    if not matches:
        # Try alternate format: just "Q1 —" without label
        q_pattern2 = re.compile(r'Q(\d+)\s*[—–\-]\s*(.+?)(?=Q\d+\s*[—–\-]|$)', re.DOTALL | re.IGNORECASE)
        matches = q_pattern2.findall(content)

    for q_num, q_content in matches:
        q_content = q_content.strip()

        # Extract label and question from first line
        first_line_match = re.match(r'^([^:?\n]+?):\s*(.+?)(?:\n|$)', q_content)
        if first_line_match:
            label = first_line_match.group(1).strip()
            question_start = first_line_match.group(2).strip()
        else:
            # No colon - first line is the question
            first_line = q_content.split('\n')[0].strip()
            label = f"Question {q_num}"
            question_start = first_line

        # Extract full question (before options or why_matters)
        question_lines = []
        why_matters = ""
        options: list[str] = []

        lines = q_content.split('\n')
        in_options = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for why_matters
            why_match = re.match(r'^[↳→]?\s*Why this matters:?\s*(.+)', line, re.IGNORECASE)
            if why_match:
                why_matters = why_match.group(1).strip()
                continue

            # Check for options A) B) C) D) E)
            opt_match = re.match(r'^([A-E])\)\s*(.+)', line)
            if opt_match:
                in_options = True
                options.append(line)
                continue

            # If not in options yet and not the first line (which has label), add to question
            if not in_options and line != lines[0].strip():
                question_lines.append(line)

        # Build question text
        question_text = question_start
        if question_lines:
            question_text = question_start + ' ' + ' '.join(question_lines)
        question_text = question_text.strip()

        # Clean up question text - remove trailing options if inline
        inline_opt = re.search(r'\s*[—–\-]?\s*A\)\s', question_text)
        if inline_opt:
            question_text = question_text[:inline_opt.start()].strip()

        if question_text:
            questions.append({
                "id": f"Q{q_num}",
                "label": label,
                "question": question_text,
                "why_matters": why_matters,
                "options": options if options else [
                    "A) Option A",
                    "B) Option B",
                    "C) Option C",
                    "D) Option D",
                    "E) None of these — my answer is: ___"
                ],
            })

    return questions[:3]


async def generate_gap_questions(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    rca_history: list[dict[str, str]],
    scale_answers: dict[str, Any] | None = None,
    web_summary: str = "",
    rca_handoff: str = "",
    rca_summary: str = "",
    onboarding_id: str = "",
) -> list[dict[str, Any]] | None:
    """
    Generate gap questions (0-3) before playbook generation.
    Returns a list of question dicts, or None on failure.
    Empty list means no additional questions needed.
    """
    settings = get_settings()
    api_key = settings.OPENROUTER_API_KEY
    model = settings.OPENROUTER_CLAUDE_MODEL  # Sonnet — faster + reliable JSON

    if not api_key:
        logger.warning("OpenRouter API key not configured — skipping gap questions")
        return None

    input_tokens = 0
    output_tokens = 0
    content = ""

    try:
        from app.services.prompts_service import get_prompt

        system_prompt = await get_prompt(
            "gap-questions",
            default=_GAP_QUESTIONS_PROMPT_DEFAULT,
        )

        user_payload = {
            "outcome": str(outcome or "").strip(),
            "outcome_label": str(outcome_label or "").strip(),
            "domain": str(domain or "").strip(),
            "task": str(task or "").strip(),
            "scale_answers": scale_answers or {},
            "web_summary": str(web_summary or "").strip(),
            "rca_history": rca_history or [],
            "rca_handoff": str(rca_handoff or "").strip(),
            "rca_summary": str(rca_summary or "").strip(),
        }
        t0 = time.monotonic()
        result = await _call_openrouter_with_retry(
            model=model,
            system_prompt=system_prompt,
            user_content=json.dumps(user_payload, ensure_ascii=True),
            temperature=0.3,
            max_tokens=1500,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        content = str(result.get("message") or "")
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)

        logger.info("Gap questions raw response", raw_content=content[:4000] if content else "<empty>")

        if not content or not content.strip():
            logger.warning("Gap questions: empty response — treating as no questions")
            if onboarding_id:
                await log_onboarding_token_usage(
                    onboarding_id=onboarding_id,
                    stage=STAGE_GAP_QUESTIONS,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=True,  # Empty response is valid (no questions needed)
                )
            return []

        # Try JSON parsing first
        questions = []
        try:
            parsed = json.loads(_extract_json_value(content))
            if isinstance(parsed, dict):
                questions = parsed.get("questions", [])
            elif isinstance(parsed, list):
                questions = parsed
        except (json.JSONDecodeError, ValueError):
            # Fallback to markdown parsing
            logger.info("Gap questions: JSON parse failed, trying markdown fallback")
            questions = _parse_gap_questions_markdown(content)
            if questions:
                logger.info("Gap questions: markdown fallback succeeded", count=len(questions))

        # Attach metadata for context pool to each question
        _meta = {
            "service": "openrouter",
            "model": model,
            "purpose": "gap_questions",
            "system_prompt": system_prompt,
            "user_message": json.dumps(user_payload, ensure_ascii=True),
            "temperature": 0.3,
            "max_tokens": 1500,
            "raw_response": content,
            "latency_ms": latency_ms,
        }
        for q in questions:
            q["_meta"] = _meta

        logger.info(
            "Gap questions generated",
            count=len(questions),
            labels=[q.get("label", "?") for q in questions],
        )

        # Log successful token usage
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_GAP_QUESTIONS,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
            )

        return questions[:3]  # Ensure max 3

    except httpx.HTTPStatusError as e:
        logger.error(
            "Gap questions HTTP error",
            status_code=e.response.status_code,
            body=e.response.text[:300],
        )
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_GAP_QUESTIONS,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=False,
                error_msg=f"HTTP {e.response.status_code}",
            )
        return None
    except (KeyError, IndexError) as e:
        logger.error("Gap questions parse error", error=str(e))
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_GAP_QUESTIONS,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=False,
                error_msg=str(e),
                raw_output=content,
            )
        return None
    except httpx.RequestError as e:
        logger.error("Gap questions request failed", error=str(e))
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_GAP_QUESTIONS,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=False,
                error_msg=str(e),
            )
        return None


_WEBSITE_AUDIT_PROMPT_DEFAULT = """\
You are a world-class conversion strategist and buyer psychologist.
You just opened this founder's website for the first time. You have never seen this business before. You are not their employee. You are the buyer.

Your job: diagnose WHAT is broken + WHY it costs them. Nothing else.

═══ INPUTS ═══
The user message is a JSON object with these fields:
  task          → USER_TASK (the specific growth goal the founder chose)
  web_summary   → CRAWL_DATA (5 pages scraped + OCR text from their website)
  scale_answers → QUESTION_ANSWERS (buying_process, revenue_model, sales_cycle,
                                    existing_assets, buyer_behavior, current_stack)
  website_url   → the website being audited
  business_profile → supplemental context (use only if crawl is thin)

Derive CRAWL_DATA_QUALITY from web_summary length:
  EMPTY   = blank or < 100 chars
  MINIMAL = 100–800 chars
  OK      = > 800 chars

═══ ABSOLUTE RULES ═══

RULE 1 — NEVER DESCRIBE WHAT THE FOUNDER ALREADY KNOWS.
  Never say: "Your company [X] does [Y]." They built it. They know.
  Never say: "You currently have [X]." Skip the setup. Go to the diagnosis.
  NEVER write corporate recaps like "CuriousJr offers online tuition..."

RULE 2 — ZERO REPETITION ACROSS SECTIONS.
  Core Disconnect says ONE thing.
  Where You Lose The Sale says DIFFERENT things.
  If "no testimonials" is in Core Disconnect → it CANNOT appear in Where You Lose.
  Each friction point must expose a DIFFERENT failure mode.

RULE 3 — EVERY FINDING = OBSERVATION + PSYCHOLOGY.
  Observation = what the BUYER sees (not what the founder has).
  Psychology = why the buyer walks away.
  Format: "The [element] says [X]. A buyer who needs [Y] reads that as [Z]."
  Not: "You have no testimonials." → That's founder-facing.
  Yes: "The hero says 'AI-Powered Platform.' A logistics buyer reads that as vague — they need 'Ship same-day across India.'"

RULE 4 — THE INVERSION TEST.
  If you can swap the company's name and the finding still works → REWRITE.
  Every finding must cite a specific element (H1, CTA text, missing element, quote).

RULE 5 — SCORING DERIVES FROM FINDINGS.
  Write Where You Lose The Sale FIRST.
  Then score. A row with a friction point above → that row ≤ 5/10.
  No crawl evidence for a row → 1–3/10.
  Overall = mathematical average, never rounded up.

═══ IF CRAWL_DATA_QUALITY = EMPTY ═══

Output only this, nothing else:

⚠️ Site could not be fully scraped (likely JS-rendered or blocked).
These are estimated observations — verify against your live site before acting.

[3 estimated friction points. Each prefixed "ESTIMATED —".]
[Derive from: task + scale_answers.]
[Max score: 4/10. No scorecard.]
STOP.

═══ IF CRAWL_DATA_QUALITY = MINIMAL or OK ═══

Output in THIS EXACT ORDER:

━━ 1. CORE DISCONNECT ━━
[2-3 sentences. The single deepest gap between what the site communicates and what the specific buyer (from scale_answers) actually needs. Must cite ONE specific element — H1, CTA, or pointed absence. This is the anchor insight. Everything downstream exposes different symptoms.]

━━ 2. BUYER'S FIRST 10 SECONDS ━━
[Exactly 3 bullets. No more. No less.]

WHO lands here: [one line — the specific buyer, their state of mind]
THEY SEE: [one line — the dominant visual/textual impression in 10 seconds]
THEY NEED: [one line — the ONE thing that would make them stay]

━━ 3. WHERE YOU LOSE THE SALE ━━
[3-5 friction points. Each exposes a DIFFERENT failure mode. Zero overlap with Core Disconnect. Zero overlap with each other.]

For each:

**[Blunt title — name the failure, not the category]** | Impact: HIGH/MED/LOW
OBSERVED: [what a buyer encounters — specific element, quote, or pointed absence from the crawl]
COST: [the psychological moment the buyer disengages. One sentence. Name the emotion — confusion, doubt, hesitation, friction.]

━━ 4. SCORECARD ━━
[Derived from Where You Lose. Scores cannot contradict findings above.]

| Check | Score | Why |
|---|---|---|
| 10-second clarity | X/10 | [H1/hero evidence] |
| Message matches buyer pain | X/10 | [copy reference] |
| Proof of results | X/10 | [testimonials/cases/numbers or absence] |
| Low-friction next step | X/10 | [CTA evidence] |
| Trust to act | X/10 | [trust signals or absence] |
| **OVERALL** | **X/10** | |

━━ 5. FIX RIGHT NOW (ZERO DEV WORK) ━━
[ONE change the founder can make today in their CMS. Name the exact element → exact replacement text → one-line why this first. Must be editable without code.]

━━ 6. THE ONE THING ━━
[One sentence. The single most important unlock. Different from Fix Right Now — this is strategic, not tactical. Make it sting. Make it true. Make them want to act.]

═══ VOICE ═══
Sharp friend who just opened their site. Not consultant. Not report.
No jargon: leverage, optimize, synergize, scale, robust, streamline.
Short sentences. Active voice. No hedging.
Every claim = evidence. Every evidence = specific crawl element.
"""


async def _persist_website_audit_log(
    *,
    onboarding_id: str | None,
    model: str,
    system_prompt: str,
    user_payload: dict,
    output: str,
    success: bool,
    error_msg: str | None,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> None:
    """Fire-and-forget: write one row to website_audit_logs. Never raises."""
    try:
        from app.db import get_pool
        from app.repositories import website_audit_logs_repository as audit_log_repo

        input_payload = {
            "system_prompt": system_prompt,
            "user_payload": user_payload,
        }
        pool = get_pool()
        async with pool.acquire() as conn:
            await audit_log_repo.insert_log(
                conn,
                onboarding_id=onboarding_id,
                model=model,
                input_payload=input_payload,
                output=output,
                success=success,
                error_msg=error_msg,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
    except Exception as _log_err:
        logger.warning("website_audit_log_persist_failed", error=str(_log_err))


async def generate_website_audit(
    *,
    outcome: str,
    domain: str,
    task: str,
    website_url: str = "",
    scale_answers: dict | None = None,
    rca_history: list[dict] | None = None,
    rca_summary: str = "",
    rca_handoff: str = "",
    pages_markdown: list[dict] | None = None,
    onboarding_id: str | None = None,
    on_token=None,
) -> str | None:
    """
    Generate a website audit using the 'website-audit' DB prompt.
    Pass on_token callback to stream tokens; otherwise returns the full text.
    Returns the audit text string, or None on failure.
    pages_markdown: list of {"url": str, "markdown": str} dicts from scraped_pages.
    """
    from app.config import get_settings
    from app.services.token_usage_service import log_onboarding_token_usage, STAGE_WEBSITE_AUDIT

    settings = get_settings()
    api_key = getattr(settings, "OPENROUTER_API_KEY", None)
    model = settings.OPENROUTER_CLAUDE_MODEL

    if not api_key:
        logger.warning("OpenRouter API key not configured — skipping website audit")
        return None

    input_tokens = 0
    output_tokens = 0
    content = ""
    latency_ms = 0
    system_prompt = ""
    user_payload: dict = {}

    try:
        from app.services.prompts_service import get_prompt

        system_prompt = await get_prompt(
            "website-audit",
            default=_WEBSITE_AUDIT_PROMPT_DEFAULT,
        )

        user_payload = {
            "outcome": str(outcome or "").strip(),
            "domain": str(domain or "").strip(),
            "task": str(task or "").strip(),
            "website_url": str(website_url or "").strip(),
            "scale_answers": scale_answers or {},
            "rca_history": rca_history or [],
            "rca_summary": str(rca_summary or "").strip(),
            "rca_handoff": str(rca_handoff or "").strip(),
            "scraped_pages": pages_markdown or [],
        }

        t0 = time.monotonic()

        if on_token is not None:
            # Streaming mode
            result = await _ai.complete_stream(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
                ],
                temperature=0.4,
                max_tokens=2800,
                on_token=on_token,
            )
        else:
            result = await _call_openrouter_with_retry(
                model=model,
                system_prompt=system_prompt,
                user_content=json.dumps(user_payload, ensure_ascii=True),
                temperature=0.4,
                max_tokens=2800,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)

        content = str(result.get("message") or "").strip()
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)

        logger.info("Website audit generated", length=len(content), latency_ms=latency_ms)

        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_WEBSITE_AUDIT,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
            )

        # Log call for admin inspection
        await _persist_website_audit_log(
            onboarding_id=onboarding_id,
            model=model,
            system_prompt=system_prompt,
            user_payload=user_payload,
            output=content,
            success=True,
            error_msg=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

        return content or None

    except Exception as e:
        logger.error("Website audit generation failed", error=str(e))
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_WEBSITE_AUDIT,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=False,
                error_msg=str(e),
                raw_output=content,
            )

        # Log failed call for admin inspection
        await _persist_website_audit_log(
            onboarding_id=onboarding_id,
            model=model,
            system_prompt=system_prompt,
            user_payload=user_payload,
            output=content,
            success=False,
            error_msg=str(e),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

        return None


_WEB_SUMMARY_PROMPT = """\
You extract the parts of a website crawl that are RELEVANT to the user's chosen growth task. Everything else is noise.

═══ INPUTS ═══
The user message is a JSON object with these fields:
  task             → USER_TASK (the specific growth goal)
  crawl_data       → FULL_CRAWL (5 pages, OCR, elements, links)
  business_profile → BUSINESS_MODEL / stage context
  outcome          → the broader goal category
  domain           → the company's domain

═══ YOUR JOB ═══
Extract ONLY what matters for solving the USER_TASK.
Discard everything else. The output feeds the RCA prompt.
Smaller and sharper > larger and fuller.

═══ RELEVANCE RULES ═══

KEEP if the element affects the USER_TASK:
  Task = "Generate leads"          → keep CTAs, forms, lead magnets, contact flow, pricing, trust signals. Discard blog topics, team bios.
  Task = "Improve ad ROAS"         → keep landing page message match, value prop, pricing, social proof. Discard careers, privacy policy.
  Task = "Get more from same customer" → keep product catalog, upsell hooks, post-purchase signals, email capture. Discard acquisition CTAs.
  Task = "Automate support"        → keep FAQ, support links, chat widgets, contact options, policy pages. Discard marketing pages.
  Task = "Hire faster"             → keep careers page, team signals, culture copy, hiring process. Discard product features, pricing.
  Task = "Trial-to-paid conversion" → keep pricing page, upgrade CTAs, free tier limits, social proof, ROI signals. Discard blog, team bios.

If unsure whether something is relevant → include it ONLY if it changes what the RCA would ask. Otherwise discard.

═══ OUTPUT FORMAT ═══

Return compact JSON. No prose, no commentary outside the JSON.

{
  "task": "[USER_TASK — copy exactly]",
  "business_snapshot": {
    "model": "[B2B SaaS / D2C / Service / Marketplace / Hybrid]",
    "stage": "[Pre-revenue / Early / Growth / Established]",
    "sells": "[one sentence — what they actually sell]",
    "buyer": "[specific role + company type]"
  },
  "task_relevant_signals": {
    "what_exists": [
      "[specific element + its current state — only if affects USER_TASK]"
    ],
    "what_is_missing": [
      "[specific missing element + why it matters for USER_TASK]"
    ],
    "what_contradicts": [
      "[founder claims X in answers, site shows Y — only if task-relevant]"
    ]
  },
  "audit_anchor": "[one line — the deepest gap between site messaging and buyer need, for this task]",
  "rca_direction": "[one line — what the RCA should probe based on the above]"
}

═══ QUALITY TEST ═══
Before returning: could a growth specialist who has never seen this business generate 3 sharp diagnostic questions from ONLY this summary? If no, add what is missing. If yes, return it.
"""


async def generate_web_summary_llm(
    *,
    raw_web_summary: str,
    outcome: str,
    domain: str,
    task: str,
    business_profile: str = "",
    onboarding_id: str | None = None,
) -> str | None:
    """
    Generate a focused, task-contextualized web summary from raw crawl data.
    Stored back to onboarding.web_summary and used by RCA and playbook generators.
    """
    from app.config import get_settings
    from app.services.token_usage_service import log_onboarding_token_usage, STAGE_WEB_SUMMARY

    settings = get_settings()
    api_key = getattr(settings, "OPENROUTER_API_KEY", None)
    model = settings.OPENROUTER_CLAUDE_MODEL

    if not api_key:
        logger.warning("OpenRouter API key not configured — skipping web summary generation")
        return None

    if not raw_web_summary.strip():
        logger.info("No raw web summary to process — skipping web summary generation")
        return None

    input_tokens = 0
    output_tokens = 0
    content = ""

    try:
        user_payload = {
            "outcome": str(outcome or "").strip(),
            "domain": str(domain or "").strip(),
            "task": str(task or "").strip(),
            "business_profile": str(business_profile or "").strip(),
            "crawl_data": str(raw_web_summary or "").strip(),
        }

        t0 = time.monotonic()
        result = await _call_openrouter_with_retry(
            model=model,
            system_prompt=_WEB_SUMMARY_PROMPT,
            user_content=json.dumps(user_payload, ensure_ascii=True),
            temperature=0.2,
            max_tokens=1200,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        content = str(result.get("message") or "").strip()
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)

        logger.info("Web summary generated", length=len(content), latency_ms=latency_ms)

        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_WEB_SUMMARY,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
            )

        return content or None

    except Exception as e:
        logger.error("Web summary generation failed", error=str(e))
        if onboarding_id:
            await log_onboarding_token_usage(
                onboarding_id=onboarding_id,
                stage=STAGE_WEB_SUMMARY,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=False,
                error_msg=str(e),
                raw_output=content,
            )
        return None
