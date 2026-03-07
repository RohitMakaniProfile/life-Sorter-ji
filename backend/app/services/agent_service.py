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
from typing import Optional

import structlog
from openai import AsyncOpenAI

from app.config import get_settings
from app.services.persona_doc_service import load_persona_doc, load_task_context

logger = structlog.get_logger()


def _get_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.openai_api_key_active)


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
    settings = get_settings()
    client = _get_client()

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
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
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

OUTPUT FORMAT (strict JSON):
{{
  "tools": [
    {{
      "name": "Exact name from RAG results",
      "description": "Brief description",
      "url": "exact URL from RAG results",
      "category": "extension|gpt|company",
      "rating": "from RAG results if available",
      "why_relevant": "1 sentence: why this fits their goal+domain+task"
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
        settings = get_settings()
        client = _get_client()

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

            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL_NAME,
                messages=[
                    {"role": "system", "content": EARLY_RECOMMENDATION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.4,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content or "{}"
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
    """
    Fetch and analyze a business website to generate audience insights.

    Attempts to scrape the website content, then uses GPT to analyze
    the target audience positioning and identify potential mismatches
    between intended and actual audience.

    Args:
        website_url: The business website URL
        outcome_label: User's growth goal
        domain: User's domain
        task: User's task
        rca_history: Diagnostic conversation so far

    Returns:
        Dict with intended_audience, actual_audience, mismatch_analysis,
        recommendations, business_summary
    """
    import httpx

    settings = get_settings()
    client = _get_client()

    # ── Step 1: Fetch website content ──────────────────────────
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

            # Basic HTML text extraction (strip tags, keep content)
            import re
            # Remove script and style blocks
            clean = re.sub(r'<script[^>]*>.*?</script>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
            clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML tags
            clean = re.sub(r'<[^>]+>', ' ', clean)
            # Collapse whitespace
            clean = re.sub(r'\s+', ' ', clean).strip()
            # Limit to first ~4000 chars to stay within token limits
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

    # ── Step 2: Build context ──────────────────────────────────
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

    # ── Step 3: GPT analysis ──────────────────────────────────
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": WEBSITE_ANALYSIS_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.5,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
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
      "why_recommended": "Specific reason based on user's answers, domain, and task"
    }}
  ],
  "gpts": [
    {{
      "name": "Exact GPT name from RAG results",
      "description": "What it does",
      "url": "exact URL from RAG results",
      "rating": "from RAG results if available",
      "why_recommended": "Specific reason based on user's answers"
    }}
  ],
  "companies": [
    {{
      "name": "Exact company/tool name from RAG results",
      "description": "What they do",
      "url": "exact URL from RAG results",
      "why_recommended": "Specific reason based on user's answers"
    }}
  ],
  "summary": "A 2-3 sentence personalized summary of why these tools were selected for this user's specific situation"
}}

If a category has no matching RAG results, return an empty array for it.
Return ONLY valid JSON."""


async def generate_personalized_recommendations(
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    questions_answers: list[dict],
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

    settings = get_settings()
    client = _get_client()

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

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": RECOMMENDATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=2500,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)

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
        }

    except json.JSONDecodeError as e:
        logger.error("Failed to parse recommendations JSON", error=str(e))
        return {"extensions": [], "gpts": [], "companies": [], "summary": ""}
    except Exception as e:
        logger.error("Failed to generate recommendations", error=str(e))
        return {"extensions": [], "gpts": [], "companies": [], "summary": ""}


# ── Business Insights + ICP Analysis ──────────────────────────

INSIGHTS_SYSTEM_PROMPT = """You are an elite business strategist generating a crystal-clear diagnostic report for a business owner.

You have the user's complete profile: their business goal, domain, task, diagnostic answers, website analysis, and business stage.

Your job: Generate a report with 3 sections:

SECTION 1 — SHARP INSIGHTS (exactly 5-6 points)
Each insight must be:
- 1 sentence max, punchy and specific to THIS user's situation
- Contains a "highlight" — the single most impactful phrase (3-6 words) to bold
- Actionable, not generic. The user should think "that's exactly my situation"
- Mix of: what's working, what's broken, what's the hidden opportunity

SECTION 2 — ICP ANALYSIS (Ideal Customer Profile)
Based on crawl data + answers:
- Who their ideal customer actually is (be specific: demographics, behavior, pain)
- VERDICT: If you land on their business URL as their ideal customer, what would you feel? \
  Be brutally honest but constructive. Would you trust them? Would you buy? What's missing?
- 3 improvement areas for their site/business to better attract their ICP

SECTION 3 — HOOK (catchy line before payment CTA)
- A single sentence that creates urgency or reveals a counter-intuitive insight
- Should make the user think "I need to see the rest of this"
- Reference something specific from their diagnostic — not generic marketing copy
- Max 15-20 words. Punchy. Memorable.

OUTPUT FORMAT (strict JSON):
{
  "insights": [
    {"point": "Your single-sentence insight", "highlight": "3-6 word key phrase to bold"},
    ...
  ],
  "icp_analysis": {
    "ideal_customer_profile": "2-3 sentences describing their ICP specifically",
    "targeting_verdict": "2-3 sentences: honest verdict of what a customer feels landing on their URL",
    "improvement_areas": ["Area 1 (1 sentence)", "Area 2", "Area 3"]
  },
  "hook": "Your catchy hook sentence here"
}

Return ONLY valid JSON."""


async def generate_business_insights(
    outcome_label: str,
    domain: str,
    task: str,
    rca_history: list[dict],
    business_profile: dict,
    crawl_summary: dict,
    crawl_raw: dict = None,
) -> Optional[dict]:
    """
    Generate sharp business insights, ICP analysis, and catchy hook.
    Uses all available session context for maximum personalization.
    """
    settings = get_settings()
    client = _get_client()

    # Build user message
    parts = [
        f"Growth Goal: {outcome_label}",
        f"Domain: {domain}",
        f"Task: {task}",
    ]

    if business_profile:
        parts.append("\nBUSINESS PROFILE:")
        for k, v in business_profile.items():
            parts.append(f"  • {k.replace('_', ' ').title()}: {v}")

    if crawl_summary and crawl_summary.get("points"):
        parts.append("\nWEBSITE ANALYSIS (from crawling their site):")
        for pt in crawl_summary["points"]:
            parts.append(f"  • {pt}")

    if crawl_raw:
        if crawl_raw.get("tech_signals"):
            parts.append(f"\nTech stack detected: {', '.join(crawl_raw['tech_signals'][:10])}")
        if crawl_raw.get("cta_patterns"):
            parts.append(f"CTAs found: {', '.join(crawl_raw['cta_patterns'][:5])}")
        if crawl_raw.get("social_links"):
            parts.append(f"Social links: {', '.join(crawl_raw['social_links'][:5])}")

    if rca_history:
        parts.append("\nDIAGNOSTIC Q&A:")
        for i, qa in enumerate(rca_history, 1):
            parts.append(f"  Q{i}: {qa.get('question', '')}")
            parts.append(f"  A{i}: {qa.get('answer', '')}")

    user_message = "\n".join(parts)

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.6,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)

        logger.info(
            "Business insights generated",
            insights_count=len(parsed.get("insights", [])),
            has_icp=bool(parsed.get("icp_analysis")),
            has_hook=bool(parsed.get("hook")),
        )

        return parsed

    except Exception as e:
        logger.error("Business insights generation failed", error=str(e))
        return None
