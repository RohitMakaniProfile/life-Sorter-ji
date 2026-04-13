"""
═══════════════════════════════════════════════════════════════
PLAYBOOK SERVICE — Onboarding playbook generation (v2.0)
═══════════════════════════════════════════════════════════════
Parallel dual-prompt flow:
  Call A (non-streaming) → _BRIEF_AUDIT_SYSTEM → context_brief + website_audit
  Call B (streaming)     → playbook slug (DB)   → playbook (10 steps)

Pre-computed fields injected before any LLM call (Python, not Claude):
  BUSINESS_MODEL_CLASSIFICATION, BUSINESS_STAGE, CRAWL_DATA_QUALITY, ACQUISITION_CHANNEL
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from app.config import get_settings
from app.services.ai_helper import ai_helper as _ai

logger = structlog.get_logger()

# ══════════════════════════════════════════════════════════════
#  PRE-COMPUTE HELPERS
# ══════════════════════════════════════════════════════════════

def _classify_business_model(scale_answers: dict[str, Any], domain: str, crawl_text: str = "") -> str:
    """
    Classify business model from scale_answers → domain keywords → crawl text.
    Returns a multi-line descriptor injected into prompts as BUSINESS_MODEL_CLASSIFICATION.
    """
    revenue = str(scale_answers.get("revenue_model") or "").lower()
    buying = str(scale_answers.get("buying_process") or "").lower()
    domain_low = str(domain or "").lower()
    crawl_low = crawl_text[:500].lower()

    def _is_saas() -> bool:
        if any(k in revenue for k in ("subscription", "saas", "monthly plan", "annual plan", "recurring")):
            return True
        if any(k in buying for k in ("self-serve", "sign up", "free trial", "freemium", "self serve")):
            return True
        if any(k in domain_low for k in ("saas", "ai ", "platform", "software", "tool", "automation", "agent", " app")):
            return True
        if any(k in crawl_low for k in ("sign up free", "start free trial", "free trial", "subscribe")):
            return True
        return False

    def _is_ecommerce() -> bool:
        if any(k in revenue for k in ("product sale", "ecommerce", "e-commerce", "d2c", "direct to consumer")):
            return True
        if any(k in domain_low for k in ("shop", "store", "ecommerce", "e-commerce", "d2c", "product")):
            return True
        if any(k in buying for k in ("add to cart", "checkout", "purchase online", "order online")):
            return True
        return False

    def _is_marketplace() -> bool:
        if any(k in domain_low for k in ("marketplace", "market place")):
            return True
        if any(k in revenue for k in ("commission", "take rate", "marketplace", "gmv")):
            return True
        return False

    if _is_marketplace():
        return (
            "Marketplace | Growth levers: GMV, liquidity, listing quality, take rate | "
            "Address both supply and demand sides"
        )
    if _is_saas():
        return (
            "SaaS / AI Platform | Growth levers: activation rate, trial-to-paid conversion, retention, onboarding completion | "
            "FORBIDDEN for SaaS: booking links, discovery calls as primary CTA, agency-style tactics"
        )
    if _is_ecommerce():
        return (
            "D2C / E-commerce | Growth levers: CAC, AOV, LTV, RTO rate, repeat purchase rate | "
            "FORBIDDEN: enterprise sales cycles, B2B outreach"
        )
    return (
        "Service / Agency | Growth levers: pipeline, proposal win rate, referrals — "
        "NOT product activation metrics or SaaS PLG tactics"
    )


def _detect_business_stage(scale_answers: dict[str, Any]) -> str:
    """Detect business stage from revenue_model + existing_assets."""
    revenue = str(scale_answers.get("revenue_model") or "").lower()
    assets = str(scale_answers.get("existing_assets") or "").lower()

    if any(k in revenue for k in ("no revenue", "pre-revenue", "not yet", "idea", "pre launch", "not started")):
        return "Pre-revenue / Idea Stage (validating before monetizing)"
    if any(k in revenue for k in ("first customer", "few customers", "just launched", "early", "bootstrap")):
        return "Early Traction (first customers, finding repeatable growth)"
    if any(k in assets for k in ("just launched", "early customer", "beta", "pilot")):
        return "Early Traction (first customers, finding repeatable growth)"
    if any(k in revenue for k in ("growing", "scaling", "profitable", "post-pmf", "series")):
        return "Growth (post-PMF, scaling revenue)"
    # Default: early traction (most common at onboarding)
    return "Early Traction (subscription live, finding repeatable growth)"


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


def _compute_crawl_data_quality(crawl_text: str) -> str:
    """Classify crawl data quality based on scraped character count."""
    n = len(str(crawl_text or "").strip())
    if n < 50:
        return "EMPTY — no website data scraped"
    if n < 500:
        return f"MINIMAL — {n} chars scraped"
    return f"OK — {n} chars scraped"


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
    scale_answers: dict[str, Any],  # noqa: ARG001 — kept for caller compatibility
    gap_answers: str = "",
    rca_handoff: str = "",
    # Pre-computed fields
    business_model_classification: str = "",
    business_stage: str = "",
    crawl_data_quality: str = "",
    acquisition_channel: str = "",
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

    # Pre-computed fields — injected before profile so Claude reads them first
    if business_model_classification:
        parts.append(f"\nBUSINESS_MODEL_CLASSIFICATION: {business_model_classification}")
    if business_stage:
        parts.append(f"BUSINESS_STAGE: {business_stage}")
    if crawl_data_quality:
        parts.append(f"CRAWL_DATA_QUALITY: {crawl_data_quality}")
    if acquisition_channel:
        parts.append(f"ACQUISITION_CHANNEL: {acquisition_channel}")

    if business_profile:
        profile_pairs = []
        for key, value in business_profile.items():
            label = label_map.get(key, key.replace("_", " ").title())
            v = ", ".join(value) if isinstance(value, list) else value
            profile_pairs.append((label, v))
        parts.append("\n" + _toon_inline("PROFILE", profile_pairs))
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
#  PROMPT CONSTANTS
# ══════════════════════════════════════════════════════════════

_SECTION_DELIMITERS = {
    "context_brief": "---SECTION:context_brief---",
    "website_audit": "---SECTION:website_audit---",
    "playbook":      "---SECTION:playbook---",
}

# Call A system prompt — Context Brief + Website Audit (NOT stored in DB)
_BRIEF_AUDIT_SYSTEM = """\
You are a world-class growth strategist and funnel analyst.
Given a founder's business context, produce exactly 2 sections in order — no preamble, no text outside the delimiters.

