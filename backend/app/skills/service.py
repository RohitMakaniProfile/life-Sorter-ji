from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.phase2.ai import AiHelper
from app.config import GEMINI_API_KEY, GEMINI_SCOUT_MODELS, OPENAI_MODEL, PYTHON_BIN, SKILLS_ROOT
from app.phase2.stores import find_latest_scrape_cache_by_url, find_scraped_pages_for_base_url
import httpx

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]


def _json_default(value: Any) -> Any:
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    return str(value)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        try:
            print(
                "[skills.service] json-dumps-failed",
                {
                    "error": str(exc),
                    "value_type": type(value).__name__,
                    "traceback": traceback.format_exc(),
                },
            )
        except Exception:
            pass
        raise


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _parse_progress_meta(raw_line: str) -> dict[str, Any]:
    """
    Parse a PROGRESS line robustly:
    - strips ANSI escapes that can appear in container logs
    - extracts the JSON object segment even if line has prefixes/suffixes
    - falls back to info/raw event when JSON is not present
    """
    cleaned = _ANSI_RE.sub("", str(raw_line or "")).strip()
    if not cleaned:
        return {"event": "info", "raw": ""}

    # Fast path: pure JSON line.
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Extract likely JSON object region from noisy line.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {"event": "info", "raw": cleaned}


def _extract_json_objects_from_text(text: str) -> tuple[list[dict[str, Any]], str]:
    out: list[dict[str, Any]] = []
    dec = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] != "{":
            i += 1
        if i >= n:
            return out, ""
        try:
            obj, j = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            return out, text[i:]
        if isinstance(obj, dict):
            out.append(obj)
        i = j
    return out, ""


@dataclass
class SkillManifest:
    id: str
    name: str
    description: str
    emoji: str
    entry: str
    directory: Path
    stages: list[str]
    stage_labels: dict[str, str]
    input_schema: dict[str, Any] | None
    summary_mode: str = "single"
    summary_array_path: str | None = None
    summary_content_field: str = "snapshot"
    summary_url_field: str = "url"


@dataclass
class SkillRunResult:
    status: str
    text: str
    error: str | None
    data: Any
    duration_ms: int


_SKILLS: dict[str, SkillManifest] = {}


def _default_stage_labels() -> dict[str, str]:
    return {
        "thinking": "Thinking",
        "running": "Running",
        "done": "Done",
        "error": "Error",
    }


def load_skills() -> None:
    global _SKILLS
    skills: dict[str, SkillManifest] = {}

    if SKILLS_ROOT.exists():
        for child in sorted(SKILLS_ROOT.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "skill.json"
            if not manifest_path.exists():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            sid = str(raw.get("id", "")).strip()
            entry = str(raw.get("entry", "")).strip()
            if not sid or not entry:
                continue
            labels = raw.get("stageLabels") if isinstance(raw.get("stageLabels"), dict) else {}
            stage_labels = {**_default_stage_labels(), **{str(k): str(v) for k, v in labels.items()}}
            stages = raw.get("stages") if isinstance(raw.get("stages"), list) else ["thinking", "running", "done"]
            post_summary = raw.get("postprocessSummary") if isinstance(raw.get("postprocessSummary"), dict) else {}
            summary_mode = str(post_summary.get("mode") or "single").strip().lower()
            if summary_mode not in ("single", "multi_page"):
                summary_mode = "single"
            skills[sid] = SkillManifest(
                id=sid,
                name=str(raw.get("name", sid)),
                description=str(raw.get("description", "")),
                emoji=str(raw.get("emoji", "🛠️")),
                entry=entry,
                directory=child,
                stages=[str(s) for s in stages],
                stage_labels=stage_labels,
                input_schema=raw.get("inputSchema") if isinstance(raw.get("inputSchema"), dict) else None,
                summary_mode=summary_mode,
                summary_array_path=str(post_summary.get("arrayPath")).strip() if post_summary.get("arrayPath") else None,
                summary_content_field=str(post_summary.get("contentField") or "snapshot"),
                summary_url_field=str(post_summary.get("urlField") or "url"),
            )

    # Built-in platform-scout (TS-only in original, reimplemented here)
    if "platform-scout" not in skills:
        skills["platform-scout"] = SkillManifest(
            id="platform-scout",
            name="Platform Scout",
            description="Infer business scope and build review + competitor queries",
            emoji="🧭",
            entry="",
            directory=SKILLS_ROOT,
            stages=["thinking", "running", "done"],
            stage_labels=_default_stage_labels(),
            input_schema={
                "type": "object",
                "properties": {
                    "businessUrl": {"type": "string"},
                    "regionHint": {"type": "string"},
                    "languageHint": {"type": "string"},
                },
            },
        )

    _SKILLS = skills


def get_skill(skill_id: str) -> SkillManifest | None:
    return _SKILLS.get(skill_id)


def list_skills() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in _SKILLS.values():
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "emoji": s.emoji,
                "description": s.description,
                "stages": s.stages,
                "stageLabels": s.stage_labels,
                "inputSchema": s.input_schema,
            }
        )
    return out


