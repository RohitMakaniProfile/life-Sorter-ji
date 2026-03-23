"""
═══════════════════════════════════════════════════════════════
AGENT EXECUTOR SERVICE — Truly Autonomous Playbook Step Executor
═══════════════════════════════════════════════════════════════
Every agent:
  1. Searches the web (Serper) for REAL data relevant to the step
  2. Produces an ACTUAL DELIVERABLE — not advice, not a plan
  3. Returns ready-to-use output the founder can copy-paste

Agent types (all do web research first):
  - ResearchAgent  → delivers: keyword lists, competitor tables, data reports
  - ContentAgent   → delivers: actual blog/posts/scripts written out
  - OutreachAgent  → delivers: real emails & DMs ready to send
  - StrategyAgent  → delivers: filled-in templates, real audit results, checklists
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
SERPER_URL = "https://google.serper.dev/search"


# ══════════════════════════════════════════════════════════════
#  LOW-LEVEL HELPERS
# ══════════════════════════════════════════════════════════════

async def _call_glm(
    system: str,
    user: str,
    max_tokens: int = 3000,
    temperature: float = 0.6,
) -> dict[str, Any]:
    """Single GLM call via OpenRouter."""
    settings = get_settings()
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            OPENROUTER_CHAT_URL,
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    latency_ms = int((time.time() - t0) * 1000)
    content = data["choices"][0]["message"].get("content") or ""
    return {"output": content.strip(), "latency_ms": latency_ms, "usage": data.get("usage", {})}


async def _serper_search(query: str, num: int = 5) -> list[dict[str, str]]:
    """Search the web using Serper API."""
    settings = get_settings()
    if not settings.SERPER_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                SERPER_URL,
                headers={"X-API-KEY": settings.SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": num},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            {"title": item.get("title", ""), "link": item.get("link", ""), "snippet": item.get("snippet", "")}
            for item in data.get("organic", [])[:num]
        ]
    except Exception as e:
        logger.warning("Serper search failed", query=query, error=str(e))
        return []


def _format_search_results(results: list[dict[str, str]]) -> str:
    if not results:
        return "No web results found."
    return "\n\n".join(
        f"{i}. **{r['title']}**\n   {r['snippet']}\n   Source: {r['link']}"
        for i, r in enumerate(results, 1)
    )


async def _multi_search(queries: list[str], num: int = 5) -> tuple[list[dict], str]:
    """Run multiple Serper searches in parallel. Returns (results_list, formatted_text)."""
    tasks = [_serper_search(q, num=num) for q in queries]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    seen, all_results = set(), []
    for batch in batches:
        if isinstance(batch, list):
            for item in batch:
                if item["link"] not in seen:
                    seen.add(item["link"])
                    all_results.append(item)
    return all_results[:10], _format_search_results(all_results[:10])


# ══════════════════════════════════════════════════════════════
#  STEP CLASSIFIER
# ══════════════════════════════════════════════════════════════

CLASSIFIER_SYSTEM = """Classify this playbook step into ONE type. Output ONLY the word.

- "research"  → needs data: competitor analysis, keyword research, market study, SEO audit, tool comparison
- "content"   → needs writing: blog, social post, ad copy, video script, landing page copy
- "outreach"  → needs messages: cold email, LinkedIn DM, partnership pitch, follow-up sequences
- "execute"   → needs doing: setup tracking, install tools, configure systems, run audits, build dashboards

Output ONLY: research | content | outreach | execute"""


async def classify_step(step_text: str) -> str:
    result = await _call_glm(system=CLASSIFIER_SYSTEM, user=f"Step: {step_text[:500]}", max_tokens=10, temperature=0.1)
    raw = (result.get("output") or "").strip().lower()
    for v in ("research", "content", "outreach", "execute"):
        if v in raw:
            return v
    return "execute"


# ══════════════════════════════════════════════════════════════
#  QUERY GENERATOR — used by ALL agents
# ══════════════════════════════════════════════════════════════

async def _generate_search_queries(step_text: str, business_context: str, count: int = 3) -> list[str]:
    """Generate targeted search queries for any step type."""
    result = await _call_glm(
        system=(
            "You generate Google search queries to FIND REAL DATA for a business task. "
            "Output 3 search queries, one per line. No numbering. No explanation. "
            "Make queries specific — include industry, geography, year 2025 where relevant. "
            "Focus on finding: real examples, actual data, competitor specifics, tools, templates."
        ),
        user=f"Business: {business_context[:300]}\n\nTask to execute: {step_text[:400]}",
        max_tokens=150,
        temperature=0.3,
    )
    queries = [q.strip() for q in result["output"].splitlines() if q.strip()][:count]
    return queries if queries else [step_text[:80]]


# ══════════════════════════════════════════════════════════════
#  RESEARCH AGENT — delivers actual data tables & findings
# ══════════════════════════════════════════════════════════════

RESEARCH_AGENT_SYSTEM = """You are an autonomous research agent. You have ALREADY searched the web.
You are given real search results. Your job: produce a COMPLETE DELIVERABLE the founder can use immediately.