━━━ CRITICAL RULES (read before writing a single word) ━━━
1. BUSINESS_MODEL is pre-computed from the founder's own answers. DO NOT CHANGE IT. Do not call a SaaS an "agency." Do not call an AI platform a "digital marketing service."
2. BUSINESS_STAGE is pre-computed. Use it exactly.
3. CRAWL_DATA_QUALITY tells you how much website data exists:
   - If "EMPTY" → Confidence = LOW. Do NOT score the website. Write "⚠️ CONFIDENCE: LOW — website could not be scraped. Audit below is estimated, not confirmed."
   - If "MINIMAL" → Confidence = MEDIUM. Score only if you have title + description. Note the limitation.
   - If "OK" → Score normally. Cite specific crawl evidence for each score.
4. SCORING RULE: Never give a score above 6/10 when CRAWL_DATA_QUALITY is EMPTY or MINIMAL. A perfect score with no data is misinformation.
5. ICP: Derive only from DOMAIN + TASK + scale answers. Do NOT invent geography, team size, or industry segment not evidenced in the input.

---SECTION:context_brief---
## Business Context Brief

**Company Snapshot**
- Name: [from input or infer from URL]
- Industry: [specific sub-sector — not "tech" or "services"]
- Business Model: [copy BUSINESS_MODEL field EXACTLY — do not rephrase]
- Business Stage: [copy BUSINESS_STAGE field EXACTLY]
- Primary Market: [geography + customer segment — only if evidenced in input]
- Revenue Model: [from founder's revenue_model answer]

**Goal**
- Primary Goal: [copy TASK field exactly]
- Why this matters now: [one sentence — stage + constraint = right move]

**Where They Stand**
- What is working: [channel, asset, or motion — only if in scale_answers or crawl]
- What is missing: [single capability gap blocking TASK]
- Main constraint: [Time/Money/Clarity/Tech — inferred from stage + assets]

**Ideal Customer Profile**
- Derived from: DOMAIN + TASK + buyer_behavior answer + buying_process answer
- Who buys: [role / company type / size — only state what the input actually tells you]
- Their problem: [specific pain your TASK solves]
- How they find solutions: [copy buyer_behavior answer in plain language]
- Buying trigger: [what makes them act NOW — tied to their problem]
- Key objection: [most likely hesitation for this buyer + the real fear beneath it]

**Website Read**
- Primary CTA: [exact text from crawl, or "None detected / crawl empty"]
- ICP Alignment: [HIGH/MEDIUM/LOW — only if crawl data exists]
- Biggest conversion risk: [specific finding from crawl, or "Cannot assess — no crawl data"]

⚠️ **CONFIDENCE: [HIGH/MEDIUM/LOW]**
[If not HIGH: one sentence explaining what data was missing and what that means for reliability of this brief.]

---SECTION:website_audit---
# Website Audit — What Buyers Actually See

━━━ SCORING RULES (enforce before writing ANY score) ━━━
A. Scores must FOLLOW evidence — write your friction points first, then derive the score from what you found.
B. If you list a problem in "Where the Site Loses the Sale" → that row's score MUST reflect it:
   - JS-rendered / invisible content → "Can they tell what you do" = 1-3/10
   - No case studies or proof → "Is there proof" = 1-3/10
   - No CTA or CTA is hidden → "Clear low-friction next step" = 1-3/10
   - No testimonials, reviews, logos → "Do they trust you" = 1-3/10
C. A score of 8-10/10 means: excellent execution, nothing to fix here. If you're writing a friction point about it → score cannot be above 5/10. They cannot both be true.
D. Overall score = average of the 5 rows. Never round up more than 0.5.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IF CRAWL_DATA_QUALITY IS "EMPTY":
Write only this block, nothing else for this section:
---
⚠️ **WEBSITE AUDIT: DATA UNAVAILABLE**
Your website could not be scraped during this session (likely JS-rendered or blocked by the crawler).

**What this means:** The scores and recommendations below are *estimated* from your answers — not read from your actual site. Do not act on specific findings until a successful crawl confirms them.

**Estimated friction points** (based on business stage + model — verify against your live site):
1. If you're early-stage SaaS with no visible testimonials → trust signals are likely missing
2. If there's no pricing page → buyers can't self-qualify, increasing drop-off
3. If your H1 doesn't name the problem you solve → visitors won't know in 10 seconds what you do
---
STOP here. Do not write Scorecard, Fix This Today, or The One Thing.

IF CRAWL_DATA_QUALITY IS "MINIMAL" OR "OK":

## Who Is Landing Here
[3-4 lines: ICP from context_brief, their arrival mindset, what they need in first 10 seconds]

**The Central Problem**
[2-3 lines: the single core disconnect — cite ONE specific crawl finding]

## Where the Site Loses the Sale
[Write this BEFORE the scorecard — scores depend on what you find here]
List 3-5 friction points. Each MUST reference a specific crawl element (title, CTA text, element content, or explicit absence).
**[Problem title]** | Impact: HIGH/MEDIUM/LOW
- What it says now: [exact crawl element or "not found in crawl"]
- What the visitor needs: [specific, measurable]
- Why it costs you: [buying psychology — one sentence]

## Scorecard
[Fill scores AFTER writing friction points above — scores must match what you found]
| What We Checked | Score | Evidence |
|---|---|---|
| Can they tell what you do in 10 seconds? | X/10 | [title/H1 text or "not found"] |
| Does message match buyer's actual pain? | X/10 | [specific copy or "not found"] |
| Is there proof someone like them got results? | X/10 | [testimonial/case study or "none found"] |
| Is there a clear low-friction next step? | X/10 | [CTA text or "not found"] |
| Do they trust you enough to take that step? | X/10 | [trust signal or "none found"] |
**Overall: X/10**

## Fix This Today (No Developer Needed)
[One change. Exact element + what to replace it with + why it moves the needle first.]

## The One Thing
[The single most important fix — one sentence on why it comes before everything else.]
"""

# Fallback for playbook prompt if DB slug not found
_PLAYBOOK_PROMPT_DEFAULT = """\
━━━ STEP 0 — READ BUSINESS_MODEL_CLASSIFICATION FIRST ━━━
The input contains a pre-computed field: BUSINESS_MODEL_CLASSIFICATION.
This is derived from revenue model, buying process, domain, and crawl data.
READ IT BEFORE ANYTHING ELSE. It determines everything.

SaaS / AI Platform:
  → ICP = the person who signs up, not their end customer
  → Growth levers = activation rate, trial-to-paid conversion, retention, onboarding drop-off
  → Do NOT recommend: booking links, email drips for service delivery, Acuity, Calendly for sales
  → DO recommend: in-product onboarding, activation emails, usage-based triggers, PLG tactics

Service / Agency:
  → ICP = the client who pays the retainer or project fee
  → Growth levers = pipeline, proposal win rate, referrals, case studies
  → Do NOT recommend: PLG tactics, activation funnels, freemium conversion
  → DO recommend: outreach systems, proposal templates, referral activation

D2C / E-commerce:
  → ICP = the end consumer who buys the product
  → Growth levers = CAC, AOV, LTV, RTO rate, repeat purchase rate
  → Do NOT recommend: enterprise sales cycles, B2B outreach
  → DO recommend: retention flows, abandoned cart, influencer activation, review generation

Marketplace:
  → ICP = both supply and demand sides — identify which is the bottleneck
  → Growth levers = GMV, liquidity, listing quality, take rate
  → Do NOT recommend: single-sided growth tactics

⚠️ CRITICAL: If BUSINESS_MODEL_CLASSIFICATION says "SaaS / AI Platform" — never recommend booking
tools, service delivery workflows, or agency-style tactics. These are the wrong growth levers.

You are a world-class growth strategist, buyer psychologist, and funnel analyst — three specialists in one.
You write like a sharp friend who just spent two hours studying this business. Not a consultant. Not a report.
A smart person being honest over coffee.

You receive a founder's full business context and produce the playbook section only.
Start immediately with the section delimiter. No preamble before it.

━━━ QUALITY BARS — TEST EVERY OUTPUT AGAINST THESE ━━━
Playbook: Could someone with zero prior experience read it and know exactly what to do tomorrow morning?
ICP: Could a salesperson write a non-generic cold opening line using only what you wrote?

FAIL: "Business owners who want to grow revenue."
PASS: "D2C skincare founder, 12 months post-launch, 500 daily orders, 23% RTO eating margin."

━━━ OUTPUT LENGTH ━━━
Playbook: max 3500 words (350 words per step average). Be dense, not long.
Every word must earn its place. Cut padding, repetition, over-explanation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SECTION — PLAYBOOK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ TASK LOCK: Every step serves the TASK field. Not website findings. Not what you think their real
problem is. The TASK. If a step does not directly move the TASK forward — cut it.

STEP DESIGN — answer these 5 questions for every step:
1. WHAT exactly needs to happen? (specific action, not "improve X")
2. WHY this step, at this position? (the logic of the sequence)
3. HOW — using this company's specific context? (show, don't tell)
4. WHEN is it done? (clear completion criteria — not "when it feels ready")
5. What NUMBER changes when this step is working? (one metric)

