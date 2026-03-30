"""
═══════════════════════════════════════════════════════════════
AI AGENT SERVICE — Dynamic Persona-Driven Question Generation
═══════════════════════════════════════════════════════════════
Uses OpenAI with loaded persona context to:

  1. Generate 2-3 highly relevant follow-up questions after Q1-Q3
  2. Produce personalized tool recommendations based on all answers
  3. Dynamically switch persona based on the domain selected

The agent loads the domain-specific persona document, parses it by task,
and extracts the Problems, Opportunities, Strategies and RCA Bridge
sections for the user's selected task. These structured sections are
used as deep context so follow-up questions directly reference the
documented problems and diagnostic signals from the persona docs.
"""

import json
import time
from typing import Optional
import re
import structlog

from app.config import get_settings
from app.services import openrouter_service
from app.services.persona_doc_service import load_persona_doc, load_task_context

logger = structlog.get_logger()


def _model_name() -> str:
    settings = get_settings()
    return settings.OPENROUTER_MODEL or settings.OPENAI_MODEL_NAME


# ── Dynamic Question Generation ────────────────────────────────


QUESTION_GENERATION_SYSTEM_PROMPT = """You are an expert AI business consultant running a diagnostic interview.

You have been provided with STRUCTURED DOMAIN CONTEXT directly from an authoritative persona document. This context contains:
- **PROBLEMS**: The specific, documented problems users face for this task
- **OPPORTUNITIES**: Concrete improvements and best practices available
- **STRATEGIES**: Proven strategic frameworks to address the problems
- **RCA BRIDGE**: Root-cause-analysis diagnostic signals (symptom → metric → root area)

Your job: Generate exactly {num_questions} diagnostic follow-up questions that will help you pinpoint WHICH of the documented problems the user is experiencing, and which opportunities/strategies are most relevant to their specific situation.

CRITICAL RULES:
- Each question MUST directly reference or probe a specific problem, opportunity, or strategy from the provided context — do NOT invent generic questions
- Use the documented PROBLEMS as inspiration: turn each problem or cluster of related problems into a diagnostic question
- Use the RCA BRIDGE signals: these are the exact symptoms and metrics you should probe for
- Options should map to different documented problems, current maturity levels, or readiness for opportunities
- Each question should have 3-5 multiple choice options covering common scenarios described in the documents
- Include one option allowing a different/custom answer
- Questions should be practical and conversational — not academic or survey-like
- DO NOT ask about their goal, domain, or task — they already answered those

OUTPUT FORMAT (strict JSON):
{{
  "questions": [
    {{
      "question": "Your question text here?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "allows_free_text": true
    }}
  ]
}}

Return ONLY valid JSON, no markdown, no explanation."""