RULES — READ CAREFULLY:
- You are NOT an advisor. Do NOT say "you should research X" or "go to tool Y."
- You HAVE the data. Use it. Produce the actual output.
- Include REAL company names, REAL URLs, REAL numbers from the search results.
- If the step asks for a keyword list → produce the actual keyword list with volumes.
- If it asks for competitor analysis → produce the actual comparison table.
- If it asks for an audit → produce the actual audit findings.

FORMAT:
## [Deliverable Title]

[The actual deliverable — tables, lists, data. NOT advice.]

### Key Data Points
[Real numbers, real names, real URLs from search results]

### Ready-to-Use Output
[Copy-pasteable deliverable: spreadsheet data, keyword list, competitor table, etc.]

NEVER say "consider doing X" — instead DO X and show the result."""


async def run_research_agent(step_text: str, business_context: str, icp_card: str = "") -> dict[str, Any]:
    t0 = time.time()
    queries = await _generate_search_queries(step_text, business_context)
    all_results, search_text = await _multi_search(queries)

    ctx = f"Business Context:\n{business_context[:600]}"
    if icp_card:
        ctx += f"\n\nICP:\n{icp_card[:300]}"

    synthesis = await _call_glm(
        system=RESEARCH_AGENT_SYSTEM,
        user=f"{ctx}\n\nPlaybook Step to EXECUTE:\n{step_text}\n\n--- WEB SEARCH RESULTS (use this data) ---\n{search_text}",
        max_tokens=3000,
        temperature=0.5,
    )
    return {
        "output": synthesis["output"],
        "sources": all_results,
        "search_queries": queries,
        "step_type": "research",
        "latency_ms": int((time.time() - t0) * 1000),
    }


# ══════════════════════════════════════════════════════════════
#  CONTENT AGENT — writes actual content pieces
# ══════════════════════════════════════════════════════════════

CONTENT_AGENT_SYSTEM = """You are an autonomous content agent. You write the ACTUAL content — finished, ready to publish.

You have been given web search results for research/inspiration. Use them for real examples and data.

RULES:
- Write the COMPLETE content piece. Not an outline. Not tips. The actual thing.
- If the step says "write a blog" → write the full blog post (800-1200 words).
- If it says "create social posts" → write 5 actual posts with hooks and CTAs.
- If it says "write ad copy" → write 3 complete ad variants (headline + body + CTA).
- If it says "video script" → write the actual script with timestamps.
- Include real data/examples from the search results.
- Match the brand voice: founder-led, direct, no corporate fluff.

FORMAT:
## [Content Type]: [Title]

[THE ACTUAL COMPLETE CONTENT — ready to copy-paste and publish]

---
**Word count:** [X]
**Platform:** [where to publish]
**CTA included:** Yes"""


async def run_content_agent(step_text: str, business_context: str, icp_card: str = "") -> dict[str, Any]:
    t0 = time.time()
    queries = await _generate_search_queries(step_text, business_context)
    all_results, search_text = await _multi_search(queries)

    ctx = f"Business Context:\n{business_context[:600]}"
    if icp_card:
        ctx += f"\n\nTarget Audience (ICP):\n{icp_card[:400]}"

    result = await _call_glm(
        system=CONTENT_AGENT_SYSTEM,
        user=f"{ctx}\n\nPlaybook Step to EXECUTE:\n{step_text}\n\n--- RESEARCH DATA (use for real examples) ---\n{search_text}",
        max_tokens=3500,
        temperature=0.7,
    )
    return {
        "output": result["output"],
        "sources": all_results,
        "search_queries": queries,
        "step_type": "content",
        "latency_ms": int((time.time() - t0) * 1000),
    }


# ══════════════════════════════════════════════════════════════
#  OUTREACH AGENT — writes real emails & DMs ready to send
# ══════════════════════════════════════════════════════════════

OUTREACH_AGENT_SYSTEM = """You are an autonomous outreach agent. You write REAL messages ready to send — no [PLACEHOLDER] brackets.

You have web search results with real companies and people. Use them.

RULES:
- Write COMPLETE messages using REAL company names from search results.
- No placeholders. No [YOUR NAME]. Fill everything in using the business context.
- Write for the ACTUAL ICP — reference their real pain points.