def first_skill_id() -> str | None:
    for sid in _SKILLS.keys():
        return sid
    return None


def _extract_url(message: str) -> str:
    m = re.search(r"https?://\S+", message or "")
    if not m:
        return ""
    return m.group(0).rstrip("),.;]\"'")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _get_by_path(data: Any, path: str | None) -> Any:
    if not path:
        return data
    cur = data
    for token in [p for p in path.split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(token)
        else:
            return None
    return cur


def _progress_stream_kind(meta: dict[str, Any]) -> str:
    explicit = str(meta.get("streamKind") or "").strip().lower()
    if explicit in ("info", "data"):
        return explicit
    evt = str(meta.get("event") or "").strip().lower()
    if evt in {"page_data", "data", "result", "record", "item"}:
        return "data"
    return "info"


async def _emit_summary_token_usage(
    on_progress: ProgressCb | None,
    *,
    stage: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(
            {
                "stage": "running",
                "type": "task",
                "message": f"Token usage recorded ({stage})",
                "meta": {
                    "kind": "token-usage",
                    "stage": stage,
                    "provider": ("anthropic" if CLAUDE_API_KEY else "openai"),
                    "model": (CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL),
                    "inputTokens": int(input_tokens or 0),
                    "outputTokens": int(output_tokens or 0),
                },
            }
        )
    except Exception:
        pass


async def _summarize_single(
    skill_id: str,
    data: Any,
    fallback_text: str,
    *,
    on_progress: ProgressCb | None = None,
) -> str:
    try:
        raw_json = _json_dumps(data)
    except Exception:
        return fallback_text
    raw_json = raw_json[:120_000]
    ai = AiHelper(temperature=0.2)
    prompt = "\n".join(
        [
            f"Skill: {skill_id}",
            "Convert this raw JSON output into compact, faithful natural-language Markdown.",
            "Rules:",
            "- Preserve all information categories/keys at least once.",
            "- Remove repetitive wording and duplicate entries.",
            "- For long arrays, summarize with counts and representative examples.",
            "- Do not invent data.",
            "",
            "Raw JSON:",
            raw_json,
        ]
    )
    res = await ai.chat(
        message=prompt,
        system_prompt="You are a precise data-to-text formatter. Keep full coverage with minimal redundancy.",
    )
    await _emit_summary_token_usage(
        on_progress,
        stage=f"skill-summary.{skill_id}",
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
    )
    text = (res.message or "").strip()
    return text or fallback_text


async def _summarize_multi_page(
    skill_id: str,
    data: Any,
    *,
    array_path: str | None,
    content_field: str,
    url_field: str,
    fallback_text: str,
    on_progress: ProgressCb | None = None,
) -> str:
    pages = _get_by_path(data, array_path)
    if not isinstance(pages, list) or not pages:
        return await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)

    ai = AiHelper(temperature=0.2)
    blocks: list[str] = []

    for idx, item in enumerate(pages, start=1):
        if not isinstance(item, dict):
            continue
        page_url = str(item.get(url_field) or f"(page {idx})")
        page_content = _clean_text(str(item.get(content_field) or ""))
        if not page_content:
            continue
        page_content = page_content[:14_000]
        prompt = "\n".join(
            [
                f"Skill: {skill_id}",
                f"Page URL: {page_url}",
                "Rewrite the page content into concise natural language, preserving all key information and removing redundant words/repetition.",
                "Do not invent data. Keep it compact and faithful.",
                "",
                "Page content:",
                page_content,
            ]
        )
        try:
            res = await ai.chat(
                message=prompt,
                system_prompt="You compress webpage extraction text into faithful natural-language notes.",
            )
            await _emit_summary_token_usage(
                on_progress,
                stage=f"skill-summary.{skill_id}.page",
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
            )
            page_summary = (res.message or "").strip()
        except Exception:
            page_summary = page_content
        if page_summary:
            blocks.append(f"page: {page_url}\ncontent: {page_summary}")

    if not blocks:
        return await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)
    return "\n\n".join(blocks)


