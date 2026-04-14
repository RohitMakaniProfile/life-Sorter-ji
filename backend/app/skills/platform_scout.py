from __future__ import annotations

import re
import time
from typing import Any

from app.config import GEMINI_SCOUT_MODELS, get_settings
from app.services.ai_helper import ai_helper as _ai
from .models import ProgressCb, SkillRunResult
from .utils import _emit, _extract_url


def _platform_scout_heuristic(
    message: str,
    business_url: str,
    region_hint: str,
) -> tuple[dict[str, Any], str]:
    scope = "local" if any(
        k in (message or "").lower()
        for k in ["near me", "local", "city", "restaurant", "clinic", "salon"]
    ) else "global"
    covered_region = region_hint or ("local-market" if scope == "local" else "global")

    domain = ""
    if business_url:
        domain = re.sub(r"^https?://", "", business_url).split("/")[0]

    base_queries = [
        f"{domain or 'brand'} reviews",
        f"{domain or 'brand'} complaints",
        f"{domain or 'brand'} competitors",
        f"best alternatives to {domain or 'this business'}",
    ]
    if scope == "local":
        base_queries += [
            f"{domain or 'business'} Google Maps reviews {covered_region}",
            f"top {domain or 'business'} competitors {covered_region}",
        ]

    data = {
        "scope": scope,
        "coveredRegion": covered_region,
        "businessUrl": business_url,
        "result": {
            "scope": scope,
            "coveredRegion": covered_region,
            "businessTypeGuess": "unknown",
            "queries": base_queries,
        },
    }
    text = "\n".join([
        "Platform scout",
        f"- Scope: {scope}",
        f"- Region: {covered_region}",
        f"- Queries generated: {len(base_queries)}",
    ])
    return data, text


def _format_scout_text(parsed: dict[str, Any]) -> str:
    hypotheses = parsed.get("platformHypotheses") or []
    queries = parsed.get("searchQueries") or []
    scope = parsed.get("scope") or "global"
    covered_region = str(parsed.get("coveredRegion") or "").strip()
    granularity = parsed.get("scopeGranularity") or ""

    top_platforms = "\n".join(
        f"- {h.get('macroType', '')}: {h.get('platformName', '')}"
        for h in hypotheses[:12]
    )
    top_queries = "\n".join(
        f"- [{q.get('goal', '')}] {q.get('query', '')}"
        for q in sorted(queries, key=lambda x: x.get("priority", 999))[:16]
    )
    scope_line = (
        f"- scope: local ({covered_region}{', ' + granularity if granularity else ''})"
        if scope == "local" and covered_region
        else f"- scope: {scope}"
    )
    lines = [
        "Platform scout",
        f"- businessTypeGuess: {parsed.get('businessTypeGuess') or '(unknown)'}",
        f"- regionGuess: {parsed.get('regionGuess') or '(none)'}",
        scope_line,
        f"- hypotheses: {len(hypotheses)}",
        f"- queries: {len(queries)}",
    ]
    if top_platforms:
        lines += ["", "Top platforms:", top_platforms]
    if top_queries:
        lines += ["", "Top web-search queries:", top_queries]
    return "\n".join(lines)