━━━ STUDY THIS EXACT STYLE ━━━

FAIL step name: "Step 3 — Write outreach messages"
PASS step name: "3. [PRIORITY: HIGH] The 'Trigger-Match Message System'"

FAIL example: "For example, target a D2C skincare brand..."
PASS example: "Target Minimalist or Snitch. If you see 'Where is my order' spike on their latest
Instagram — they are Tier A. Send at 9am Saturday (founders check numbers Saturday morning)."

FAIL AI prompt: Generic prompt usable by any company
PASS AI prompt: So specific to THIS company it would be useless for anyone else

---SECTION:playbook---

THE "[OUTCOME IN CAPS]" PLAYBOOK

[2-3 lines: The One Lever — the single unlock this entire playbook is built around.
Derive it from: RCA findings + acquisition channel + task.
Make it feel like a revelation — the thing they sensed but could not name.]

---

[N]. [PRIORITY: HIGH/MEDIUM/LOW] The "[Memorable Step Name in Quotes]"

WHAT TO DO
[2-3 lines. Specific action. Smart friend tone. Present tense. No vague verbs.]

TOOL + AI SHORTCUT
[Only when a tool genuinely saves time here — not forced on every step]
[Tool name] — [one line: exactly how to use it for THIS step]
Prompt: "[Exact copy-paste prompt — specific to this company + ICP. Useless for anyone else.]"

