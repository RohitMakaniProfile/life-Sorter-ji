"""
═══════════════════════════════════════════════════════════════
PLAYBOOK SERVICE — 5-Agent AI Growth Playbook Engine
═══════════════════════════════════════════════════════════════
Orchestrates a parallel+sequential agent pipeline to produce
a personalised AI growth playbook from user context.

Optimised Flow (v2):
  Input (crawl + RCA answers + profile)
       ↓
  ┌────┴─────────────────────────────────────────┐
  ↓                                              ↓
  AGENT A — Merged Context+ICP                AGENT E — Website Critic
  (Context Brief + ICP Card                   (crawl + raw session data,
   + Gap Questions baked in)                   derives ICP itself)
  ~4000 tokens → ~5-6s                        ~2000 tokens → ~3s
  CRITICAL PATH                               OFF CRITICAL PATH ✓
       ↓ [user answers gap Qs if any]
       ↓
  AGENT C — 10-Step Playbook
  (Agent A output + gap answers)
  ~8000 tokens → ~8-10s
       ↓
  AGENT D — Tool Matrix per Step
  (Agent A + Agent C)
  ~2500 tokens → ~3s
       ↓
  DONE: ~16-19s critical path
  Agent E runs fully parallel → 0s added to critical path

All agents use GLM-4 Plus via OpenRouter.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings

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
YOU DO: Recommend the single best REAL tool per step — use the PROVIDED TOOL LIST first,
        then your own knowledge. Never use "[a tool for X]" placeholders.


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


━━━ TOOL SELECTION RULES ━━━
PRIORITY 1 — Use a tool from the PROVIDED TOOL LIST if it genuinely fits the step.
PRIORITY 2 — Use your own knowledge to name the single best real tool for the job.
NEVER write "[a tool for X]" — always name the actual tool.
One tool per step maximum — the best one, not the safest one.
If you know the tool has a free tier, mention it in one word: "(Free)" or "(Paid)".
The Prompt in TOOL + AI SHORTCUT must be specific to THIS company — not reusable for others.


━━━ RULES YOU NEVER BREAK ━━━
— Playbook name = the outcome, never the company name
— Every step = named technique in quotes
— WHAT TO DO always present. TOOL, REAL EXAMPLE, THE EDGE earn their place.
— Steps must be a chain — each builds on the last
— Simple English. Founder reads on phone at 10pm. Understands immediately.
— If any step could apply to a different company — rewrite it.
— Exactly 10 steps. No more, no less.

━━━ LANGUAGE RULES — DOMAIN-SPECIFIC PLAIN ENGLISH ━━━
— The reader is a business owner in the DOMAIN specified in the input. They are NOT a marketing expert.
— Use words that person uses daily in their own work. Match their vocabulary.
— NEVER use jargon from OTHER domains. A sales person does not know "content funnel". A tuition owner does not know "CPC".
— If you must use a technical term, explain it in plain words immediately after: "CTR (the % of people who click your link)"
— Write like a smart friend explaining over coffee — not a consultant writing a report.
— Every sentence must be clear to someone with zero marketing background.
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
#  NEW V2 PROMPTS — AGENT A (MERGED) + AGENT E (STANDALONE)
# ══════════════════════════════════════════════════════════════

AGENT_A_MERGED_PROMPT = """
You are an elite business intelligence specialist. Your job is to parse the user's context
and identify the exact gaps needed before building their growth playbook.

YOU DO NOT: Give advice. Recommend tools. Build playbooks. Build ICP profiles.
YOU DO: Parse, enrich, structure, and flag gaps.


━━━ OUTPUT FORMAT ━━━

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
- SEO Signals: [H1: Y/N | Meta: Y/N | Sitemap: Y/N | Schema: Y/N]
- Biggest Website Risk: [one specific conversion killer]

**INFERRED GAPS** [2-3 things not stated but clearly implied by the data]
- Gap 1: [gap + why it matters]
- Gap 2:
- Gap 3:

**DATA QUALITY**
- Confidence: [HIGH / MEDIUM / LOW]
- Missing Data: [anything unclear or contradictory]

---

**GAP QUESTIONS** (REQUIRED — always ask 1-2 targeted questions, max 3)

Rules:
— Ask what is GENUINELY missing that would change a playbook step
— Never ask what is already answered in the context
— Every question gets 4 realistic options (last option always: "Other / not sure")
— If context is rich, ask 1 sharp question — but always ask at least 1