PRODUCE ALL OF THESE:
1. **Cold Email #1** — Subject line + 4-line body + CTA (under 100 words)
2. **Cold Email #2** — Different angle, same target
3. **LinkedIn DM** — 2-3 lines, conversational
4. **Follow-up Email** — For day 3 after no reply
5. **WhatsApp Message** — Ultra-short version (under 40 words)

For each, reference a SPECIFIC pain point or trend from the search results.

End with:
---
**Personalization hooks used:** [list the specific data points you referenced]
**Send sequence:** [recommended timing for each message]"""


async def run_outreach_agent(step_text: str, business_context: str, icp_card: str = "") -> dict[str, Any]:
    t0 = time.time()
    queries = await _generate_search_queries(step_text, business_context)
    all_results, search_text = await _multi_search(queries)

    ctx = f"Business Context:\n{business_context[:600]}"
    if icp_card:
        ctx += f"\n\nIdeal Customer Profile:\n{icp_card[:500]}"

    result = await _call_glm(
        system=OUTREACH_AGENT_SYSTEM,
        user=f"{ctx}\n\nPlaybook Step to EXECUTE:\n{step_text}\n\n--- REAL MARKET DATA (use for personalization) ---\n{search_text}",
        max_tokens=3000,
        temperature=0.7,
    )
    return {
        "output": result["output"],
        "sources": all_results,
        "search_queries": queries,
        "step_type": "outreach",
        "latency_ms": int((time.time() - t0) * 1000),
    }


# ══════════════════════════════════════════════════════════════
#  EXECUTE AGENT — actually does the task with real data
# ══════════════════════════════════════════════════════════════

EXECUTE_AGENT_SYSTEM = """You are an autonomous execution agent. You DO the work — you don't advise.

You have real web search data. Use it to produce a FINISHED deliverable.

RULES — CRITICAL:
- NEVER say "go to [tool]" or "you should" or "consider doing." YOU are the tool. YOU do it.
- If the step says "audit the website" → produce the actual audit with real findings.
- If it says "build a keyword map" → produce the actual keyword map table.
- If it says "set up tracking" → produce the exact code snippets, tag configurations, event names.
- If it says "create a sitemap" → produce the actual XML sitemap content.
- If it says "install a tool" → produce the step-by-step with exact code/config ready to paste.
- If it says "build a dashboard" → produce the exact metrics, filters, and formulas.

Use REAL data from search results — real URLs, real tools, real numbers.

FORMAT:
## DONE: [What was accomplished]

[The actual deliverable — code, config, audit results, data tables, templates filled in]

### Files/Assets Created
[List every tangible output with copy-pasteable content]

### Verification
[How to confirm this was done correctly — specific checks]"""


async def run_execute_agent(step_text: str, business_context: str, icp_card: str = "") -> dict[str, Any]:
    t0 = time.time()
    queries = await _generate_search_queries(step_text, business_context)
    all_results, search_text = await _multi_search(queries)

    ctx = f"Business Context:\n{business_context[:600]}"
    if icp_card:
        ctx += f"\n\nICP:\n{icp_card[:300]}"

    result = await _call_glm(
        system=EXECUTE_AGENT_SYSTEM,
        user=f"{ctx}\n\nPlaybook Step to EXECUTE NOW:\n{step_text}\n\n--- REAL DATA FROM WEB (use this) ---\n{search_text}",
        max_tokens=3500,
        temperature=0.5,
    )
    return {
        "output": result["output"],
        "sources": all_results,
        "search_queries": queries,
        "step_type": "execute",
        "latency_ms": int((time.time() - t0) * 1000),
    }


# ══════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

async def execute_playbook_step(
    step_number: int,
    step_text: str,
    business_context: str,
    icp_card: str = "",
    force_type: Optional[str] = None,
) -> dict[str, Any]:
    """
    Main entry point. Classifies + executes a single playbook step.
    Every agent searches the web first, then produces an actual deliverable.
    """
    t0 = time.time()

    valid_types = {"research", "content", "outreach", "execute"}
    if force_type and force_type in valid_types:
        step_type = force_type
    else:
        step_type = await classify_step(step_text)

    logger.info("Executing playbook step", step_number=step_number, step_type=step_type)

    if step_type == "research":
        result = await run_research_agent(step_text, business_context, icp_card)
    elif step_type == "content":
        result = await run_content_agent(step_text, business_context, icp_card)
    elif step_type == "outreach":
        result = await run_outreach_agent(step_text, business_context, icp_card)
    else:
        result = await run_execute_agent(step_text, business_context, icp_card)

    return {
        "step_number": step_number,
        "step_type": step_type,
        "output": result["output"],
        "sources": result.get("sources", []),
        "search_queries": result.get("search_queries", []),
        "latency_ms": int((time.time() - t0) * 1000),
    }