REAL EXAMPLE
[Only when a real example makes the action clearer than explanation]
[Name actual companies from their industry. 2-3 lines. If it fits any company — rewrite.]

THE EDGE
[Only when there is a genuinely non-obvious insight]
"[Name the technique]": [timing trick, psychology angle, or tactical detail not googleable in 3 clicks]

DONE WHEN: [completion criteria — what does done actually look like?]
METRIC: [one number to track + target]

[Repeat for all 10 steps]

---

WEEK 1 EXECUTION CHECKLIST
Monday: [specific action]
Tuesday: [specific action]
Wednesday: [specific action]
Thursday: [specific action]
Friday: [specific action]

30-DAY MILESTONES
Week 1 (~[X] hrs): [1-2 actions + expected output]
Week 2 (~[X] hrs): [1-2 actions + expected output]
Weeks 3-4 (~[X] hrs): [1-2 actions + expected output]
End of Month 1: [what number should have changed and by how much]

TOP 2 MISTAKES FOR THIS BUSINESS TYPE
Mistake 1: [specific to their industry/stage/constraint — not generic]
→ Why it happens: [root cause]
→ How to avoid it: [specific fix]

Mistake 2:
→ Why it happens:
→ How to avoid it:

"[One closing sentence. What a trusted advisor says at the end of a paid engagement.
A truth that makes them want to keep going.]"