async def generate_dynamic_questions(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    num_questions: int = 3,
) -> list[dict]:
    """
    Generate dynamic follow-up questions based on parsed persona task context.

    Loads the persona doc, parses the task-specific block (Problems, Opportunities,
    Strategies, RCA Bridge), and uses those sections to generate targeted diagnostic
    questions.
    """
    # ── Load structured task context from persona doc ──────────
    task_ctx = load_task_context(domain, task)

    if task_ctx and task_ctx.get("problems"):
        # Build structured context from the parsed sections
        persona_context_parts = []
        persona_context_parts.append(f"MATCHED TASK: {task_ctx['task']}")

        if task_ctx.get("variants"):
            persona_context_parts.append(f"\nTASK VARIANTS:\n{task_ctx['variants']}")

        if task_ctx.get("adjacent_terms"):
            persona_context_parts.append(f"\nADJACENT TERMS (metrics/concepts to probe):\n{task_ctx['adjacent_terms']}")

        persona_context_parts.append(f"\nPROBLEMS (documented issues users face):\n{task_ctx['problems']}")

        if task_ctx.get("opportunities"):
            persona_context_parts.append(f"\nOPPORTUNITIES (improvements to assess readiness for):\n{task_ctx['opportunities']}")

        if task_ctx.get("strategies"):
            persona_context_parts.append(f"\nSTRATEGIES (frameworks to evaluate fit):\n{task_ctx['strategies']}")

        if task_ctx.get("rca_bridge"):
            persona_context_parts.append(f"\nRCA BRIDGE (symptom → metric → root area):\n{task_ctx['rca_bridge']}")

        persona_context = "\n".join(persona_context_parts)

        logger.info(
            "Using structured task context for question generation",
            domain=domain,
            task=task,
            matched_task=task_ctx["task"][:60],
            context_length=len(persona_context),
        )
    else:
        # Fallback to full doc if task parsing fails
        full_doc = load_persona_doc(domain)
        if full_doc:
            persona_context = full_doc
            logger.warning(
                "Task context parsing failed, using full doc as fallback",
                domain=domain,
                task=task,
            )
        else:
            logger.warning(
                "No persona doc found for domain, using generic context",
                domain=domain,
            )
            persona_context = f"Domain: {domain}. Task: {task}. Outcome: {outcome_label}."

    # Build the user message
    user_message = f"""USER'S SELECTIONS:
- Growth Goal: {outcome_label}
- Domain: {domain}
- Task: {task}

STRUCTURED DOMAIN CONTEXT (from authoritative persona document):
{persona_context}

Based on the PROBLEMS, OPPORTUNITIES, STRATEGIES, and RCA BRIDGE above, generate {num_questions} diagnostic questions that help identify:
1. Which specific problems from the document the user is currently experiencing
2. Their current maturity level relative to the documented opportunities
3. Which strategies would be most relevant to their situation

Each question should directly map to documented content — not generic consulting questions."""

    system_prompt = QUESTION_GENERATION_SYSTEM_PROMPT.format(
        num_questions=num_questions
    )

    try:
        response = await openrouter_service.chat_completion(
            model=_model_name(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        raw = response.get("message") or "{}"
        parsed = json.loads(raw)
        questions = parsed.get("questions", [])

        logger.info(
            "Dynamic questions generated from persona context",
            domain=domain,
            task=task,
            count=len(questions),
        )

        return questions

    except json.JSONDecodeError as e:
        logger.error("Failed to parse dynamic questions JSON", error=str(e))
        return _fallback_questions(domain, task, task_ctx)
    except Exception as e:
        logger.error("Failed to generate dynamic questions", error=str(e))
        return _fallback_questions(domain, task, task_ctx)


def _fallback_questions(domain: str, task: str, task_ctx: Optional[dict] = None) -> list[dict]:
    """
    Fallback questions if AI generation fails.
    Uses the parsed task context to build relevant questions from the doc itself.
    """
    questions = []

    if task_ctx and task_ctx.get("problems"):
        # Extract first few problems and turn them into a diagnostic question
        problems_text = task_ctx["problems"]
        problem_lines = [
            line.strip() for line in problems_text.split("\n")
            if line.strip() and len(line.strip()) > 20
        ]

        if problem_lines:
            options = [p[:120] for p in problem_lines[:5]]
            questions.append({
                "question": f"Which of these documented problems best describes your current challenge with {task.lower()}?",
                "options": options,
                "allows_free_text": True,
            })

    if task_ctx and task_ctx.get("rca_bridge"):
        rca_text = task_ctx["rca_bridge"]
        rca_lines = [
            line.strip() for line in rca_text.split("\n")
            if line.strip() and len(line.strip()) > 15
        ]
        if rca_lines:
            options = [r[:120] for r in rca_lines[:5]]
            questions.append({
                "question": "Which symptom are you seeing most often?",
                "options": options,
                "allows_free_text": True,
            })

    # Generic fallback if nothing from docs
    if not questions:
        questions = [
            {
                "question": f"What tools or processes are you currently using for {task.lower()}?",
                "options": [
                    "Manual processes only",
                    "Basic tools (spreadsheets, email)",
                    "Some specialized software",
                    "Advanced/enterprise tools",
                ],
                "allows_free_text": True,
            },
            {
                "question": "What's your team size working on this?",
                "options": [
                    "Just me (solopreneur)",
                    "Small team (2-5 people)",
                    "Medium team (6-20 people)",
                    "Large team (20+ people)",
                ],
                "allows_free_text": True,
            },
            {
                "question": "What's your primary goal in the next 30 days?",
                "options": [
                    "Quick wins - start seeing results fast",
                    "Build a sustainable system/process",
                    "Scale what's already working",
                    "Fix something that's broken",
                ],
                "allows_free_text": True,
            },
        ]

    return questions


# ── Personalized Recommendation Generation ─────────────────────


# ── Early Recommendations (after Q3, before full RCA) ──────────

EARLY_RECOMMENDATION_PROMPT = """You are an expert AI tools advisor. Based on the user's growth goal, \
domain, and task (the first 3 questions of their diagnostic), select the most \
relevant tools from the RAG results below.

These are EARLY recommendations — the user hasn't completed a full diagnostic yet, \
so keep recommendations broad but relevant. Focus on tools that are universally \
useful for this task area.

IMPORTANT:
- Only recommend tools from the RAG RESULTS below — never invent tools
- Select 3-5 tools maximum that are most broadly relevant
- Keep 'why_relevant' brief (1 sentence) — these are preliminary picks
- Classify each as 'extension', 'gpt', or 'company' based on its source
- For EACH tool, also provide:
  • 'implementation_stage': When in their workflow to adopt this tool (e.g., "Day 1 — Start using immediately", "Week 1 — After setting up your content calendar", "Ongoing — Use during weekly review")
  • 'issue_solved': What specific problem this tool addresses for their goal+domain+task (1 sentence, concrete)
  • 'ease_of_use': How easy it is to integrate with their current process (e.g., "Plug & play — no setup needed", "15-min setup, works alongside your current tools", "Requires migrating existing data — but worth it")

OUTPUT FORMAT (strict JSON):
{{
  "tools": [
    {{
      "name": "Exact name from RAG results",
      "description": "Brief description",
      "url": "exact URL from RAG results",
      "category": "extension|gpt|company",
      "rating": "from RAG results if available",
      "why_relevant": "1 sentence: why this fits their goal+domain+task",
      "implementation_stage": "When to adopt this tool in their workflow",
      "issue_solved": "What specific problem this addresses",
      "ease_of_use": "How easy to integrate with current process"
    }}
  ],
  "message": "A 2-3 sentence message: present these tools as a starting point, then \
encourage the user to continue the diagnostic for more precise, tailored recommendations. \
Make it feel like: 'Here's what I'd suggest at a glance — but let me dig deeper into \
your specific situation to find the exact tools you need.'"
}}

Return ONLY valid JSON."""


def _fallback_tools_from_json(domain: str, task: str, limit: int = 5) -> list[dict]:
    """
    Direct keyword-based tool lookup from matched_tools_by_persona.json.
    Used as a reliable fallback when the RAG pipeline is unavailable.
    """
    from pathlib import Path

    json_path = Path(__file__).resolve().parent.parent.parent.parent / "matched_tools_by_persona.json"
    if not json_path.exists():
        logger.warning("matched_tools_by_persona.json not found for fallback")
        return []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        logger.error("Failed to read matched_tools_by_persona.json", error=str(e))
        return []

    # Find the best matching persona key from the JSON
    domain_lower = domain.lower()
    task_lower = task.lower()
    search_terms = (domain_lower + " " + task_lower).split()

    best_key = None
    best_score = 0
    for persona_key in raw_data:
        key_lower = persona_key.lower().replace(".docx", "")
        score = sum(1 for term in search_terms if term in key_lower)
        # Also check if domain words are a substring
        if domain_lower in key_lower or key_lower in domain_lower:
            score += 5
        if score > best_score:
            best_score = score
            best_key = persona_key

    if not best_key:
        # Just pick the first persona
        best_key = next(iter(raw_data), None)

    if not best_key:
        return []

    tools_list = raw_data[best_key]
    if not isinstance(tools_list, list):
        return []

    # Score each tool by keyword relevance to the task
    scored: list[tuple[int, dict]] = []
    for tool in tools_list:
        t_name = (tool.get("name") or "").lower()
        t_desc = (tool.get("description") or "").lower()
        t_text = t_name + " " + t_desc
        relevance = sum(1 for term in search_terms if len(term) > 2 and term in t_text)
        # Also boost by rating
        try:
            rating_bonus = int(float(tool.get("rating", "0")) * 2)
        except (ValueError, TypeError):
            rating_bonus = 0
        scored.append((relevance + rating_bonus, tool))

    # Sort by relevance descending, then take top N
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for _, tool in scored[:limit]:
        results.append({
            "name": tool.get("name", ""),
            "description": (tool.get("description") or "")[:200],
            "url": tool.get("url", ""),
            "category": tool.get("category", "extension"),
            "rating": tool.get("rating", ""),
            "why_relevant": f"Highly rated tool for {domain} — {task}.",
        })

    logger.info("Fallback early recommendations from JSON", persona=best_key, count=len(results))
    return results


async def generate_early_recommendations(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
) -> dict:
    """
    Generate early/preliminary tool recommendations based only on Q1+Q2+Q3.

    Strategy:
      1. Try RAG pipeline (embeddings + Qdrant + LLM selection)
      2. If RAG is empty or fails → use direct JSON fallback
    Always returns at least a few tools so the user sees recommendations.

    Returns:
        Dict with 'tools' (list) and 'message' (str)
    """
    from app.rag.retrieval import search_by_session

    default_message = (
        "Based on your goal and domain, here are some tools I'd recommend "
        "at first glance — but let me dig deeper into your specific situation "
        "to find the exact tools you need."
    )

    # ── Attempt 1: Full RAG pipeline ─────────────────────────────
    try:
        rag_results = await search_by_session(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            answers=[],
            top_k=10,
        )

        if rag_results.results:
            # Format RAG results
            rag_tools_text = ""
            for i, tool in enumerate(rag_results.results, 1):
                rag_tools_text += f"\n--- Tool #{i} (relevance: {tool.relevance_score:.3f}) ---\n"
                rag_tools_text += f"Name: {tool.name}\n"
                rag_tools_text += f"Description: {tool.description}\n"
                rag_tools_text += f"Source: {tool.source}\n"
                if tool.category:
                    rag_tools_text += f"Category: {tool.category}\n"
                if tool.url:
                    rag_tools_text += f"URL: {tool.url}\n"
                if tool.rating:
                    rag_tools_text += f"Rating: {tool.rating}\n"

            user_message = f"""USER'S SELECTIONS (Q1-Q3 only — diagnostic hasn't started yet):
- Growth Goal: {outcome_label}
- Domain: {domain}
- Task: {task}

═══════════════════════════════════════════════════════════
RAG RESULTS — Real tools from our verified database
═══════════════════════════════════════════════════════════
{rag_tools_text}

Select the 3-5 most broadly relevant tools for this user's goal+domain+task."""

            t0 = time.monotonic()
            response = await openrouter_service.chat_completion(
                model=_model_name(),
                messages=[
                    {"role": "system", "content": EARLY_RECOMMENDATION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.4,
                max_tokens=1200,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)

            raw = response.get("message") or "{}"
            parsed = json.loads(raw)

            if parsed.get("tools"):
                logger.info(
                    "Early recommendations via RAG+LLM",
                    domain=domain,
                    task=task,
                    tools_count=len(parsed["tools"]),
                )
                return {
                    "tools": parsed["tools"],
                    "message": parsed.get("message", default_message),
                    "_meta": {
                        "service": "openai",
                        "model": _model_name(),
                        "purpose": "early_recommendations",
                        "system_prompt": EARLY_RECOMMENDATION_PROMPT,
                        "user_message": user_message,
                        "temperature": 0.4,
                        "max_tokens": 1200,
                        "raw_response": raw,
                        "latency_ms": latency_ms,
                        "token_usage": {
                            "prompt_tokens": int((response.get("usage") or {}).get("prompt_tokens") or 0),
                            "completion_tokens": int((response.get("usage") or {}).get("completion_tokens") or 0),
                            "total_tokens": int((response.get("usage") or {}).get("total_tokens") or 0),
                        },
                    },
                }

        logger.warning("RAG returned empty — falling back to JSON", domain=domain, task=task)

    except Exception as e:
        logger.warning("RAG pipeline failed — falling back to JSON", error=str(e))

    # ── Attempt 2: Direct JSON fallback (always works) ───────────
    fallback_tools = _fallback_tools_from_json(domain, task, limit=5)
    if fallback_tools:
        return {"tools": fallback_tools, "message": default_message}

    # ── Attempt 3: custom_gpts.py as last resort ─────────────────
    from app.data.custom_gpts import get_relevant_gpts
    gpts = get_relevant_gpts(category=task, goal=outcome, limit=4)
    if gpts:
        tools = [
            {
                "name": g["name"],
                "description": g.get("description", ""),
                "url": g.get("url", ""),
                "category": "gpt",
                "rating": g.get("rating", ""),
                "why_relevant": f"Popular GPT for {task}.",
            }
            for g in gpts
        ]
        logger.info("Early recommendations from custom_gpts fallback", count=len(tools))
        return {"tools": tools, "message": default_message}

    logger.error("All early recommendation sources returned empty")
    return {"tools": [], "message": ""}


# ── Website Audience Analysis ──────────────────────────────────

WEBSITE_ANALYSIS_PROMPT = """You are an expert audience & positioning analyst. You've been given:
1. The content/HTML from a business website
2. The user's stated growth goal, domain, and task
3. Their RCA diagnostic history so far

Your job: Analyze the website to determine WHO the business is currently \
targeting (through their messaging, content, offers) vs. WHO might actually \
be consuming/resonating with that content.

This is a powerful insight — many businesses have an audience mismatch where \
their content reaches Audience B while they think they're targeting Audience A.

ANALYSIS FRAMEWORK:
- **Intended Audience**: Based on the website's messaging, offers, pricing, \
  and positioning — who are they TRYING to reach?
- **Actual Audience**: Based on the content style, language, topics, and \
  distribution — who is this content most likely reaching?
- **Mismatch Analysis**: Is there a gap? Why? What signals indicate this?
- **Recommendations**: 2-3 actionable steps to better align content with \
  the intended audience (or pivot to serve the actual audience better)

OUTPUT FORMAT (strict JSON):
{{
  "intended_audience": "Description of who the business seems to be targeting (1-2 sentences)",
  "actual_audience": "Description of who the content probably reaches (1-2 sentences)",
  "mismatch_analysis": "Analysis of the gap, if any, with specific evidence from the site (2-3 sentences)",
  "recommendations": [
    "Actionable recommendation 1",
    "Actionable recommendation 2",
    "Actionable recommendation 3"
  ],
  "business_summary": "Brief 1-2 sentence summary of what the business does"
}}

Be specific and reference actual content/messaging from the website. \
If you can't detect a mismatch, say so — don't invent one. \
Return ONLY valid JSON."""


async def analyze_website_audience(
    website_url: str,
    outcome_label: str,
    domain: str,
    task: str,
    rca_history: list[dict],
) -> dict:
    import httpx

    website_content = ""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; IkshanBot/1.0)"},
        ) as http_client:
            resp = await http_client.get(website_url)
            resp.raise_for_status()
            raw_html = resp.text

            clean = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
            clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            website_content = clean[:4000]

            logger.info(
                "Website content fetched",
                url=website_url,
                content_length=len(website_content),
            )
    except Exception as e:
        logger.warning(
            "Could not fetch website content",
            url=website_url,
            error=str(e),
        )
        website_content = f"(Could not fetch website at {website_url} — analyze based on URL and user context only)"

    rca_text = ""
    if rca_history:
        for i, qa in enumerate(rca_history, 1):
            rca_text += f"Q{i}: {qa.get('question', '')}\nA{i}: {qa.get('answer', '')}\n\n"

    user_message = f"""WEBSITE URL: {website_url}

WEBSITE CONTENT (extracted text):
{website_content}

USER CONTEXT:
- Growth Goal: {outcome_label}
- Domain: {domain}
- Task: {task}

DIAGNOSTIC CONVERSATION SO FAR:
{rca_text if rca_text else "(No diagnostic answers yet)"}

Analyze this website and provide audience insights."""

    try:
        response = await openrouter_service.chat_completion(
            model=_model_name(),
            messages=[
                {"role": "system", "content": WEBSITE_ANALYSIS_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.5,
            max_tokens=1000,
        )
        raw = response.get("message") or "{}"
        parsed = json.loads(raw)

        logger.info(
            "Website audience analysis complete",
            url=website_url,
            has_mismatch=bool(parsed.get("mismatch_analysis")),
        )

        return {
            "intended_audience": parsed.get("intended_audience", ""),
            "actual_audience": parsed.get("actual_audience", ""),
            "mismatch_analysis": parsed.get("mismatch_analysis", ""),
            "recommendations": parsed.get("recommendations", []),
            "business_summary": parsed.get("business_summary", ""),
        }

    except Exception as e:
        logger.error("Website audience analysis GPT call failed", error=str(e))
        return {
            "intended_audience": "",
            "actual_audience": "",
            "mismatch_analysis": "Analysis could not be completed at this time.",
            "recommendations": [],
            "business_summary": "",
        }


RECOMMENDATION_SYSTEM_PROMPT = """You are an expert AI tools consultant. You have been given the user's profile AND a curated list of REAL tools retrieved from our verified tool database (RAG RESULTS).

Your job: Select the best tools FROM THE RAG RESULTS that match this user's specific situation, and explain why each is relevant.

CRITICAL RULES:
- You MUST ONLY recommend tools that appear in the RAG RESULTS section below
- Do NOT invent or hallucinate tool names — only use what's provided
- If a RAG tool doesn't fit the user's situation, skip it
- You may reword descriptions to be more user-friendly, but keep the tool name and URL exact
- Every recommendation must have a specific 'why_recommended' tied to the user's answers
- Prioritize tools with higher relevance scores
- Prioritize free/freemium tools when the user seems budget-conscious
- Recommend 2-6 items per category (only include categories that have results)
- The 'summary' MUST be a structured object with: icp, seo, top_funnel (5 strategies), \
  mid_funnel (5 strategies), bottom_funnel (5 strategies), and one_liner. \
  Use the WEBSITE ANALYSIS and BUSINESS PROFILE data to generate specific, actionable \
  ICP, SEO, and funnel strategies. Each funnel must have exactly 5 short, crisp strategies \
  specific to THIS business — not generic marketing advice.
- For EACH tool, you MUST also provide:
  • 'implementation_stage': WHEN in the user's workflow they should adopt this tool. Be specific — \
    reference their actual situation from the Q&A. Examples: "Day 1 — Start using before your next post", \
    "Week 1 — After auditing your current lead flow", "Month 1 — Once your content calendar is set up", \
    "Ongoing — Use during weekly performance reviews"
  • 'issue_solved': What SPECIFIC problem from the diagnostic this tool solves. Connect it directly \
    to something the user said or a root cause identified. Not generic — tie it to THEIR situation.
  • 'ease_of_use': How easy it is to adopt given THEIR current process and tools. Be honest — \
    if it requires learning, say so. Examples: "Plug & play — works in your browser, no setup", \
    "30-min initial setup, then integrates with your existing workflow", \
    "Requires migrating from spreadsheets — 2-3 hours initially, saves 5+ hrs/week after"

OUTPUT FORMAT (strict JSON):
{{
  "extensions": [
    {{
      "name": "Exact tool name from RAG results",
      "description": "What it does (can reword)",
      "url": "exact URL from RAG results",
      "free": true,
      "rating": "from RAG results if available",
      "installs": "from RAG results if available",
      "why_recommended": "Specific reason based on user's answers, domain, and task",
      "implementation_stage": "When in workflow to adopt (e.g., Day 1, Week 1, Month 1, Ongoing)",
      "issue_solved": "What specific diagnosed problem this tool fixes",
      "ease_of_use": "How easy to adopt given their current setup"
    }}
  ],
  "gpts": [
    {{
      "name": "Exact GPT name from RAG results",
      "description": "What it does",
      "url": "exact URL from RAG results",
      "rating": "from RAG results if available",
      "why_recommended": "Specific reason based on user's answers",
      "implementation_stage": "When in workflow to adopt",
      "issue_solved": "What specific problem this addresses",
      "ease_of_use": "How easy to integrate"
    }}
  ],
  "companies": [
    {{
      "name": "Exact company/tool name from RAG results",
      "description": "What they do",
      "url": "exact URL from RAG results",
      "why_recommended": "Specific reason based on user's answers",
      "implementation_stage": "When in workflow to adopt",
      "issue_solved": "What specific problem this addresses",
      "ease_of_use": "How easy to integrate"
    }}
  ],
  "summary": {
    "icp": "1-2 crisp sentences: Who is their ideal customer? Be specific — demographics, behavior, pain points.",
    "seo": "1-2 crisp sentences: Current SEO health verdict — what's working, what's broken, one quick win.",
    "top_funnel": [
      "Growth strategy 1 for awareness & discovery",
      "Growth strategy 2",
      "Growth strategy 3",
      "Growth strategy 4",
      "Growth strategy 5"
    ],
    "mid_funnel": [
      "Growth strategy 1 for consideration & trust",
      "Growth strategy 2",
      "Growth strategy 3",
      "Growth strategy 4",
      "Growth strategy 5"
    ],
    "bottom_funnel": [
      "Growth strategy 1 for conversion & revenue",
      "Growth strategy 2",
      "Growth strategy 3",
      "Growth strategy 4",
      "Growth strategy 5"
    ],
    "one_liner": "A single punchy sentence tying the tools to the user's growth goal"
  }
}}

If a category has no matching RAG results, return an empty array for it.
Return ONLY valid JSON."""


async def generate_personalized_recommendations(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    questions_answers: list[dict],
    crawl_summary: dict = None,
    crawl_raw: dict = None,
    business_profile: dict = None,
    rca_diagnostic_context: dict = None,
    rca_summary: str = "",
    gbp_data: dict = None,
) -> dict:
    """
    Generate personalized tool recommendations using RAG + GPT.

    Pipeline:
        1. Query the RAG vector store with full session context
           → gets top-20 real tools ranked by semantic similarity
        2. Send those real tools + user profile to GPT
           → GPT selects the best ones and writes 'why_recommended'

    Args:
        outcome: The outcome ID
        outcome_label: The outcome display label
        domain: The domain/sub-category
        task: The specific task
        questions_answers: List of all Q&A pairs (static + dynamic)

    Returns:
        Dict with 'extensions', 'gpts', 'companies', 'summary'
    """
    from app.rag.retrieval import search_by_session

    # ── Step 1: Query RAG for real tools ────────────────────────
    rag_results = await search_by_session(
        outcome_label=outcome_label,
        domain=domain,
        task=task,
        answers=questions_answers,
        top_k=20,
    )

    # Format RAG results for the GPT prompt
    rag_tools_text = ""
    if rag_results.results:
        for i, tool in enumerate(rag_results.results, 1):
            rag_tools_text += f"\n--- Tool #{i} (relevance: {tool.relevance_score:.3f}) ---\n"
            rag_tools_text += f"Name: {tool.name}\n"
            rag_tools_text += f"Description: {tool.description}\n"
            rag_tools_text += f"Source: {tool.source}\n"
            if tool.category:
                rag_tools_text += f"Category: {tool.category}\n"
            if tool.url:
                rag_tools_text += f"URL: {tool.url}\n"
            if tool.rating:
                rag_tools_text += f"Rating: {tool.rating}\n"
            if tool.installs:
                rag_tools_text += f"Installs: {tool.installs}\n"
            rag_tools_text += f"Persona/Domain: {tool.persona}\n"

        logger.info(
            "RAG tools retrieved for recommendations",
            domain=domain,
            task=task,
            tools_found=len(rag_results.results),
            top_score=rag_results.results[0].relevance_score if rag_results.results else 0,
        )
    else:
        rag_tools_text = "(No tools found in database for this query)"
        logger.warning("No RAG results for recommendation query", domain=domain, task=task)

    # ── Step 2: Load persona context ────────────────────────────
    task_ctx = load_task_context(domain, task)
    if task_ctx and task_ctx.get("problems"):
        context_parts = [f"MATCHED TASK: {task_ctx['task']}"]
        if task_ctx.get("problems"):
            context_parts.append(f"\nDOCUMENTED PROBLEMS:\n{task_ctx['problems']}")
        if task_ctx.get("opportunities"):
            context_parts.append(f"\nDOCUMENTED OPPORTUNITIES:\n{task_ctx['opportunities']}")
        if task_ctx.get("strategies"):
            context_parts.append(f"\nDOCUMENTED STRATEGIES:\n{task_ctx['strategies']}")
        persona_context = "\n".join(context_parts)
    else:
        full_doc = load_persona_doc(domain)
        persona_context = full_doc or f"Domain: {domain}. Task: {task}."

    # Build Q&A summary
    qa_text = ""
    for i, qa in enumerate(questions_answers, 1):
        qa_text += f"Q{i} ({qa.get('type', 'static')}): {qa.get('q', qa.get('question', ''))}\n"
        qa_text += f"A{i}: {qa.get('a', qa.get('answer', ''))}\n\n"

    # ── Step 3: GPT selects + ranks from RAG results ───────────
    user_message = f"""USER PROFILE:
- Growth Goal: {outcome_label}
- Domain: {domain}
- Task: {task}

ALL QUESTIONS & ANSWERS:
{qa_text}

PERSONA CONTEXT (domain expertise):
{persona_context}

═══════════════════════════════════════════════════════════
RAG RESULTS — Real tools from our verified database
(Select the best ones for this user from these results ONLY)
═══════════════════════════════════════════════════════════
{rag_tools_text}

Based on the user's profile and answers, select the most relevant tools from the RAG RESULTS above. Group them into extensions, gpts, and companies. Write a personalized 'why_recommended' for each."""

    # Add RCA summary (Claude's root cause diagnosis)
    if rca_summary:
        user_message += f"\n\n═══ ROOT CAUSE DIAGNOSIS (from Claude's RCA) ═══\n{rca_summary}"

    # Add dynamic loader context (problems, RCA bridge, opportunities, strategies from persona docs)
    if rca_diagnostic_context:
        sections = rca_diagnostic_context.get("sections", [])
        for sec in sections:
            key = sec.get("key", "")
            items = sec.get("items", [])
            if key == "problems" and items:
                user_message += "\n\n═══ DOCUMENTED PROBLEM PATTERNS (from persona docs) ═══\n"
                for i, item in enumerate(items, 1):
                    user_message += f"  P{i}. {item}\n"
            elif key == "rca_bridge" and items:
                user_message += "\n\n═══ DIAGNOSTIC SIGNALS (symptom → root cause) ═══\n"
                rca_parsed = sec.get("rca_parsed", [])
                if rca_parsed:
                    for i, rca in enumerate(rca_parsed, 1):
                        line = f"  S{i}. \"{rca.get('symptom', '')}\""
                        if rca.get("metric"): line += f" → KPI: {rca['metric']}"
                        if rca.get("root_area"): line += f" → Root: {rca['root_area']}"
                        user_message += line + "\n"
                else:
                    for i, item in enumerate(items, 1):
                        user_message += f"  S{i}. {item}\n"
            elif key == "opportunities" and items:
                user_message += "\n\n═══ GROWTH OPPORTUNITIES (from persona docs) ═══\n"
                for i, item in enumerate(items, 1):
                    user_message += f"  O{i}. {item}\n"
        strategies = rca_diagnostic_context.get("strategies", "")
        if strategies:
            user_message += f"\n\n═══ PROVEN STRATEGIES & FRAMEWORKS ═══\n{strategies[:1500]}\n"

    # Add crawl/business context for ICP, SEO, and funnel analysis
    if crawl_summary and crawl_summary.get("points"):
        user_message += "\n\nWEBSITE ANALYSIS (from crawling their site):\n"
        for pt in crawl_summary["points"]:
            user_message += f"  • {pt}\n"

    if crawl_raw:
        if crawl_raw.get("tech_signals"):
            user_message += f"\nTech stack detected: {', '.join(crawl_raw['tech_signals'][:10])}"
        if crawl_raw.get("cta_patterns"):
            user_message += f"\nCTAs found: {', '.join(crawl_raw['cta_patterns'][:5])}"
        if crawl_raw.get("social_links"):
            user_message += f"\nSocial links: {', '.join(crawl_raw['social_links'][:5])}"
        seo = crawl_raw.get("seo_basics", {})
        if seo:
            seo_notes = []
            if seo.get("has_meta"): seo_notes.append("Has meta tags")
            else: seo_notes.append("Missing meta tags")
            if seo.get("has_viewport"): seo_notes.append("Mobile viewport set")
            else: seo_notes.append("No mobile viewport")
            if seo.get("has_sitemap"): seo_notes.append("Sitemap detected")
            else: seo_notes.append("No sitemap")
            user_message += f"\nSEO Basics: {', '.join(seo_notes)}"

    if business_profile:
        user_message += "\n\nBUSINESS PROFILE:\n"
        for k, v in business_profile.items():
            user_message += f"  • {k.replace('_', ' ').title()}: {v}\n"

    if gbp_data:
        user_message += "\n\n═══ GOOGLE BUSINESS PROFILE DATA ═══\n"
        if gbp_data.get("business_name"):
            user_message += f"  • Business: {gbp_data['business_name']}\n"
        if gbp_data.get("rating"):
            user_message += f"  • Rating: {gbp_data['rating']}/5 ({gbp_data.get('total_reviews', '?')} reviews)\n"
        if gbp_data.get("category"):
            user_message += f"  • Category: {gbp_data['category']}\n"
        reviews = gbp_data.get("reviews", [])
        if reviews:
            user_message += f"  Customer Reviews ({len(reviews)}):\n"
            for i, rev in enumerate(reviews[:5], 1):
                text = rev.get("text", rev.get("snippet", ""))
                if text:
                    user_message += f"    R{i}. [{rev.get('rating', '?')}★] {text[:200]}\n"

    t0 = time.monotonic()
    try:
        response = await openrouter_service.chat_completion(
            model=_model_name(),
            messages=[
                {"role": "system", "content": RECOMMENDATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=3500,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        raw = response.get("message") or "{}"
        parsed = json.loads(raw)
        token_usage = {
            "prompt_tokens": int((response.get("usage") or {}).get("prompt_tokens") or 0),
            "completion_tokens": int((response.get("usage") or {}).get("completion_tokens") or 0),
            "total_tokens": int((response.get("usage") or {}).get("total_tokens") or 0),
        }

        logger.info(
            "Personalized recommendations generated (RAG-powered)",
            domain=domain,
            task=task,
            rag_tools_input=len(rag_results.results),
            extensions_out=len(parsed.get("extensions", [])),
            gpts_out=len(parsed.get("gpts", [])),
            companies_out=len(parsed.get("companies", [])),
        )

        return {
            "extensions": parsed.get("extensions", []),
            "gpts": parsed.get("gpts", []),
            "companies": parsed.get("companies", []),
            "summary": parsed.get("summary", ""),
            "_meta": {
                "service": "openai",
                "model": _model_name(),
                "purpose": "personalized_recommendations",
                "system_prompt": RECOMMENDATION_SYSTEM_PROMPT,
                "user_message": user_message,
                "temperature": 0.4,
                "max_tokens": 3500,
                "raw_response": raw,
                "latency_ms": latency_ms,
                "token_usage": token_usage,
            },
        }

    except json.JSONDecodeError as e:
        logger.error("Failed to parse recommendations JSON", error=str(e))
        return {"extensions": [], "gpts": [], "companies": [], "summary": ""}
    except Exception as e:
        logger.error("Failed to generate recommendations", error=str(e))
        return {"extensions": [], "gpts": [], "companies": [], "summary": ""}