async def _summarize_multi_page_entries(
    skill_id: str,
    data: Any,
    *,
    array_path: str | None,
    content_field: str,
    url_field: str,
    fallback_text: str,
    on_progress: ProgressCb | None = None,
) -> tuple[list[dict[str, Any]], str]:
    pages = _get_by_path(data, array_path)
    if not isinstance(pages, list) or not pages:
        return [], await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)

    ai = AiHelper(provider="openai", temperature=0.2)
    entries: list[dict[str, Any]] = []
    blocks: list[str] = []

    for idx, item in enumerate(pages, start=1):
        if not isinstance(item, dict):
            continue
        page_url = str(item.get(url_field) or f"(page {idx})")
        page_content = _clean_text(str(item.get(content_field) or ""))
        if not page_content:
            continue
        page_content = page_content[:14_000]
        prompt = "\n".join(
            [
                f"Skill: {skill_id}",
                f"Page URL: {page_url}",
                "Rewrite the page content into concise natural language, preserving all key information and removing redundant words/repetition.",
                "Do not invent data. Keep it compact and faithful.",
                "",
                "Page content:",
                page_content,
            ]
        )
        try:
            res = await ai.chat(
                message=prompt,
                system_prompt="You compress webpage extraction text into faithful natural-language notes.",
            )
            await _emit_summary_token_usage(
                on_progress,
                stage=f"skill-summary.{skill_id}.page",
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
            )
            page_summary = (res.message or "").strip()
        except Exception:
            page_summary = page_content
        if page_summary:
            entries.append({"url": page_url, "raw": item, "text": page_summary})
            blocks.append(f"page: {page_url}\ncontent: {page_summary}")

    if not blocks:
        return [], await _summarize_single(skill_id, data, fallback_text, on_progress=on_progress)
    return entries, "\n\n".join(blocks)


def _is_homepage_scrape(args: dict[str, Any] | None) -> bool:
    if not isinstance(args, dict):
        return False
    max_pages = int(args.get("maxPages") or 0)
    max_depth = int(args.get("maxDepth") or 0)
    deep = bool(args.get("deep")) if "deep" in args else False
    if max_pages <= 1:
        return True
    return max_depth <= 0 and not deep


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