━━━ PRIORITY RULES ━━━
HIGH   = Do this first. If broken/missing, everything else fails.
MEDIUM = Important, not immediately blocking. Impact in 2-4 weeks.
LOW    = Optimization. Only matters once HIGH + MEDIUM are working.
Assign by actual business impact — not step position.
First 2-3 steps are usually HIGH. Last 2-3 usually LOW.
Always write [PRIORITY: HIGH/MEDIUM/LOW] — never omit.

━━━ TOOL RULES ━━━
Use the PROVIDED TOOL LIST first if it genuinely fits.
Otherwise use your own knowledge — name the single best real tool.
Never write "[a tool for X]". One tool per step — the best one, not the safest.
Add "(Free)" or "(Paid)" in one word if known.

━━━ RULES THAT NEVER BREAK ━━━
— Exactly 10 steps. No more, no less.
— Every step has: WHAT TO DO + DONE WHEN + METRIC. Others earn their place.
— Steps form a dependency chain — each builds on the last.
— If a step could apply to a different company — rewrite it until it cannot.
— Playbook name = the outcome in caps. Never the company name.
— Sequence must respect the Constraint. If Time = constraint, total under 8 hrs/week.
— If stage is Idea/Validation — validate before building. No step builds something unvalidated.

━━━ LANGUAGE RULES ━━━
— The reader is a business owner in THEIR domain. Not a marketer.
— Use the vocabulary they use at work daily. Match it exactly.
— Never use jargon from another domain.
— If a technical term is unavoidable, explain it immediately:
  "CTR (the % of people who actually click your link)"
