# Playbook Single LLM Call — Proposal

## Current vs Proposed

| | Current (3 calls) | Single call |
|---|---|---|
| LLM calls | 3 | 1 |
| Streaming | Agent C only | Whole response (frontend splits by delimiter) |
| Cost | ~18,000 tokens total | ~10,000–12,000 tokens |
| Latency | ~8–10s (parallel A+E → C) | ~6–8s (single stream) |
| Agent A feeds Agent C | Yes (explicit hand-off) | Yes (same context window) |
| Agent C sees Agent E output | No | Yes |
| Independent retry per agent | Yes | No |

---

## Why It Works

The `FINAL_PHASE2_REPORT_CONTEXT.md` report uses the exact same pattern — one prompt, strict output order, multiple deep sections. The key difference here is we add **section delimiters** so the frontend can split the stream into 3 tabs without waiting for the full response.

**Added benefit:** Agent C currently never sees Agent E's website audit. In a single call, the model builds the playbook steps with full website context already in its window.

---

## Output Structure

The prompt enforces a strict 3-section output order. Frontend routes streaming tokens to the correct tab as each delimiter is hit.

```
---SECTION:context_brief---

## BUSINESS CONTEXT BRIEF

**COMPANY SNAPSHOT**
- Name, Industry, Business Model, Primary Market, Revenue Model

**GOAL CLASSIFICATION**
- Primary Goal: [MUST match TASK field exactly]
- Task Priority Order + rationale

**BUYER SITUATION**
- Stage: Idea / Early Traction / Growth / Established
- Current Stack, Stack Gap, Channel Strength, Constraint

**WEBSITE INTELLIGENCE**
- Primary CTA, SEO Signals (H1/Meta/Sitemap/Schema Y/N)
- Biggest Website Risk

**INFERRED GAPS** (2-3 implied but unstated)

**DATA QUALITY**
- Confidence: HIGH / MEDIUM / LOW
- Missing Data


---SECTION:website_audit---

# Your Website Audit — What Buyers Actually See

## 1. Who's Landing on Your Site
[Buyer profile — role, company size, pain point, buying cycle]

**The Gap**
[Central disconnect between site messaging and buyer needs]

## 2. Your Site's Scorecard
| What We Checked | Score | Finding |
|---|---|---|
| Can they tell what you do in 10 seconds? | X/10 | ... |
| Would a referred prospect "get it"? | X/10 | ... |
| Is there proof for buying committee? | X/10 | ... |
| Can they see how it works? | X/10 | ... |
| Clear next step for serious buyers? | X/10 | ... |

**Overall: X/10**

## 3. The 30-Minute Fix
[Single CMS-level change, no developer needed]

## 4. The Big Build
[One developer-worthy change with highest ROI]

## 5. Where Your Site Loses the Sale
[3-5 friction points with revenue impact HIGH/MEDIUM/LOW]


---SECTION:playbook---

THE "[OUTCOME IN CAPS]" PLAYBOOK

[2-3 lines: The One Lever]

---

1. [PRIORITY: HIGH] The "[Memorable Step Name]"

WHAT TO DO
[2-3 lines — always present]

TOOL + AI SHORTCUT
[Tool name] — [one-line usage]
Prompt: "[Company-specific copy-paste prompt]"

REAL EXAMPLE
[Actual brands from their industry, 2-3 lines]

THE EDGE
"[Technique name]": [timing trick / psychology angle / tactical detail]

[Steps 2–10 in same format — always exactly 10]

---

WEEK 1 EXECUTION CHECKLIST
Monday: [specific action]
Tuesday: [specific action]
Wednesday: [specific action]
Thursday: [specific action]
Friday: [specific action]

"[One closing sentence — truth, not pitch]"
```

---

## Prompt Architecture

Mirrors `FINAL_PHASE2_REPORT_CONTEXT.md` — one system prompt with three ordered output contracts and section-level rules.

```
SYSTEM PROMPT STRUCTURE:

1. Role definition
   — You are a growth strategist + website critic + context analyst.
   — One job: produce all 3 sections in order.

2. STEP 1: Classify business model (B2B / D2C / Hybrid)
   — Mandatory before writing anything.
   — All 3 sections must align with the declared mode.

3. REQUIRED OUTPUT ORDER (strict)
   — Section 1: context_brief
   — Section 2: website_audit  ← now informs Section 3
   — Section 3: playbook       ← built with full context + audit in window

4. Per-section output contracts
   — context_brief: same rules as Agent A (TASK lock, never override with crawl data)
   — website_audit: same rules as Agent E (B2B vs D2C scorecard)
   — playbook: same rules as Agent C (exactly 10 steps, TASK lock, no generic steps)

5. Global rules that never break
   — TASK field is non-negotiable across all sections
   — Plain English, domain vocabulary, founder reading on phone
   — No placeholders ([a tool for X] → always name the real tool)
   — Steps form a chain, each builds on the last
```

---

## Frontend Parsing

Stream arrives as one response. Frontend accumulates tokens and splits on delimiters:

```
Incoming stream:
  ---SECTION:context_brief---  → route to Tab 3 (Context Brief)
  ...tokens...
  ---SECTION:website_audit---  → route to Tab 2 (Website Audit)
  ...tokens...
  ---SECTION:playbook---       → route to Tab 1 (Playbook)
  ...tokens...
```

Each tab renders incrementally as tokens arrive. No waiting for the full response.

---

## Risk & Mitigation

| Risk | Likelihood | Mitigation |
|---|---|---|
| TASK-lock bleeds — playbook steps drift to website findings | Medium | Explicit `TASK LOCK` rule repeated in Section 3 contract |
| Model writes sections out of order | Low | "REQUIRED OUTPUT ORDER — do not deviate" in prompt |
| Playbook quality drops (less focused cognitive mode) | Medium | Test 10–15 real inputs; compare step specificity vs current |
| Section delimiter appears inside content | Low | Use unique delimiter format unlikely in prose (`---SECTION:name---`) |
| No per-agent retry on failure | Low | Retry whole call — single failure surface instead of 3 |

---

## What to Test Before Shipping

1. **TASK-lock compliance** — does every playbook step serve the stated task, not the website audit findings?
2. **Step specificity** — are company names, real tools, and non-generic edges present in all 10 steps?
3. **Section delimiter reliability** — does the parser always split correctly across 20+ test runs?
4. **Streaming UX** — do all 3 tabs start rendering at the right moment, not after full response?