Q1 — [Label]: [Question text]
  A) [specific realistic option]
  B) [specific realistic option]
  C) [specific realistic option]
  D) Other / not sure

[Q2 only if a second gap genuinely changes the playbook direction]
[Q3 only if a third gap is critical — rarely needed]


━━━ GUARDRAILS ━━━
- Empty crawl data: flag as critical risk in Website Intelligence section
- Never invent data. If unknown: state "Unknown — [what would confirm this]"
- B2B + B2C product: produce a SECONDARY BUYER profile below the primary
- Never write "business owners" without a specific modifier
""".strip()


AGENT_E_STANDALONE_PROMPT = """
You are the Website Critic — a conversion analyst who produces a One-Pager Website Audit Report.

You receive raw business context (founder answers, website crawl data, diagnostic Q&A).

━━━ STEP 1: CLASSIFY THE BUSINESS MODEL (MANDATORY) ━━━
Before writing anything else, determine the business model from observable signals:

→ B2B — sells to businesses/teams/professional buyers
  Classification signals: demo/consultation CTAs, enterprise pricing, case studies, integrations page, security/compliance badges, "contact sales", SLA mentions, buyer committee language
  Analytical lens: market demand, decision-making factors, ROI impact, competitive positioning, sales conversion

→ D2C — sells directly to individual consumers/end-users
  Classification signals: shopping cart, product pages with "Add to Cart", consumer pricing, reviews/ratings, social media-driven discovery, influencer mentions, lifestyle imagery
  Analytical lens: customer preferences, trends, sentiment, buying behavior, engagement, emotional connection

→ Hybrid — both motions are material. Pick the PRIMARY mode and note what you de-prioritized.

State your classification clearly: "Report Mode: B2B" or "Report Mode: D2C"
With 2-3 evidence bullets explaining WHY (cite specific site elements).
Do NOT switch lens mid-report — every section must align with the declared mode.

━━━ STEP 2: DERIVE THE IDEAL BUYER ━━━
Then build the buyer profile through that MODEL-SPECIFIC lens:
- B2B: decision-maker role, company size, pain point, buying cycle, internal stakeholders
- D2C: demographic, psychographic, discovery channel, purchase trigger, hesitation factors

━━━ STEP 3: AUDIT THROUGH THAT BUYER'S EYES ━━━
YOUR ONLY JOB: Tell the owner exactly what's failing and what to fix — through the lens of their actual buyer.

Every finding must name a SPECIFIC element from the website.
No evidence = delete the finding.

FAIL: "The website lacks social proof."
PASS: "Homepage has no testimonials above the fold. The only trust signal is award logos
buried below 3 scroll depths. A first-time visitor leaves before seeing them."


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IF BUSINESS MODEL = B2B → USE THIS OUTPUT CONTRACT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Your Website Audit — What Buyers Actually See

## 1. Who's Landing on Your Site (And What They Think)
Your ideal buyer profile — based on what your site says, who you're really selling to, and how they actually find you.

[3-4 Lines: Describe the ideal B2B client profile. Include: decision-maker role/title, company size and industry, core pain point they are trying to solve, how they typically discover the product (referral, partner intro, industry event), buying cycle length, and what internal stakeholders influence the purchase decision.]