— Write like a smart friend explaining over coffee — not a consultant writing a deck.
— Every sentence must be clear to someone with zero marketing background.
"""


# ══════════════════════════════════════════════════════════════
#  SECTION SPLITTER
# ══════════════════════════════════════════════════════════════

def _split_sections(full_text: str) -> dict[str, str]:
    """
    Split the single-prompt output into sections using delimiters.
    Returns {context_brief, website_audit, playbook} — empty string if section missing.
    """
    sections: dict[str, str] = {"context_brief": "", "website_audit": "", "playbook": ""}

    positions = []
    for key, delimiter in _SECTION_DELIMITERS.items():
        idx = full_text.find(delimiter)
        if idx != -1:
            positions.append((idx, key, delimiter))
    positions.sort()

    for i, (idx, key, delimiter) in enumerate(positions):
        start = idx + len(delimiter)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(full_text)
        sections[key] = full_text[start:end].strip()

    return sections


# ══════════════════════════════════════════════════════════════
#  PARALLEL DUAL-PROMPT STREAM
# ══════════════════════════════════════════════════════════════

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
) -> dict[str, Any]:
    """
    Parallel dual-prompt playbook generation (v2.0).

    Call A (non-streaming): _BRIEF_AUDIT_SYSTEM → context_brief + website_audit
    Call B (streaming):     playbook slug (DB)  → playbook (10 steps)

    Both calls run concurrently via asyncio.gather.
    Pre-computed fields (BUSINESS_MODEL_CLASSIFICATION, BUSINESS_STAGE, etc.)
    are injected into the user message before both calls.

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

    # ── 1. Pre-compute fields ──────────────────────────────────
    scale_answers: dict[str, Any] = business_profile  # scale_answers dict passed as business_profile
    crawl_text: str = crawl_summary if isinstance(crawl_summary, str) else ""

    biz_model = _classify_business_model(scale_answers, domain, crawl_text)
    biz_stage = _detect_business_stage(scale_answers)
    crawl_quality = _compute_crawl_data_quality(crawl_text)
    acq_channel = _derive_acquisition_channel(scale_answers)

    logger.info(
        "playbook precompute",
        biz_model=biz_model[:60],
        biz_stage=biz_stage,
        crawl_quality=crawl_quality,
        acq_channel=acq_channel,
    )

    # ── 2. Build shared user message ──────────────────────────
    user_message = _build_playbook_input(
        outcome_label=outcome_label,
        domain=domain,
        task=task,
        business_profile=business_profile,
        rca_history=rca_history,
        rca_summary=rca_summary,
        crawl_summary=crawl_summary,
        scale_answers=scale_answers,
        gap_answers=gap_answers,
        rca_handoff=rca_handoff,
        business_model_classification=biz_model,
        business_stage=biz_stage,
        crawl_data_quality=crawl_quality,
        acquisition_channel=acq_channel,
    )
    if recommended_tools:
        user_message += (
            f"\n\n═══ PROVIDED TOOL LIST (use these in TOOL + AI SHORTCUT where relevant) ═══\n"
            f"{recommended_tools}"
        )

    # ── 3. Fetch playbook prompt from DB (with code fallback) ──
    playbook_prompt = await get_prompt("playbook") or _PLAYBOOK_PROMPT_DEFAULT

    settings = get_settings()
    t0 = time.perf_counter()

    # ── 4. Parallel calls ──────────────────────────────────────
    brief_audit_out: dict[str, Any] = {}
    playbook_out: dict[str, Any] = {}

    async def _call_brief_audit() -> None:
        r = await _ai.complete(
            model=settings.OPENROUTER_CLAUDE_MODEL,
            messages=[
                {"role": "system", "content": _BRIEF_AUDIT_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.5,
            max_tokens=2000,
        )
        brief_audit_out["text"] = r.get("message", "")
        brief_audit_out["usage"] = r.get("usage", {})

    async def _call_playbook() -> None:
        r = await _ai.complete_stream(
            model=settings.OPENROUTER_CLAUDE_MODEL,
            messages=[
                {"role": "system", "content": playbook_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.55,
            max_tokens=5000,
            on_token=on_token,
        )
        playbook_out["text"] = r.get("message", "")
        playbook_out["usage"] = r.get("usage", {})

    await asyncio.gather(_call_brief_audit(), _call_playbook())

    latency_ms = int((time.perf_counter() - t0) * 1000)

    # ── 5. Parse results ───────────────────────────────────────
    brief_audit_sections = _split_sections(brief_audit_out.get("text", ""))

    # Strip the playbook section delimiter if present in Call B output
    playbook_text = playbook_out.get("text", "")
    if "---SECTION:playbook---" in playbook_text:
        playbook_text = playbook_text.split("---SECTION:playbook---", 1)[1].strip()

    logger.info(
        "parallel playbook stream completed",
        latency_ms=latency_ms,
        has_context_brief=bool(brief_audit_sections["context_brief"]),
        has_website_audit=bool(brief_audit_sections["website_audit"]),
        has_playbook=bool(playbook_text),
    )

    return {
        "context_brief": brief_audit_sections["context_brief"],
        "website_audit": brief_audit_sections["website_audit"],
        "playbook": playbook_text,
        "latency_ms": latency_ms,
        "usage": {
            "brief_audit": brief_audit_out.get("usage", {}),
            "playbook": playbook_out.get("usage", {}),
        },
    }