_SCOUT_PROMPT_TEMPLATE = """\
You are a Business Intelligence discovery assistant.
Given landing-page and scraped signals for a business, generate which external platforms are likely to contain customer reviews, listings, social proof, competitive signals, and market context. You MUST also infer whether the business is LOCAL (primary market is a specific place) or GLOBAL, and generate region-aware search queries.

You MUST output JSON only with this shape:
{{
  "businessTypeGuess": "short label (e.g. hotel, cafe, delivery, SaaS)",
  "regionGuess": "short label or empty (e.g. India, Gujarat, Ahmedabad)",
  "scope": "global or local",
  "coveredRegion": "when scope is local: the primary market — city name (e.g. Ahmedabad), state/region (e.g. Gujarat), or country (e.g. India). Empty string when scope is global.",
  "scopeGranularity": "when scope is local only: city | state_or_region | country",
  "platformHypotheses": [
    {{ "macroType": "maps|reviews|delivery|booking|marketplace|social|appstore|forums|news|jobs|other",
      "platformName": "e.g. Google Maps, TripAdvisor, Zomato, Swiggy, Yelp, Booking.com",
      "why": "1 sentence",
      "searchHints": ["optional short terms/domains"]
    }}
  ],
  "searchQueries": [
    {{ "priority": 1, "query": "string", "goal": "reviews|listings|competitors|funding|news|discussions|pricing" }}
  ]
}}

Scope and region rules:
- scope=global: business clearly targets many countries/regions. coveredRegion="", scopeGranularity omitted.
- scope=local: business has a primary market. Set coveredRegion and scopeGranularity accordingly.
- Infer scope from landing copy: local cues = city/state names, "serving X", "based in", single-location; global cues = "worldwide", "global", many countries listed.

Search query rules (CRITICAL for local businesses):
- When scope=local, ALL competitor/review/listing queries MUST include the covered region.
- When scope=global, use brand/category without forcing a region.
- Include 12-20 queries ordered by priority (1 = highest).
- Do NOT hallucinate obscure platforms; keep platformHypotheses practical (8-20).

businessUrl: {business_url}
regionHint: {region_hint}
languageHint: {language_hint}

landingSummary / scraped context (use this to infer scope, region, and business type):
{landing_summary}
"""


async def run_platform_scout(
    message: str,
    args: dict[str, Any] | None,
    on_progress: ProgressCb | None,
) -> SkillRunResult:
    started = time.time()
    await _emit(on_progress, {"stage": "running", "type": "task", "message": "Analyzing business context"})

    args = args or {}
    business_url = str(args.get("businessUrl", "")).strip() or _extract_url(message)
    region_hint = str(args.get("regionHint", "")).strip()
    language_hint = str(args.get("language", "") or args.get("languageHint", "")).strip()
    landing_summary = str(args.get("landingSummary", "")).strip() or message[:3500]

    if (get_settings().OPENROUTER_API_KEY or "").strip():
        try:
            prompt = _SCOUT_PROMPT_TEMPLATE.format(
                business_url=business_url or "(unknown)",
                region_hint=region_hint or "(none)",
                language_hint=language_hint or "(none)",
                landing_summary=landing_summary[:3500] or "(none)",
            )

            if GEMINI_SCOUT_MODELS:
                model_ids = [m.strip() for m in GEMINI_SCOUT_MODELS.split(",") if m.strip()]
            else:
                from app.doable_claw_agent.agent.gemini_models import get_planner_models
                model_ids = get_planner_models()

            for model_id in model_ids:
                try:
                    parsed = await _ai.complete_json_with_candidates(
                        model_candidates=_ai.model_candidates(
                            model_id,
                            prefix_env="OPENROUTER_MODEL_PREFIX",
                        ),
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=2200,
                    )
                    normalized = {
                        "businessTypeGuess": parsed.get("businessTypeGuess") or "",
                        "regionGuess": parsed.get("regionGuess") or "",
                        "scope": "local" if parsed.get("scope") == "local" else "global",
                        "coveredRegion": str(parsed.get("coveredRegion") or "").strip(),
                        "scopeGranularity": parsed.get("scopeGranularity"),
                        "platformHypotheses": (
                            parsed.get("platformHypotheses")
                            if isinstance(parsed.get("platformHypotheses"), list) else []
                        ),
                        "searchQueries": (
                            parsed.get("searchQueries")
                            if isinstance(parsed.get("searchQueries"), list) else []
                        ),
                    }
                    text = _format_scout_text(normalized)
                    data = {
                        "model": model_id,
                        "businessUrl": business_url,
                        "regionHint": region_hint,
                        "languageHint": language_hint,
                        "result": normalized,
                        "scope": normalized["scope"],
                        "coveredRegion": normalized["coveredRegion"],
                    }
                    return SkillRunResult(
                        status="ok", text=text, error=None, data=data,
                        duration_ms=int((time.time() - started) * 1000),
                    )
                except Exception as e:
                    status_code = getattr(getattr(e, "response", None), "status_code", None)
                    if status_code in (429, 503) and model_ids.index(model_id) < len(model_ids) - 1:
                        continue
                    break
        except Exception:
            pass

    data, text = _platform_scout_heuristic(message, business_url, region_hint)
    return SkillRunResult(
        status="ok", text=text, error=None, data=data,
        duration_ms=int((time.time() - started) * 1000),
    )