**The Gap**
[2-3 line executive summary. State the central disconnect between what the website communicates and what the ideal B2B client needs to see. Frame around referral momentum — does the site validate why they were sent here? Write like you're telling a friend: "Here's the problem..."]

## 2. Your Site's Scorecard — Where You're Winning & Losing
We scored your site on the 5 things that decide if a B2B buyer moves forward or goes to a competitor.

| What We Checked | Score | What We Found |
|---|---|---|
| Can they tell what you do in 10 seconds? | [X/10] | [Does the homepage clearly explain what the product does, who it is for, and why it matters — in under 10 seconds? B2B buyers evaluate 4-6 vendors — vague value props get you eliminated first.] |
| Would a referred prospect "get it" instantly? | [X/10] | [When a prospect lands via a shared link, does the page immediately validate why they were sent here? 84% of B2B deals start with a referral — your site must close what the referrer opened.] |
| Is there enough proof to convince a buying committee? | [X/10] | [Are client logos, case studies with ROI numbers, certifications, or security badges visible? B2B buyers need to justify the purchase to 3-5 stakeholders — give them the ammo.] |
| Can they see how it actually works? | [X/10] | [Is there a product walkthrough, demo video, or clear how-it-works section? A technical evaluator and a VP have different needs — does your site serve both?] |
| Is there a clear next step for serious buyers? | [X/10] | [Is there a CTA matched to buyer stage? Early = 'See Demo', Mid = 'Get Custom Proposal', Late = 'Talk to Sales'. Generic 'Contact Us' loses pipeline.] |

**Overall: [X/10]**

## 3. The 30-Minute Fix — Do This Today, No Developer Needed
One change. Biggest impact. You can do it yourself in your CMS right now.

Options (pick the most impactful ONE):
- Rewrite the homepage headline to lead with the business outcome, not the feature
- Add one client logo bar or testimonial directly below the hero section
- Replace generic CTAs ('Contact Us', 'Get Started') with consultative B2B actions ('Book a 15-Min Strategy Call', 'See a Custom Demo')
- Add a one-line subhead explaining what the product does in plain language for a non-technical decision-maker
- Surface a case study stat or proof point as a callout near the hero

[Write the specific recommendation: name the exact element on their site, what to replace it with, and why it matters for B2B conversion. This should be doable in under 30 minutes in a CMS.]

## 4. The Big Build — The One Dev Change Worth Your Time
If you're going to invest developer time in ONE thing, make it this.

Options (pick the most impactful ONE):
- Build a dedicated 'How It Works' section with a product walkthrough (3-5 steps, demo video, or interactive tour)
- Create a credibility section with layered trust signals (logos by industry, named testimonials, case study with before/after metrics, compliance badges)
- Build an ROI calculator or value estimator as the primary conversion tool
- Create shareable sales enablement assets for the internal champion (one-page summary, competitor comparison, 2-min explainer video)
- Design a referral-specific landing page that acknowledges the referral context

[Write the specific recommendation: what to build, how it serves the ICP's buying process, and what success looks like.]

## 5. What Your Site Says vs. What Buyers Need to Hear
These are the exact spots where your messaging loses the deal. Each one is a B2B-specific gap — where your site fails the buying committee, not just the individual visitor.

For each mismatch found (include 3-5):
**[Catchy 3-5 word title that names the problem]**
- Your site says: [Quote or describe the current element]
- Your buyer needs to see: [What the decision-maker, technical evaluator, or internal champion needs — framed as a business outcome, ROI signal, or risk reduction]
- Why you're losing the deal: [1-2 sentences. Connect to B2B buying dynamics — committee buy-in, vendor evaluation, procurement, or champion enablement]
- Revenue Impact: [HIGH / MEDIUM / LOW]
- Who this blocks: [Economic Buyer / Technical Evaluator / Internal Champion / Procurement]


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IF BUSINESS MODEL = D2C → USE THIS OUTPUT CONTRACT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Your Website Audit — What Shoppers Actually See

## 1. Who's Visiting Your Store (And Why They Leave)
This is who your ideal buyer is — based on your brand, pricing, and where they find you.

[3-4 Lines: Describe the ideal D2C customer. Include: demographic (age range, lifestyle), psychographic (values, aspirations, pain points), how they discover the product (Instagram, Google search, influencer, friend recommendation), purchase trigger (impulse vs. researched), price sensitivity, and what makes them hesitate before buying.]

**The Gap**
[2-3 line executive summary. State the central disconnect between what the website communicates and what the ideal consumer needs to feel/see to buy. Frame around first-visit conversion — does the site create enough desire and trust to buy now? Write like you're telling a friend: "Here's the problem..."]

## 2. Your Store's Scorecard — Where You're Winning & Losing
We scored your site on the 5 things that decide if a shopper buys or bounces. These are D2C-specific — not B2B metrics.

| What We Checked | Score | What We Found |
|---|---|---|
| Do they feel "this is for me" in 3 seconds? | [X/10] | [Does the homepage create an immediate emotional hit — aspirational imagery, a headline that speaks to their identity, a clear 'this is for people like me' signal? D2C shoppers decide in the time it takes to scroll past an Instagram ad.] |
| Do they WANT your product after seeing the page? | [X/10] | [Do product pages create desire? Lifestyle photos > studio shots. Benefits > specs. "You'll feel" > "It features". Social proof next to the Add to Cart button, not buried at the bottom.] |
| How easy is it to actually buy? | [X/10] | [Clicks from homepage to payment complete? Guest checkout available? Express pay (UPI, GPay, Apple Pay)? Every extra step loses 10-15% of shoppers. Score inversely.] |
| Do they trust you enough to pay? | [X/10] | [Reviews with photos, UGC, influencer mentions, "as seen in" badges, return policy visible — all WHERE the shopper looks before tapping "Buy". Not on a separate page nobody visits.] |
| Does it work on their phone? | [X/10] | [70%+ of D2C traffic is mobile. Thumb-friendly CTAs? Images load in 2s? Checkout doesn't break on small screens? This alone can 2x conversion.] |

**Overall: [X/10]**

## 3. The 30-Minute Fix — Do This Today, No Developer Needed
One change. Biggest impact. You can do it yourself right now.

Options (pick the most impactful ONE):
- Rewrite the homepage headline to lead with the emotional benefit or transformation, not the product category
- Add customer reviews or UGC (user-generated content) directly on the homepage or product page above the fold
- Replace generic CTAs ('Shop Now') with desire-driven language ('Get Yours', 'Start Your [Transformation]', 'Try It Risk-Free')
- Add urgency or scarcity signals (limited stock, shipping deadline, launch window) near the primary CTA
- Surface the strongest customer quote or before/after result as a hero-adjacent callout

[Write the specific recommendation with exact element references from their site.]

## 4. The Big Build — The One Dev Change Worth Your Time
If you're going to invest developer time in ONE thing, make it this.

Options (pick the most impactful ONE):
- Redesign product pages with lifestyle imagery, benefit-led copy, and integrated reviews (not feature dumps)
- Build a quiz or product recommender that personalizes the experience and reduces choice paralysis
- Create a mobile-first checkout flow that eliminates friction (guest checkout, fewer form fields, express pay options)
- Build a post-purchase referral program or loyalty program with on-site visibility
- Design a 'starter bundle' or 'best seller' landing page that serves as the default entry point from ads

[Write the specific recommendation: what to build, how it serves the buyer's psychology, and what success looks like.]

## 5. Where Your Site Loses the Sale
These are the exact moments shoppers leave without buying. Each one is a D2C-specific drop-off — where desire dies, trust breaks, or friction kills the impulse.

For each friction point found (include 3-5):
**[Catchy 3-5 word title that names the problem]**
- Your site shows: [Quote or describe the current element]
- Your shopper needs to feel: [The emotional trigger that would keep them moving — desire, urgency, trust, identity, or FOMO]
- Why you're losing them: [1-2 sentences. Connect to D2C buying psychology — impulse loss, social proof gap, choice paralysis, or trust deficit]
- Revenue Impact: [HIGH / MEDIUM / LOW]
- Where they drop: [Homepage / Product Page / Cart / Checkout / Post-Purchase]


━━━ GUARDRAILS (BOTH MODELS) ━━━
- First: determine business model from context. If unclear, default to B2B for SaaS/services, D2C for physical products/consumer apps.
- Empty corpus: CRITICAL WARNING before any analysis.
- Never assume what's on pages not in the corpus.
- Quick Win must be genuinely no-dev. If it needs a developer → Strategic Fix.
- Pick only ONE Quick Win and ONE Strategic Fix — the most impactful for THIS specific company. Do not list all options.
- ICP Mismatches / Buyer Friction Points: minimum 3, maximum 5. Each must reference a specific page element.

━━━ LANGUAGE RULES ━━━
- Write in plain English. The reader is a founder reading this on their phone at 11pm.
- Never use jargon without explaining it: "above the fold (the part visible before scrolling)"
- No consultant language. Write like a sharp friend who just spent 20 minutes on their website and is being brutally honest over coffee.
- Be direct and specific. "Your homepage headline says 'Welcome to XYZ' — that tells a referred VP of Engineering nothing about why they should care."
- Headings should feel like insights, not report sections. "Where Your Site Loses the Sale" not "Buyer Friction Points".
- Every score table row should be a question a founder would actually ask, not a consultant metric.
- The tone should make the founder think "this person gets my business" not "this is a generic audit template".
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
    model_override: Optional[str] = None,
) -> dict[str, Any]:
    """
    Call an LLM via OpenRouter.
    Uses OPENROUTER_MODEL (GLM) by default; pass model_override to use a different model.
    Returns {"content": str, "usage": dict, "latency_ms": int}.
    """
    settings = get_settings()
    api_key = settings.OPENROUTER_API_KEY
    model = model_override or settings.OPENROUTER_MODEL

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ikshan.ai",
        "X-Title": "Ikshan Playbook Engine",
    }

    OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
    OPENAI_FALLBACK_MODEL = "gpt-4o-mini"

    t0 = time.perf_counter()
    max_retries = 3
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = None
        use_openrouter = True
        for attempt in range(max_retries):
            resp = await client.post(OPENROUTER_CHAT_URL, json=payload, headers=headers)
            if resp.status_code == 429 and attempt < max_retries - 1:
                wait = 2 ** attempt + 1  # 2s, 3s, 5s
                logger.warning("OpenRouter 429 rate limit, retrying", attempt=attempt + 1, wait_s=wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code == 402:
                logger.warning("OpenRouter 402 (out of credits) — falling back to OpenAI direct", model=model)
                use_openrouter = False
            break

        if not use_openrouter:
            openai_key = settings.OPENAI_API_KEY
            openai_payload = {**payload, "model": OPENAI_FALLBACK_MODEL}
            openai_headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            }
            resp = await client.post(OPENAI_CHAT_URL, json=openai_payload, headers=openai_headers)
            resp.raise_for_status()
        elif use_openrouter:
            resp.raise_for_status()

    latency_ms = int((time.perf_counter() - t0) * 1000)
    data = resp.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    return {"content": content, "usage": usage, "latency_ms": latency_ms}


# ══════════════════════════════════════════════════════════════
#  TOON-STYLE COMPACT SERIALISATION HELPERS
#  Reduces input token count by 35-55% vs verbose key-value blocks.
#  Concept: tabular arrays (headers declared once, not per row).
# ══════════════════════════════════════════════════════════════

_SEP = "|"  # column separator inside a TOON row


def _tv(value: Any, sep: str = _SEP) -> str:
    """Sanitise a single cell value — strip newlines, escape the separator."""
    if value is None:
        return "-"
    s = str(value).replace("\n", " ").replace("\r", "").strip()
    return s.replace(sep, ";") if sep in s else s


def _toon_table(label: str, headers: list[str], rows: list[list[Any]]) -> str:
    """
    Produce a TOON-style tabular block:

        LABEL[N]{h1|h2|h3}:
        v1|v2|v3
        v1|v2|v3

    Headers are declared once — values only per row.
    Commas inside values are left alone (pipe is the separator).
    """
    if not rows:
        return ""
    header_str = _SEP.join(headers)
    row_lines = [_SEP.join(_tv(cell) for cell in row) for row in rows]
    return f"{label}[{len(rows)}]{{{header_str}}}:\n" + "\n".join(row_lines)


def _toon_inline(label: str, pairs: list[tuple[str, Any]]) -> str:
    """
    Compact single-line key:value block for small dicts (≤8 fields).

        LABEL: key1:val1 | key2:val2 | key3:val3
    """
    parts = [f"{k}:{_tv(v)}" for k, v in pairs if v]
    return f"{label}: " + " | ".join(parts) if parts else ""


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
    rca_handoff: str = "",
) -> str:
    """
    Assemble the full user context that is fed into each agent.
    Uses rca_handoff (structured summary) when available, falls back to raw rca_history.
    """
    label_map = {
        "buying_process": "BuyProcess",
        "revenue_model": "RevModel",
        "sales_cycle": "SalesCycle",
        "existing_assets": "Assets",
        "buyer_behavior": "BuyerDiscovery",
        "current_stack": "Stack",
    }

    parts = [
        f"GOAL: {outcome_label}",
        f"DOMAIN: {domain}",
        f"TASK: {task}",
    ]

    # Business profile — compact inline (6 fields, single line)
    if business_profile:
        profile_pairs = []
        for key, value in business_profile.items():
            label = label_map.get(key, key.replace("_", " ").title())
            v = ", ".join(value) if isinstance(value, list) else value
            profile_pairs.append((label, v))
        parts.append(_toon_inline("PROFILE", profile_pairs))

    # RCA diagnostic findings — use structured handoff if available (much smaller than raw Q&A)
    if rca_handoff:
        parts.append(f"\nDIAGNOSTIC_FINDINGS:\n{rca_handoff}")
    elif rca_history:
        # Fallback: raw Q&A history (for sessions that started before this change)
        rca_rows = [
            [qa.get("question", ""), qa.get("answer", "")]
            for qa in rca_history
        ]
        parts.append("\n" + _toon_table("RCA", ["Q", "A"], rca_rows))

    # RCA summary — free text, keep as-is (can't compress narrative)
    if rca_summary:
        parts.append(f"\nROOT_CAUSE:\n{rca_summary}")

    # Crawl data — compact bullets (remove indent whitespace)
    if crawl_summary and crawl_summary.get("points"):
        pts = crawl_summary["points"]
        parts.append("\nCRAWL[{}]:\n".format(len(pts)) + "\n".join(pts))

    # Gap answers
    if gap_answers:
        parts.append(f"\nGAP_ANSWERS:\n{gap_answers}")

    return "\n".join(p for p in parts if p)


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
    rca_handoff: str = "",
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
        rca_handoff=rca_handoff,
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
    rca_handoff: str = "",
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
        rca_handoff=rca_handoff,
    )

    result = await _call_claude(
        system_prompt=AGENT1_PROMPT,
        user_message=user_message,
        temperature=0.4,
        max_tokens=3000,
    )

    logger.info(
        "Agent 1 (Context Parser) completed",
        latency_ms=result["latency_ms"],
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
        "Build the ICP Card. Then check what's missing and produce gap questions "
        "(maximum 3) if needed. If nothing is missing, skip the gap questions section entirely.\n\n"
        "IMPORTANT: If you DO produce gap questions, you MUST format them EXACTLY like this:\n"
        "**GAP QUESTIONS** (to improve ICP accuracy):\n\n"
        "Q1 — [Question label]: [Question text]\n"
        "  A) [option]\n"
        "  B) [option]\n"
        "  C) [option]\n"
        "  D) [option]\n\n"
        "Q2 — [Question label]: [Question text]\n"
        "  A) [option]\n"
        "  B) [option]\n"
        "  C) [option]\n"
        "  D) [option]\n\n"
        "Rules for gap question options:\n"
        "- Each question MUST have 3-5 options labeled A) B) C) D) E)\n"
        "- Options must be specific, contextual, and mutually exclusive\n"
        "- The LAST option should always be 'Other / Not sure'\n"
        "- Options must be short (under 15 words each)\n"
        "- Do NOT use generic options — make them specific to THIS company's context\n"
    )

    result = await _call_claude(
        system_prompt=AGENT2_PROMPT,
        user_message=user_message,
        temperature=0.6,
        max_tokens=4000,
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
) -> dict[str, Any]:
    """
    Agent 3: Build the 10-step execution playbook.
    Input: Agent 1 output + Agent 2 output + gap answers.
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
    user_message += (
        "Build the 10-step playbook now. Follow the exact output format. "
        "Every step must be specific to THIS company — nothing generic. "
        "You MUST include all 10 steps — do NOT stop early. Exactly 10 numbered steps."
    )

    result = await _call_claude(
        system_prompt=AGENT3_PROMPT,
        user_message=user_message,
        temperature=0.7,
        max_tokens=10000,
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
#  AGENT 5 — Website Critic (parallel with Agent 4)
# ══════════════════════════════════════════════════════════════

async def run_agent5_website_critic(
    crawl_summary: dict[str, Any],
    agent2_output: str,
) -> dict[str, Any]:
    """
    Agent 5: Audit the website through the ICP's eyes.
    Input: Crawl data + Agent 2 ICP Card.
    """
    crawl_text = ""
    if crawl_summary and crawl_summary.get("points"):
        crawl_text = "\n".join(f"  • {pt}" for pt in crawl_summary["points"])
    else:
        crawl_text = "(No crawl data available — CRITICAL WARNING)"

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
#  V2 AGENTS — Merged A, Standalone E, C+D runner
# ══════════════════════════════════════════════════════════════

async def run_agent_a_merged(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    rca_summary: str,
    crawl_summary: dict[str, Any],
    gap_answers: str = "",
    rca_handoff: str = "",
) -> dict[str, Any]:
    """
    Agent A (v2): Merged Context Parser + ICP Analyst + Gap Questions.
    Runs GLM only (fast path). Opus is fired as a background task by the caller.
    Uses rca_handoff (structured summary) when available instead of raw rca_history.
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
        rca_handoff=rca_handoff,
    )

    settings = get_settings()
    result = await _call_claude(
        system_prompt=AGENT_A_MERGED_PROMPT,
        user_message=user_message,
        temperature=0.5,
        max_tokens=3000,
        model_override=settings.OPENROUTER_CLAUDE_MODEL,
    )

    logger.info(
        "Agent A (merged Context+ICP) completed — Sonnet",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent": "agent_a_merged",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


def build_tools_toon(all_tools: list[dict[str, Any]]) -> str:
    """
    Convert a list of tool dicts into a TOON tabular block for Agent C.

    TOOLS[N]{name|type|price|desc|why|solves|ease}:
    HubSpot CRM|company|Free|CRM for pipeline|Great for early B2B|No lead tracking|30-min setup
    ...

    ~50% fewer tokens vs the verbose multi-line format.
    """
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
            name,
            tool.get("category", ""),
            price,
            tool.get("description", ""),
            tool.get("why_recommended", ""),
            tool.get("issue_solved", ""),
            tool.get("ease_of_use", ""),
        ])

    return _toon_table("TOOLS", ["name", "type", "price", "desc", "why", "solves", "ease"], rows)