async def _run_platform_scout(message: str, args: dict[str, Any] | None, on_progress: ProgressCb | None) -> SkillRunResult:
    started = time.time()
    await _emit(on_progress, {"stage": "running", "type": "task", "message": "Analyzing business context"})

    args = args or {}
    business_url = str(args.get("businessUrl", "")).strip() or _extract_url(message)
    region_hint = str(args.get("regionHint", "")).strip()
    language_hint = str(args.get("language", "") or args.get("languageHint", "")).strip()
    landing_summary = str(args.get("landingSummary", "")).strip() or message[:3500]

    if GEMINI_API_KEY:
        try:
            from google import genai  # type: ignore

            prompt = _SCOUT_PROMPT_TEMPLATE.format(
                business_url=business_url or "(unknown)",
                region_hint=region_hint or "(none)",
                language_hint=language_hint or "(none)",
                landing_summary=landing_summary[:3500] or "(none)",
            )

            if GEMINI_SCOUT_MODELS:
                model_ids = [m.strip() for m in GEMINI_SCOUT_MODELS.split(",") if m.strip()]
            else:
                from app.phase2.agent.gemini_models import get_gemini_models
                model_ids = get_gemini_models()

            client = genai.Client(api_key=GEMINI_API_KEY)
            last_err: Exception | None = None

            for model_id in model_ids:
                try:
                    res = await client.aio.models.generate_content(
                        model=model_id,
                        contents=prompt,
                        config={"response_mime_type": "application/json"},
                    )
                    raw = (res.text or "").strip()
                    parsed = json.loads(raw)

                    normalized = {
                        "businessTypeGuess": parsed.get("businessTypeGuess") or "",
                        "regionGuess": parsed.get("regionGuess") or "",
                        "scope": "local" if parsed.get("scope") == "local" else "global",
                        "coveredRegion": str(parsed.get("coveredRegion") or "").strip(),
                        "scopeGranularity": parsed.get("scopeGranularity"),
                        "platformHypotheses": parsed.get("platformHypotheses") if isinstance(parsed.get("platformHypotheses"), list) else [],
                        "searchQueries": parsed.get("searchQueries") if isinstance(parsed.get("searchQueries"), list) else [],
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
                    return SkillRunResult(status="ok", text=text, error=None, data=data, duration_ms=int((time.time() - started) * 1000))

                except Exception as e:
                    last_err = e
                    err_msg = str(e).lower()
                    is_retryable = any(k in err_msg for k in ["503", "429", "unavailable", "resource_exhausted", "overloaded", "high demand"])
                    if is_retryable and model_ids.index(model_id) < len(model_ids) - 1:
                        continue
                    break

        except Exception:
            pass

    data, text = _platform_scout_heuristic(message, business_url, region_hint)
    return SkillRunResult(status="ok", text=text, error=None, data=data, duration_ms=int((time.time() - started) * 1000))


async def _emit(on_progress: ProgressCb | None, event: dict[str, Any]) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(event)
    except Exception as exc:
        try:
            print(f"[skills.service] on_progress-failed | {exc}")
        except Exception:
            pass


async def _stream_skill_subprocess_stdout(
    proc: asyncio.subprocess.Process,
    on_progress: ProgressCb | None,
) -> tuple[str, bytes, str, int]:
    """
    Read skill runner stdout line-by-line so PROGRESS: events reach on_progress immediately.

    Using proc.communicate() buffers all stdout until the subprocess exits, which breaks
    live discovery/page updates for long-running skills (e.g. scrape-playwright).
    """
    assert proc.stdout is not None
    stdout_parts: list[str] = []
    result_line = ""

    async def _drain_stderr() -> bytes:
        if proc.stderr:
            return await proc.stderr.read()
        return b""

    stderr_task = asyncio.create_task(_drain_stderr())

    try:
        while True:
            line_b = await proc.stdout.readline()
            if not line_b:
                break
            chunk = line_b.decode("utf-8", errors="replace")
            stdout_parts.append(chunk)
            for raw in chunk.splitlines():
                t = raw.strip()
                if not t:
                    continue
                if t.startswith("PROGRESS:"):
                    raw_json = t[len("PROGRESS:") :].strip()
                    meta = _parse_progress_meta(raw_json)
                    meta["streamKind"] = _progress_stream_kind(meta)
                    event_name = str(meta.get("event", "info"))
                    message_text = str(meta.get("url") or meta.get("message") or event_name)
                    await _emit(
                        on_progress,
                        {
                            "stage": "running",
                            "type": "info",
                            "message": message_text,
                            "meta": meta,
                        },
                    )
                else:
                    result_line = t
    finally:
        pass

    stderr_data = await stderr_task
    exit_code = await proc.wait()
    return "".join(stdout_parts), stderr_data, result_line, exit_code


async def run_skill(
    skill_id: str,
    message: str,
    history: list[dict[str, Any]] | None = None,
    args: dict[str, Any] | None = None,
    on_progress: ProgressCb | None = None,
) -> SkillRunResult:
    manifest = get_skill(skill_id)
    if not manifest:
        return SkillRunResult(status="error", text="", error=f"Unknown skill: {skill_id}", data=None, duration_ms=0)

    if skill_id == "platform-scout":
        return await _run_platform_scout(message, args, on_progress)

    # Offload Playwright-heavy crawling to dedicated scraper microservice.
    if skill_id == "scrape-playwright":
        safe_args = args or {}
        lookup_url = str(safe_args.get("url") or "").strip() or _extract_url(message)
        result: SkillRunResult
        if lookup_url and _is_homepage_scrape(safe_args):
            cached = await find_latest_scrape_cache_by_url(lookup_url)
            if cached and cached.get("data") is not None:
                await _emit(
                    on_progress,
                    {
                        "stage": "running",
                        "type": "info",
                        "message": f"cache hit for {lookup_url}",
                        "meta": {
                            "event": "cache_hit",
                            "url": lookup_url,
                            "cacheSkillCallId": str(cached.get("id") or ""),
                        },
                    },
                )
                result = SkillRunResult(status="ok", text="", error=None, data=cached.get("data"), duration_ms=0)
            else:
                result = await _run_scrape_playwright_remote(message=message, args=safe_args, on_progress=on_progress)
        else:
            result = await _run_scrape_playwright_remote(message=message, args=safe_args, on_progress=on_progress)

        if result.status == "ok" and result.data is not None and manifest.summary_mode in ("single", "multi_page"):
            try:
                if manifest.summary_mode == "multi_page":
                    page_entries, summary_text = await _summarize_multi_page_entries(
                        skill_id=skill_id,
                        data=result.data,
                        array_path=manifest.summary_array_path,
                        content_field=manifest.summary_content_field,
                        url_field=manifest.summary_url_field,
                        fallback_text=result.text,
                        on_progress=on_progress,
                    )
                    result.text = summary_text
                    if page_entries and isinstance(result.data, dict):
                        result.data = {**result.data, "_pageEntries": page_entries}
                else:
                    result.text = await _summarize_single(
                        skill_id=skill_id,
                        data=result.data,
                        fallback_text=result.text,
                        on_progress=on_progress,
                    )
            except Exception:
                pass
        return result

    script_path = manifest.directory / manifest.entry
    if not script_path.exists():
        return SkillRunResult(status="error", text="", error=f"Skill entry not found: {script_path}", data=None, duration_ms=0)

    started = time.time()
    payload: dict[str, Any] = {
        "message": message,
        "history": history or [],
        "skillId": skill_id,
        "runId": f"{skill_id}-{int(started * 1000)}",
    }
    if args:
        payload["args"] = args

    proc = await asyncio.create_subprocess_exec(
        PYTHON_BIN,
        "-u",
        str(script_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert proc.stdin is not None
    proc.stdin.write(_json_dumps(payload).encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    stdout_text, stderr_data, result_line, exit_code = await _stream_skill_subprocess_stdout(proc, on_progress)
    stderr_text = stderr_data.decode("utf-8", errors="replace").strip()

    text = stdout_text.strip()
    err: str | None = None
    data: Any = None

    parse_target = result_line or stdout_text.strip()
    if parse_target:
        try:
            parsed = json.loads(parse_target)
            if isinstance(parsed, dict):
                if isinstance(parsed.get("text"), str):
                    text = parsed.get("text") or ""
                if parsed.get("data") is not None:
                    data = parsed.get("data")
                if parsed.get("error"):
                    err = str(parsed.get("error"))
        except Exception:
            pass

    if exit_code != 0 and not err:
        err = stderr_text or f"Skill exited with code {exit_code}"

    status = "error" if err else "ok"
    if not text and err:
        text = ""

    if status == "ok" and data is not None and manifest.summary_mode in ("single", "multi_page"):
        try:
            if manifest.summary_mode == "multi_page":
                text = await _summarize_multi_page(
                    skill_id=skill_id,
                    data=data,
                    array_path=manifest.summary_array_path,
                    content_field=manifest.summary_content_field,
                    url_field=manifest.summary_url_field,
                    fallback_text=text,
                    on_progress=on_progress,
                )
            else:
                text = await _summarize_single(skill_id=skill_id, data=data, fallback_text=text, on_progress=on_progress)
        except Exception:
            pass

    return SkillRunResult(
        status=status,
        text=text,
        error=err,
        data=data,
        duration_ms=int((time.time() - started) * 1000),
    )


async def _run_scrape_playwright_remote(*, message: str, args: dict[str, Any], on_progress: ProgressCb | None) -> SkillRunResult:
    started = time.time()
    base = os.getenv("SCRAPER_BASE_URL", "").strip().rstrip("/")
    if not base:
        return SkillRunResult(
            status="error",
            text="",
            error="SCRAPER_BASE_URL not configured",
            data=None,
            duration_ms=0,
        )

    url = str(args.get("url") or "").strip() or _extract_url(message)
    if not url:
        return SkillRunResult(
            status="error",
            text="scrape-playwright: missing url",
            error="missing_url",
            data=None,
            duration_ms=int((time.time() - started) * 1000),
        )

    payload: dict[str, Any] = {"url": url}
    for k in ("maxPages", "maxDepth", "deep", "parallel"):
        if k in args and args[k] is not None:
            payload[k] = args[k]

    existing_pages = await find_scraped_pages_for_base_url(url)
    existing_urls = sorted(
        {
            str(p.get("url") or "").strip().rstrip("/")
            for p in existing_pages
            if isinstance(p, dict) and str(p.get("url") or "").strip()
        }
    )
    if existing_urls:
        await _emit(
            on_progress,
            {
                "stage": "running",
                "type": "info",
                "message": f"reusing {len(existing_urls)} previously scraped urls",
                "meta": {
                    "event": "reuse_existing_urls",
                    "url": url,
                    "reusedCount": len(existing_urls),
                },
            },
        )

    resume_ck = args.get("resumeCheckpoint") if isinstance(args.get("resumeCheckpoint"), dict) else None
    skip_list = args.get("skipUrls") if isinstance(args.get("skipUrls"), list) else None
    if resume_ck:
        payload["resumeCheckpoint"] = resume_ck
    merged_skip: list[str] = []
    if skip_list:
        merged_skip.extend([str(u).strip() for u in skip_list if str(u).strip()])
    merged_skip.extend(existing_urls)
    deduped_skip = sorted({u.rstrip("/") or u for u in merged_skip if u})
    if deduped_skip:
        payload["skipUrls"] = deduped_skip

    done_result: dict[str, Any] | None = None
    err: str | None = None

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{base}/v1/scrape-playwright/stream",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code >= 400:
                err_text = (await resp.aread()).decode("utf-8", errors="replace")
                return SkillRunResult(
                    status="error",
                    text="",
                    error=f"scraper_http_{resp.status_code}: {err_text.strip() or 'request failed'}",
                    data=None,
                    duration_ms=int((time.time() - started) * 1000),
                )

            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:") :].strip()
                if not raw:
                    continue
                try:
                    meta = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(meta, dict):
                    continue

                # Some scraper builds can carry concatenated JSON progress inside an
                # info.message string. Recover nested events so page_data/checkpoint
                # are not dropped by upstream parsers.
                if str(meta.get("event") or "").strip().lower() == "info" and isinstance(meta.get("message"), str):
                    nested, _ = _extract_json_objects_from_text(str(meta.get("message") or ""))
                    if nested:
                        for item in nested:
                            item["streamKind"] = _progress_stream_kind(item)
                            event_name = str(item.get("event", "info"))
                            message_text = str(item.get("url") or item.get("message") or event_name)
                            await _emit(
                                on_progress,
                                {
                                    "stage": "running",
                                    "type": "info",
                                    "message": message_text,
                                    "meta": item,
                                },
                            )
                        continue

                # done event: {event:"done", result:{text,data,error?}}
                if str(meta.get("event") or "").strip().lower() == "done" and isinstance(meta.get("result"), dict):
                    done_result = meta["result"]
                    continue

                # Forward progress into existing pipeline shape.
                meta["streamKind"] = _progress_stream_kind(meta)
                event_name = str(meta.get("event", "info"))
                message_text = str(meta.get("url") or meta.get("message") or event_name)
                await _emit(
                    on_progress,
                    {
                        "stage": "running",
                        "type": "info",
                        "message": message_text,
                        "meta": meta,
                    },
                )

    if done_result is None:
        err = "scraper_stream_ended_without_done"
        return SkillRunResult(
            status="error",
            text="",
            error=err,
            data=None,
            duration_ms=int((time.time() - started) * 1000),
        )

    if done_result.get("error"):
        err = str(done_result.get("error"))

    text = str(done_result.get("text") or "")
    data = done_result.get("data")
    # Backward-compatible fallback: some scraper builds return the payload object
    # directly instead of nesting it under result.data.
    if data is None and isinstance(done_result, dict):
        legacy_keys = {"base_url", "scraped_urls", "failed_urls", "stats", "pages"}
        if legacy_keys.intersection(done_result.keys()):
            data = done_result
    if isinstance(data, dict):
        old_pages = existing_pages
        new_pages = data.get("pages") if isinstance(data.get("pages"), list) else []
        merged: dict[str, dict[str, Any]] = {}
        for p in old_pages:
            if not isinstance(p, dict):
                continue
            pu = str(p.get("url") or "").strip().rstrip("/")
            if pu:
                merged[pu] = p
        for p in new_pages:
            if not isinstance(p, dict):
                continue
            pu = str(p.get("url") or "").strip().rstrip("/")
            if pu:
                merged[pu] = p
        if merged:
            data = {**data, "pages": list(merged.values()), "reusedPageCount": len(old_pages)}
    status = "error" if err else "ok"

    return SkillRunResult(
        status=status,
        text=text,
        error=err,
        data=data,
        duration_ms=int((time.time() - started) * 1000),
    )