async def run_agent_e_standalone(
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict[str, Any],
    rca_history: list[dict[str, str]],
    crawl_summary: dict[str, Any],
    crawl_raw: dict[str, Any] = None,
) -> dict[str, Any]:
    """
    Agent E (v2): Website Critic — runs fully in parallel with Agent A.
    Derives ICP from raw session data (no Agent A dependency).
    ~2000 tokens, ~3s — adds 0s to critical path.
    """
    # Build crawl text
    crawl_text = ""
    if crawl_summary and crawl_summary.get("points"):
        crawl_text = "\n".join(f"  • {pt}" for pt in crawl_summary["points"])
    else:
        crawl_text = "(No crawl data available — CRITICAL WARNING)"

    # Build session context (raw data, no ICP card needed)
    parts = [
        f"Growth Goal: {outcome_label}",
        f"Domain: {domain}",
        f"Task: {task}",
    ]

    if business_profile:
        parts.append("\nBUSINESS PROFILE (Scale Questions):")
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

    if rca_history:
        parts.append("\nDIAGNOSTIC Q&A:")
        for i, qa in enumerate(rca_history, 1):
            parts.append(f"  Q{i}: {qa.get('question', '')}")
            parts.append(f"  A{i}: {qa.get('answer', '')}")

    # Add detailed crawl signals if available
    if crawl_raw:
        hp = crawl_raw.get("homepage", {})
        if hp.get("title"):
            parts.append(f"\nHomepage Title: {hp['title']}")
        if hp.get("h1s"):
            parts.append(f"H1 Headlines: {', '.join(hp['h1s'][:5])}")
        tech = crawl_raw.get("tech_signals", [])
        if tech:
            parts.append(f"Tech Stack: {', '.join(tech[:8])}")
        ctas = crawl_raw.get("cta_patterns", [])
        if ctas:
            parts.append(f"CTAs Found: {', '.join(ctas[:6])}")

    session_context = "\n".join(parts)

    user_message = (
        "═══ BUSINESS CONTEXT (Raw Session Data) ═══\n"
        f"{session_context}\n\n"
        "═══ WEBSITE CRAWL DATA ═══\n"
        f"{crawl_text}\n\n"
        "Derive the ICP from the business context above, then audit the website "
        "through that ICP's eyes. Follow the exact output format. "
        "Every finding must reference a SPECIFIC element from the crawl data."
    )

    settings = get_settings()
    result = await _call_claude(
        system_prompt=AGENT_E_STANDALONE_PROMPT,
        user_message=user_message,
        temperature=0.5,
        max_tokens=5000,
        model_override=settings.OPENROUTER_CLAUDE_MODEL,
    )

    logger.info(
        "Agent E standalone (Website Critic) completed — Sonnet",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent": "agent_e_standalone",
        "output": result["content"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
    }


async def run_agent_c(
    agent_a_output: str,
    gap_answers: str = "",
    recommended_tools: str = "",
) -> dict[str, Any]:
    """
    Run Agent C (Playbook) — GLM only (fast path).
    Caller is responsible for firing Opus as a background task using _agent_c_msg from the return dict.
    recommended_tools: pre-formatted string of tools already surfaced to this user.
    """
    t0 = time.perf_counter()

    # Build the shared Agent C user message
    agent_c_msg = (
        "═══ CONTEXT BRIEF + ICP CARD (Agent A) ═══\n"
        f"{agent_a_output}\n\n"
    )
    if gap_answers:
        agent_c_msg += f"═══ GAP QUESTION ANSWERS ═══\n{gap_answers}\n\n"
    if recommended_tools:
        agent_c_msg += f"═══ PROVIDED TOOL LIST (already recommended to this user — use these in TOOL + AI SHORTCUT where relevant) ═══\n{recommended_tools}\n\n"
    agent_c_msg += (
        "Build the 10-step playbook now. Follow the exact output format. "
        "Every step must be specific to THIS company — nothing generic. "
        "For TOOL + AI SHORTCUT: use tools from the PROVIDED TOOL LIST above where they fit, "
        "and your own knowledge for the rest — always name the real tool, never use placeholders. "
        "You MUST include all 10 steps — do NOT stop early. Exactly 10 numbered steps."
    )

    # Agent C — Sonnet only
    settings = get_settings()
    result = await _call_claude(
        system_prompt=AGENT3_PROMPT,
        user_message=agent_c_msg,
        temperature=0.7,
        max_tokens=10000,
        model_override=settings.OPENROUTER_CLAUDE_MODEL,
    )

    total_ms = int((time.perf_counter() - t0) * 1000)

    logger.info(
        "Agent C (Playbook Architect) completed — Sonnet",
        latency_ms=result["latency_ms"],
    )

    return {
        "agent_c_playbook": result["content"],
        "agent_c_latency_ms": result["latency_ms"],
        "total_latency_ms": total_ms,
        "usage": {
            "prompt_tokens": result["usage"].get("prompt_tokens", 0),
            "completion_tokens": result["usage"].get("completion_tokens", 0),
        },
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
    rca_handoff: str = "",
) -> dict[str, Any]:
    """
    Run the complete 5-agent pipeline:
      Agent 1 → Agent 2 → (wait for gap answers if needed) → Agent 3 → Agent 4 + 5 (parallel)

    This is the FULL pipeline called AFTER gap answers are collected.
    Pass cached_agent1_output / cached_agent2_output to skip re-running those agents.
    Returns all agent outputs + total timing.
    """
    t0 = time.perf_counter()
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _accum_usage(result: dict) -> None:
        u = result.get("usage", {})
        total_usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        total_usage["completion_tokens"] += u.get("completion_tokens", 0)

    # ── Step 1: Agent 1 — Context Parser ──────────────────────
    if cached_agent1_output:
        logger.info("Agent 1 skipped — using cached output")
        agent1 = {"agent": "agent1_context_parser", "output": cached_agent1_output, "usage": {}, "latency_ms": 0}
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
            rca_handoff=rca_handoff,
        )
        _accum_usage(agent1)

    # ── Step 2: Agent 2 — ICP Analyst ─────────────────────────
    if cached_agent2_output:
        logger.info("Agent 2 skipped — using cached output")
        agent2 = {"agent": "agent2_icp_analyst", "output": cached_agent2_output, "usage": {}, "latency_ms": 0}
    else:
        agent2 = await run_agent2_icp_analyst(agent1_output=agent1["output"])
        _accum_usage(agent2)

    # ── Step 3: Agent 3 — Playbook Architect ──────────────────
    agent3 = await run_agent3_playbook_architect(
        agent1_output=agent1["output"],
        agent2_output=agent2["output"],
        gap_answers=gap_answers,
    )
    _accum_usage(agent3)

    # ── Step 4: Agent 5 — Website Critic ──────────────────────
    agent5 = await run_agent5_website_critic(
        crawl_summary=crawl_summary,
        agent2_output=agent2["output"],
    )
    _accum_usage(agent5)

    total_ms = int((time.perf_counter() - t0) * 1000)

    logger.info(
        "Full playbook pipeline completed",
        total_latency_ms=total_ms,
        total_prompt_tokens=total_usage["prompt_tokens"],
        total_completion_tokens=total_usage["completion_tokens"],
    )

    return {
        "agent1_context_brief": agent1["output"],
        "agent2_icp_card": agent2["output"],
        "agent3_playbook": agent3["output"],
        "agent5_website_audit": agent5["output"],
        "total_latency_ms": total_ms,
        "total_usage": total_usage,
        "agent_latencies": {
            "agent1": agent1["latency_ms"],
            "agent2": agent2["latency_ms"],
            "agent3": agent3["latency_ms"],
            "agent5": agent5["latency_ms"],
        },
    }
