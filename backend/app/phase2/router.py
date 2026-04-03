from __future__ import annotations

import asyncio
import json
import re
import time as _time
import traceback
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.services.ai_helper import ai_helper as _ai
from .agent.final_formatter import format_final_answer
from app.config import CLAUDE_API_KEY, CLAUDE_MODEL, OPENAI_MODEL, STORAGE_BUCKET
from app.skills.service import first_skill_id, get_skill, run_skill
from app.services import unified_chat_service
from .stores import (
    append_skill_streamed_text,
    append_assistant_placeholder,
    append_message,
    claim_plan_run_for_execution,
    create_plan_run,
    create_skill_call,
    get_agent,
    get_or_create_conversation,
    get_plan_run,
    get_skill_calls_by_message_id,
    get_skill_calls_by_message_id_full,
    get_token_usage,
    save_token_usage,
    fetch_skill_call_output,
    push_skill_output,
    save_stage_outputs,
    set_skill_call_result,
    update_message_content,
    update_message_meta,
    update_plan_run,
)

router = APIRouter()
_PLAN_BG_TASKS: dict[str, asyncio.Task] = {}


def is_plan_background_task_running(plan_id: str) -> bool:
    task = _PLAN_BG_TASKS.get(plan_id)
    return bool(task and not task.done())


def _register_plan_bg_task(plan_id: str, task: asyncio.Task) -> None:
    _PLAN_BG_TASKS[plan_id] = task

    def _cleanup(done_task: asyncio.Task) -> None:
        current = _PLAN_BG_TASKS.get(plan_id)
        if current is done_task:
            _PLAN_BG_TASKS.pop(plan_id, None)

    task.add_done_callback(_cleanup)


def _actor_from_payload(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip() or None
    user_id = str(payload.get("userId") or payload.get("user_id") or "").strip() or None
    return session_id, user_id

def _log(label: str, **fields: Any) -> None:
    try:
        print(f"[phase2.router] {label} | {json.dumps(fields, default=str, ensure_ascii=False)}")
    except Exception:
        print(f"[phase2.router] {label} | <log-serialize-error>")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_url_from_message(msg: str) -> str:
    raw = msg or ""
    m = re.search(r"https?://[^\s]+", raw, re.I)
    if m:
        return m.group(0).rstrip("),.;]\"'")
    # Bare hostname (e.g. "endee.io" / "www.endee.io") — plan + skills need a URL
    m2 = re.search(
        r"(?:^|[\s\n])((?:https?://)?(?:www\.)?[\w-]+\.(?:[a-z]{2,24}))\b",
        raw,
        re.I,
    )
    if not m2:
        return ""
    candidate = m2.group(1).strip().rstrip("),.;]\"'")
    low = candidate.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return candidate
    return f"https://{candidate.lstrip('/')}"


def _is_execution_intent(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    # Explicit research / analysis asks (even when URL is bare-domain only)
    if re.search(r"\bdeep\s+analysis\b|\bdeep\s+dive\b|deep-dive", text):
        return True
    if _extract_url_from_message(message):
        return True

    execution_hints = (
        "analyze",
        "audit",
        "report",
        "strategy",
        "research",
        "competitor",
        "market",
        "crawl",
        "scrape",
        "playbook",
        "roadmap",
        "go to market",
        "gtm",
        "positioning",
        "icp",
        "persona",
        "pricing",
        "website",
        "business",
    )
    conversational_hints = (
        "what is",
        "who is",
        "explain",
        "define",
        "difference between",
        "how are you",
        "hello",
        "hi",
        "thanks",
        "thank you",
    )
    if any(h in text for h in conversational_hints) and not any(h in text for h in execution_hints):
        return False
    return any(h in text for h in execution_hints)


def _skill_display_name(skill_id: str) -> str:
    manifest = get_skill(skill_id)
    if manifest and str(manifest.name or "").strip():
        return str(manifest.name).strip()
    return " ".join(part.capitalize() for part in skill_id.replace("_", "-").split("-") if part).strip() or skill_id


@lru_cache(maxsize=1)
def _load_default_phase2_contexts() -> dict[str, str]:
    cfg_dir = Path(__file__).resolve().parents[2] / "config"
    processing = cfg_dir / "phase2_processing.context.md"
    output = cfg_dir / "phase2_output.context.md"
    try:
        processing_text = processing.read_text(encoding="utf-8").strip()
    except Exception:
        processing_text = ""
    try:
        output_text = output.read_text(encoding="utf-8").strip()
    except Exception:
        output_text = ""
    return {
        "skillSelectorContext": processing_text,
        "finalOutputFormattingContext": output_text,
    }


def _get_crawl_pages_excerpt(crawl_data: Any) -> str:
    try:
        pages = crawl_data.get("pages") if isinstance(crawl_data, dict) else None
        if not isinstance(pages, list):
            return ""
        excerpts: list[str] = []
        for p in pages[:6]:
            if not isinstance(p, dict):
                continue
            u = str(p.get("url") or "")
            snap = str(p.get("snapshot") or "")[:1200]
            excerpts.append(f"URL: {u}\nEXCERPT:\n{snap}")
        return "\n\n---\n\n".join(excerpts)
    except Exception:
        return ""


def _should_stream_page_nl(skill_id: str) -> bool:
    return skill_id in {"scrape-playwright", "scrape-agentbrowser"}


def _build_page_nl_prompt(skill_id: str, meta: dict[str, Any]) -> str:
    url = str(meta.get("url") or "")
    title = str(meta.get("title") or "")
    desc = str(meta.get("meta_description") or "")
    elements = meta.get("elements") if isinstance(meta.get("elements"), list) else []
    lines: list[str] = []
    for el in elements[:400]:
        if not isinstance(el, dict):
            continue
        t = str(el.get("type") or "").strip().lower() or "text"
        c = str(el.get("content") or "").strip()
        if not c:
            continue
        lines.append(f"{t}: {c}")
    element_sequence = "\n".join(lines)[:14000]
    body = str(meta.get("snapshot") or "")
    body = body[:6000]
    return "\n".join(
        [
            f"Skill: {skill_id}",
            f"URL: {url}",
            f"Title: {title}",
            f"Meta description: {desc}",
            "",
            "Convert this structured page extraction into concise natural language.",
            "Preserve key evidence, remove repetition, do not invent facts.",
            "Use the DOM sequence to preserve local context between headings and nearby items.",
            "",
            "DOM-ordered typed elements:",
            element_sequence,
            "",
            "Fallback raw text (only if needed):",
            body,
        ]
    )


def _scrape_failure_recoverable(err: str | None) -> bool:
    if not err:
        return False
    e = str(err).lower()
    if "scraper_base_url not configured" in e or "missing_url" in e:
        return False
    return any(
        part in e
        for part in (
            "scraper_stream_ended_without_done",
            "scraper_http_",
            "connection",
            "timeout",
            "connecterror",
            "readerror",
            "remoteprotocol",
            "playwright_scraper_failed",
        )
    )


def _latest_parallel_checkpoint_from_output(rows: list[Any]) -> dict[str, Any] | None:
    for entry in reversed(rows):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "checkpoint":
            continue
        pl = entry.get("payload")
        if not isinstance(pl, dict):
            continue
        if int(pl.get("v") or 0) != 1 or not pl.get("parallel"):
            continue
        return pl
    return None


def _skip_urls_from_scrape_output(rows: list[Any]) -> list[str]:
    seen: set[str] = set()
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "progress":
            pl = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            ev = str(entry.get("event") or pl.get("event") or "").strip().lower()
            if ev == "page_data":
                u = str(pl.get("url") or "").strip()
                if u:
                    seen.add(u.rstrip("/") or u)
        elif entry.get("type") == "checkpoint":
            pl = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            for u in pl.get("scraped_urls") or []:
                su = str(u).strip()
                if su:
                    seen.add(su.rstrip("/") or su)
    return sorted(seen)


def _normalize_scout_queries(
    scout_data: Any,
    scan_data: Any,
    url: str,
) -> tuple[list[str], str, str, str, str]:
    if not isinstance(scout_data, dict):
        scout_data = {}
    if not isinstance(scan_data, dict):
        scan_data = {}

    result = scout_data.get("result") if isinstance(scout_data.get("result"), dict) else scout_data
    inferred_scope = str(result.get("scope") or scout_data.get("scope") or "")
    covered_region = str(result.get("coveredRegion") or scout_data.get("coveredRegion") or "")
    business_type_guess = str(result.get("businessTypeGuess") or "")
    market_guess = str(
        result.get("marketGuess")
        or scout_data.get("marketGuess")
        or scan_data.get("market")
        or scan_data.get("category")
        or business_type_guess
        or ""
    )
    business_name = str(
        scan_data.get("name") or scan_data.get("businessName") or scan_data.get("brand") or ""
    )
    operation_type = (
        "local" if "local" in inferred_scope.lower()
        else "global" if "global" in inferred_scope.lower()
        else "unknown"
    )

    structured: list[dict[str, Any]] = []
    for q in (result.get("searchQueries") or []):
        if isinstance(q, dict) and q.get("query"):
            structured.append({"query": str(q["query"]).strip(), "priority": q.get("priority", 999)})
    legacy: list[str] = [
        str(q).strip() for q in (result.get("queries") or []) if str(q).strip()
    ]
    raw_queries = (
        [q["query"] for q in sorted(structured, key=lambda x: x["priority"])]
        if structured else legacy
    )

    audience = str(scan_data.get("targetAudience") or scan_data.get("audience") or "").strip()
    region_part = covered_region if operation_type == "local" else ""
    market_core = " ".join(filter(None, [market_guess, audience])).strip() or "business"
    competitor_base = " ".join(filter(None, [market_core, region_part])).strip()
    business_identity = " ".join(filter(None, [business_name, url, region_part])).strip()

    if not raw_queries:
        queries = [
            f"{competitor_base} competitors",
            f"{competitor_base} alternatives",
            f"best {market_core}" + (f" in {region_part}" if region_part else ""),
            f"{business_identity} customer reviews",
            f"{business_identity} listings",
        ]
        return (
            [re.sub(r"\s+", " ", q).strip() for q in queries if q.strip()],
            operation_type, covered_region, market_guess, business_name,
        )

    identity_needle = business_name.lower()
    normalized: list[str] = []
    for q in raw_queries:
        qq = re.sub(r"\s+", " ", q).strip()
        lower = qq.lower()
        if re.search(r"competitor|competitors|alternative|alternatives", lower):
            normalized.append(
                f"{competitor_base} alternatives".strip()
                if re.search(r"alternative|alternatives", lower)
                else f"{competitor_base} competitors".strip()
            )
        elif re.search(
            r"review|reviews|rating|ratings|listing|listings|google maps|zomato|swiggy|justdial|tripadvisor",
            lower,
        ):
            has_identity = bool(identity_needle) and identity_needle in lower
            normalized.append(qq if has_identity else re.sub(r"\s+", " ", f"{business_identity} {qq}").strip())
        else:
            normalized.append(qq)

    seen: set[str] = set()
    deduped = [q for q in normalized if q and not (q in seen or seen.add(q))]  # type: ignore[func-returns-value]
    return deduped, operation_type, covered_region, market_guess, business_name


def _allowed_file_path(path: str) -> bool:
    if ".." in path:
        return False
    allowed = [Path("/tmp").resolve(), Path(STORAGE_BUCKET).resolve()]
    p = Path(path).resolve()
    for root in allowed:
        if p == root or str(p).startswith(str(root) + "/"):
            return True
    return False


async def _resolve_agent_and_skill(payload: dict[str, Any]) -> dict[str, Any]:
    default_skill = first_skill_id() or "platform-scout"
    default_contexts = _load_default_phase2_contexts()

    agent_id = str(payload.get("agentId") or "").strip()
    allowed_from_request = payload.get("allowedSkillIds") if isinstance(payload.get("allowedSkillIds"), list) else []
    allowed_from_request = [str(s) for s in allowed_from_request if isinstance(s, str)]

    if agent_id:
        agent = await get_agent(agent_id)
        if agent:
            allowed = [s for s in agent.get("allowedSkillIds", []) if isinstance(s, str)]
            chosen = next((sid for sid in allowed if get_skill(sid)), default_skill)
            return {
                "agentId": agent_id,
                "skillId": chosen,
                "allowedSkillIds": allowed,
                "contexts": {
                    "skillSelectorContext": (agent.get("skillSelectorContext") or default_contexts.get("skillSelectorContext") or ""),
                    "finalOutputFormattingContext": (agent.get("finalOutputFormattingContext") or default_contexts.get("finalOutputFormattingContext") or ""),
                },
            }
        return {
            "agentId": agent_id,
            "skillId": default_skill,
            "allowedSkillIds": allowed_from_request,
            "contexts": default_contexts,
        }

    first_allowed = next((sid for sid in allowed_from_request if get_skill(sid)), None)
    chosen = first_allowed or default_skill
    return {
        "agentId": chosen,
        "skillId": chosen,
        "allowedSkillIds": allowed_from_request,
        "contexts": default_contexts,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sse(data: dict[str, Any]) -> bytes:
    try:
        return f"data: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n".encode("utf-8")
    except Exception as exc:
        _log(
            "sse-serialize-failed",
            error=str(exc),
            data_type=type(data).__name__,
            data_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        raise


async def _emit_plan_progress(
    cb,
    message: str,
    *,
    event: str | None = None,
    kind: str = "task",
) -> None:
    if cb is None:
        return
    await cb({
        "stage": "thinking",
        "type": kind,
        "message": message,
        "meta": {"event": event or "info"},
    })


async def _create_plan_draft(
    *,
    body: dict[str, Any],
    emit_progress=None,
    emit_token=None,
) -> dict[str, Any]:
    message = str(body.get("message") or "").strip()
    session_id, user_id = _actor_from_payload(body)
    _log("plan-draft-start", message_preview=message[:200], has_emit_progress=emit_progress is not None)
    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        session_id=session_id,
        user_id=user_id,
    )
    contexts = resolved.get("contexts", {})
    _log("plan-draft-conversation-resolved", conversation_id=conv.get("id"), agent_id=resolved.get("agentId"))

    user_message_id = await append_message(conv["id"], "user", message)

    placeholder = "\n".join([
        "## Plan (draft)",
        "",
        "- Collect on-site evidence (business-scan + agent browser crawl)",
        "- Run platform-scout (mandatory) to infer scope/region and generate competitor + review queries",
        "- Run web-search (mandatory) using scout queries to find competitor + review URLs",
        "- Execute remaining steps (taxonomy/classify/targeted scraping) after approval",
        "",
        "*(Generating plan...)*",
    ])
    plan_message_id = await append_message(
        conv["id"],
        "assistant",
        placeholder,
        kind="plan",
        options=["Approve", "Cancel"],
    )

    await _emit_plan_progress(emit_progress, "Analyzing request context", event="plan-started")
    url = _extract_url_from_message(message)

    async def _run_skill_for_plan(sid: str, args: dict[str, Any], input_msg: str) -> Any:
        if not get_skill(sid):
            _log("plan-skill-missing", skill_id=sid)
            return None
        skill_name = _skill_display_name(sid)
        run_id = f"plan-{plan_message_id}-{sid}-{int(_time.time() * 1000)}"
        _log("plan-skill-start", skill_id=sid, run_id=run_id, args=args)
        skill_call_id = await create_skill_call(conv["id"], plan_message_id, sid, run_id, {"args": args})
        page_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        page_worker_task: asyncio.Task | None = None

        if _should_stream_page_nl(sid):
            async def _page_worker() -> None:
                while True:
                    meta = await page_queue.get()
                    if meta is None:
                        break
                    try:
                        prompt = _build_page_nl_prompt(sid, meta)
                        r = await _ai.chat(
                            prompt,
                            system_prompt="You convert web extraction objects into compact factual notes.",
                            temperature=0.2,
                            provider="openai",
                        )
                        page_url = str(meta.get("url") or "").strip()
                        note = (r.message or "").strip()
                        if note:
                            chunk = f"page: {page_url}\ncontent: {note}\n\n"
                            await append_skill_streamed_text(skill_call_id, chunk)
                        await save_token_usage(
                            plan_message_id,
                            OPENAI_MODEL,
                            r.input_tokens,
                            r.output_tokens,
                            stage=f"page-nl.{sid}",
                            provider="openai",
                            session_id=session_id,
                        )
                    except Exception:
                        pass
            page_worker_task = asyncio.create_task(_page_worker())

        # Stream skill-call start into the plan-building stream so the UI context panel
        # can show exactly what is running during plan creation.
        if emit_progress is not None:
            try:
                await emit_progress(
                    {
                        "stage": "thinking",
                        "type": "task",
                        "message": f"Running {skill_name}",
                        "meta": {
                            "kind": "skill-call",
                            "id": run_id,
                            "skillId": sid,
                            "skillName": skill_name,
                            "status": "running",
                            "input": {"args": args},
                        },
                    }
                )
            except Exception:
                pass

        async def _on_prog(event: dict[str, Any]) -> None:
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            # Ensure meta always includes skillId for client-side inference.
            try:
                if isinstance(meta, dict) and sid:
                    meta = {**meta, "skillId": sid}
                    event = {**event, "meta": meta}
            except Exception:
                pass
            if str(meta.get("event") or "").strip():
                _log("plan-skill-progress", skill_id=sid, run_id=run_id, event=meta.get("event"), meta_keys=list(meta.keys()))
            if (
                _should_stream_page_nl(sid)
                and str(meta.get("event") or "").strip().lower() == "page_data"
                and isinstance(meta, dict)
            ):
                await page_queue.put(meta)
            # Persist progress so SSE followers can replay it during background execution.
            evt = str(meta.get("event") or "").strip().lower()
            if evt == "checkpoint" and isinstance(meta.get("payload"), dict):
                try:
                    await push_skill_output(
                        skill_call_id,
                        {"type": "checkpoint", "payload": meta["payload"]},
                    )
                except Exception:
                    pass
            elif evt in ("started", "discovered", "page", "page_data"):
                try:
                    await push_skill_output(
                        skill_call_id,
                        {
                            "type": "progress",
                            "event": evt,
                            "payload": meta,
                        },
                    )
                except Exception:
                    pass
            # Forward progress to plan stream (UI) for live context panel.
            if emit_progress is not None:
                try:
                    await emit_progress(event)
                except Exception:
                    pass

        result = await run_skill(sid, input_msg, history=conv.get("messages") or [], args=args, on_progress=_on_prog)
        _log(
            "plan-skill-finished",
            skill_id=sid,
            run_id=run_id,
            status=result.status,
            error=result.error,
            has_data=result.data is not None,
        )
        if page_worker_task is not None:
            await page_queue.put(None)
            await page_worker_task
        await set_skill_call_result(
            skill_call_id,
            "error" if result.status == "error" else "done",
            result.text, result.data, result.error,
        )
        if emit_progress is not None:
            try:
                await emit_progress(
                    {
                        "stage": "thinking" if result.status != "error" else "error",
                        "type": "task",
                        "message": f"{skill_name} {'completed' if result.status != 'error' else 'failed'}",
                        "meta": {
                            "kind": "skill-call",
                            "id": run_id,
                            "skillId": sid,
                            "skillName": skill_name,
                            "status": "done" if result.status != "error" else "error",
                            "input": {"args": args},
                            "outputSummary": (result.text or "")[:600],
                        },
                    }
                )
            except Exception:
                pass
        return result

    scan_args: dict[str, Any] = {"url": url} if url else {}
    crawl_args_plan: dict[str, Any] = (
        {
            "url": url,
            "instructions": "Scan only the homepage and extract all visible JS-rendered content.",
            "maxPages": 1,
            "maxDepth": 0,
            "deep": False,
        }
        if url else {}
    )
    crawl_args_execute: dict[str, Any] = (
        {
            "url": url,
            "instructions": "Scan whole website for business evidence. Exclude blog/news unless directly relevant to pricing, onboarding, trust, reviews, or competitor claims.",
            "maxPages": 40,
            "maxDepth": 3,
            "deep": True,
        }
        if url else {}
    )

    if url:
        _log("plan-url-detected", url=url)
        await _emit_plan_progress(emit_progress, "Reading business information from website", event="business-scan-start")
        scan_res, crawl_res = await asyncio.gather(
            _run_skill_for_plan("business-scan", scan_args, message),
            _run_skill_for_plan("scrape-playwright", crawl_args_plan, message),
        )
    else:
        await _emit_plan_progress(
            emit_progress,
            "No URL detected, planning from your prompt context",
            event="no-url",
            kind="info",
        )
        scan_res = crawl_res = None

    scan_text: str = str(scan_res.text) if scan_res and scan_res.text else ""
    scan_data: Any = scan_res.data if scan_res else None
    crawl_data: Any = crawl_res.data if crawl_res else None
    crawl_pages_excerpt = _get_crawl_pages_excerpt(crawl_data)

    scout_input = "\n".join(filter(None, [
        message,
        f"Business URL: {url}" if url else "",
        f"business-scan (text):\n{scan_text}" if scan_text else "",
        f"scrape-playwright (page excerpts):\n{crawl_pages_excerpt}" if crawl_pages_excerpt else "",
    ]))
    scout_args: dict[str, Any] = {"businessUrl": url, "regionHint": "", "language": ""} if url else {}
    await _emit_plan_progress(emit_progress, "Inferring business scope and discovery queries", event="platform-scout-start")
    scout_res = await _run_skill_for_plan("platform-scout", scout_args, scout_input) if url else None
    scout_data: Any = scout_res.data if scout_res else None

    queries, operation_type, covered_region, market_guess, business_name = _normalize_scout_queries(
        scout_data or {}, scan_data or {}, url
    )
    business_ref = business_name or "business"
    await _emit_plan_progress(
        emit_progress,
        f"Searching {business_ref} related information on web",
        event="web-search-start",
        kind="search",
    )
    web_search_args: dict[str, Any] = {
        "queries": "\n".join(queries),
        "maxResultsPerQuery": 6,
        "maxTotalResults": 40 if queries else 30,
        "region": covered_region,
        "market": market_guess,
        "operationType": operation_type,
        "coveredRegion": covered_region,
        "businessName": business_name,
        "businessUrl": url,
    }
    search_res = await _run_skill_for_plan("web-search", web_search_args, message)
    search_data: Any = search_res.data if search_res else None

    candidate_urls: list[str] = []
    if isinstance(search_data, dict):
        results_list = (
            search_data.get("result", {}).get("results")
            or search_data.get("results")
            or []
        )
        for r in (results_list if isinstance(results_list, list) else []):
            u = r.get("url") or r.get("link") if isinstance(r, dict) else None
            if isinstance(u, str) and u.startswith("http") and u not in candidate_urls:
                candidate_urls.append(u)

    planner_ctx = (contexts.get("skillSelectorContext") or "").strip()
    active_model = CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL

    plan_prompt = "\n".join(filter(None, [
        "You generate an execution plan for a deep business analysis.",
        "",
        "Inputs:",
        "- User request",
        "- On-site evidence (business-scan + crawl excerpts)",
        "- Platform scout output (scope/locality + queries)",
        "- Web search results (candidate URLs)",
        "",
        "Requirements:",
        "- Output MUST be Markdown only.",
        "- Plan must contain a TODO checklist (Markdown checkboxes) that, when completed, guarantees enough evidence to write the final report.",
        "- The checklist must adapt to local vs global scope. If local, include locality/region-specific tasks.",
        "- The plan should be built USING the business context, but should not dump raw scraped data.",
        "- Competitor discovery queries must be market/category + audience + (if local) region based; avoid using only business name for competitor search.",
        "- Review/listing discovery should target exact business identity (name/domain + location for local businesses).",
        '- Include a section titled "Phase 6 — Targeted Collection (Reviews + Competitors)".',
        '- Include a short "Assumptions to verify" section so user can confirm the inferred basics (scope/region/category).',
        '- Add an "Inferred Business Profile" section with: market, operation type (local/global), and region.',
        "- Include explicit checklist lines to run `scrape-playwright` twice: first for homepage-only scan, then for whole-site crawl excluding blog/news pages.",
        "",
        f"Planner context:\n{planner_ctx}" if planner_ctx else "",
        "",
        "User request:",
        message,
        "",
        f"Inferred basics (may be wrong): market={market_guess} operationType={operation_type} region={covered_region}",
        "",
        f"business-scan (summary text):\n{scan_text}" if scan_text else "",
        f"crawl excerpts:\n{crawl_pages_excerpt}" if crawl_pages_excerpt else "",
        f"platform-scout (JSON excerpt):\n{json.dumps(scout_data)[:5000]}" if scout_data else "",
        ("web-search candidate URLs:\n" + "\n".join(f"- {u}" for u in candidate_urls[:30])) if candidate_urls else "",
    ]))

    await _emit_plan_progress(emit_progress, "Creating plan draft", event="plan-markdown-generation")
    _log("plan-markdown-generation-start", conversation_id=conv.get("id"), plan_message_id=plan_message_id)
    try:
        async def _on_plan_token(tok: str) -> None:
            if emit_token is None:
                return
            try:
                await emit_token({"token": tok})
            except Exception:
                pass

        ai_result = await _ai.chat_stream(
            plan_prompt,
            system_prompt="You are a planning assistant. Output only Markdown. No code fences.",
            on_token=_on_plan_token if emit_token is not None else None,
            temperature=0.2,
        )
        plan_markdown = ai_result.message.strip()
        await save_token_usage(
            plan_message_id,
            active_model,
            ai_result.input_tokens,
            ai_result.output_tokens,
            stage="plan-creation.draft",
            provider="anthropic" if CLAUDE_API_KEY else "openai",
            session_id=session_id,
        )
    except Exception:
        plan_markdown = "\n".join([
            "## Execution Plan",
            "",
            f"User request: {message}",
            "",
            "### Checklist",
            "- [ ] Run `business-scan` on target URL/context",
            "- [ ] Run `scrape-playwright` for homepage-only JS-rendered discovery",
            "- [ ] Run `scrape-playwright` for whole-site crawl (max 40 URLs; exclude blog/news unless relevant)",
            "- [ ] Run `platform-scout` to derive discovery queries",
            "- [ ] Run `web-search` with scout queries",
            "- [ ] Run `platform-taxonomy` and `classify-links`",
            "- [ ] Produce final synthesis",
            "",
            "### Assumptions to verify",
            "- Scope (local/global)",
            "- Region/market",
            "- Primary business category",
        ])

    plan_json = {
        "steps": [
            {"stepId": "scan", "skillId": "business-scan", "args": scan_args, "purpose": "Extract landing page business facts"},
            {"stepId": "crawl", "skillId": "scrape-playwright", "args": crawl_args_execute, "purpose": "Collect whole-site on-site evidence while excluding blog/news unless relevant"},
            {"stepId": "scout", "skillId": "platform-scout", "args": scout_args, "dependsOn": ["scan", "crawl"], "purpose": "Generate region-aware review + competitor queries"},
            {"stepId": "search", "skillId": "web-search", "args": web_search_args, "dependsOn": ["scout"], "purpose": "Find review/listing URLs + competitor URLs"},
            {"stepId": "taxonomy", "skillId": "platform-taxonomy", "args": {}, "dependsOn": ["crawl", "search"], "purpose": "Build ecosystem map + domain rules"},
            {"stepId": "classify", "skillId": "classify-links", "args": {}, "dependsOn": ["taxonomy"], "purpose": "Classify discovered URLs"},
        ],
        "evidence": {
            "businessUrl": url,
            "marketGuess": market_guess,
            "operationType": operation_type,
            "coveredRegion": covered_region,
            "scoutQueries": queries,
            "candidateUrls": candidate_urls[:50],
        },
    }

    plan_run = await create_plan_run(conv["id"], user_message_id, plan_message_id, plan_markdown, plan_json)
    _log("plan-draft-created", plan_id=plan_run.get("id"), conversation_id=conv.get("id"))
    await update_message_content(conv["id"], plan_message_id, plan_markdown)
    await update_message_meta(conv["id"], plan_message_id, "plan", plan_run["id"])

    await _emit_plan_progress(emit_progress, "Plan ready for your approval", event="plan-ready", kind="done")
    return {
        "conversationId": conv["id"],
        "planId": plan_run["id"],
        "planMessageId": plan_message_id,
        "planMarkdown": plan_markdown,
        "agentId": resolved["agentId"],
        "skillId": resolved["skillId"],
        "allowedSkillIds": resolved.get("allowedSkillIds", []),
        "contexts": contexts,
    }



def _parse_checklist_items(markdown: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ln in (markdown or "").splitlines():
        line = ln.strip()
        if not line.startswith(("- [", "* [")):
            continue
        done = line.lower().startswith("- [x]") or line.lower().startswith("* [x]")
        text = re.sub(r"^[-*]\s+\[[ xX]\]\s+", "", line).strip()
        if text:
            items.append({"text": text, "done": done})
    return items


def _render_checklist(markdown: str, items: list[dict[str, Any]]) -> str:
    item_idx = 0
    out: list[str] = []
    for ln in (markdown or "").splitlines():
        line = ln
        stripped = line.strip()
        if stripped.startswith(("- [", "* [")) and item_idx < len(items):
            prefix = line[: len(line) - len(line.lstrip())]
            marker = "- [x]" if items[item_idx].get("done") else "- [ ]"
            out.append(f"{prefix}{marker} {items[item_idx].get('text', '')}".rstrip())
            item_idx += 1
        else:
            out.append(line)
    return "\n".join(out)


def _mark_checklist_from_skill(items: list[dict[str, Any]], skill_id: str, summary: str) -> list[str]:
    changed: list[str] = []
    hay = f"{skill_id} {summary}".lower()

    def mark(terms: list[str], extra: list[str] | None = None) -> None:
        for it in items:
            if it.get("done"):
                continue
            t = str(it.get("text") or "").lower()
            matches_item = any(k in t for k in terms)
            matches_summary = any(k in hay for k in (extra or []))
            if matches_item or matches_summary:
                it["done"] = True
                changed.append(str(it.get("text") or ""))

    if skill_id == "platform-scout":
        mark(["market", "scope", "region", "local", "global", "inferred business profile"], ["market", "scope", "region", "local", "global"])
        mark(["competitor quer", "review quer", "search quer"], ["queries", "competitor", "reviews"])
    if skill_id == "web-search":
        mark(["competitor", "alternatives", "review", "listing", "sources", "urls"], ["results", "review", "competitor", "http"])
    if skill_id in ("business-scan", "scrape-agentbrowser", "scrape-playwright", "scrape-bs4"):
        mark(["on-site", "onsite", "landing page", "business context", "site evidence", "crawl"], ["page", "site", "pricing", "about", "service"])
    if skill_id == "platform-taxonomy":
        mark(["taxonomy", "ecosystem", "platform categories", "domain rules"], ["taxonomy", "category", "domain"])
    if skill_id == "classify-links":
        mark(["classify", "classification", "bucket", "categor"], ["classified", "category", "bucket"])

    return changed


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api/files/download")
async def p2_files_download(path: str = Query(...)) -> FileResponse:
    if not _allowed_file_path(path):
        raise HTTPException(status_code=403, detail="Access denied")
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = "audio/mpeg" if p.name.endswith(".mp3") else "video/mp4"
    return FileResponse(str(p), media_type=media, filename=p.name)


async def p2_chat_message(req: Request) -> dict[str, Any]:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    session_id, user_id = _actor_from_payload(body)
    # No agent selected => phase1-style normal chat flow.
    if not str(body.get("agentId") or "").strip():
        out = await unified_chat_service.run_standard_chat(
            message=message,
            persona=str(body.get("persona") or "default"),
            context=body.get("context") if isinstance(body.get("context"), dict) else None,
            conversation_history=body.get("conversationHistory") if isinstance(body.get("conversationHistory"), list) else None,
            conversation_id=str(body.get("conversationId") or "").strip() or None,
            session_id=session_id,
            user_id=user_id,
        )
        return {
            "message": out["message"],
            "conversationId": out["conversationId"],
            "mode": "standard",
            "usage": out.get("usage"),
            "stageOutputs": {},
            "outputFile": None,
        }

    # Agent selected, but prompt is regular conversation => use normal LLM chat.
    if not _is_execution_intent(message):
        out = await unified_chat_service.run_standard_chat(
            message=message,
            persona=str(body.get("persona") or "default"),
            context=body.get("context") if isinstance(body.get("context"), dict) else None,
            conversation_history=body.get("conversationHistory") if isinstance(body.get("conversationHistory"), list) else None,
            conversation_id=str(body.get("conversationId") or "").strip() or None,
            session_id=session_id,
            user_id=user_id,
        )
        return {
            "message": out["message"],
            "conversationId": out["conversationId"],
            "mode": "standard",
            "usage": out.get("usage"),
            "stageOutputs": {},
            "outputFile": None,
        }

    # Agent selected + execution intent => plan-first flow, execution happens only after approval.
    draft = await _create_plan_draft(body=body)
    return {
        "mode": "agentic-plan",
        "conversationId": draft["conversationId"],
        "planId": draft["planId"],
        "planMessageId": draft["planMessageId"],
        "planMarkdown": draft["planMarkdown"],
    }



async def p2_chat_plan_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    if not str(body.get("agentId") or "").strip():
        raise HTTPException(status_code=400, detail="agentId is required for plan mode")

    if not _is_execution_intent(message):
        session_id, user_id = _actor_from_payload(body)

        async def standard_generator():
            try:
                out = await unified_chat_service.run_standard_chat(
                    message=message,
                    persona=str(body.get("persona") or "default"),
                    context=body.get("context") if isinstance(body.get("context"), dict) else None,
                    conversation_history=body.get("conversationHistory") if isinstance(body.get("conversationHistory"), list) else None,
                    conversation_id=str(body.get("conversationId") or "").strip() or None,
                    session_id=session_id,
                    user_id=user_id,
                )
                yield _sse({"token": out["message"]})
                yield _sse(
                    {
                        "done": True,
                        "mode": "standard",
                        "conversationId": out["conversationId"],
                        "usage": out.get("usage"),
                        "stageOutputs": {},
                        "outputFile": None,
                    }
                )
            except Exception as exc:
                yield _sse({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})

        return StreamingResponse(standard_generator(), media_type="text/event-stream")

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                _log("plan-stream-worker-start")
                await emit({"stage": "thinking", "label": "Building plan", "stageIndex": 0})
                result = await _create_plan_draft(body=body, emit_progress=emit_progress, emit_token=emit)
                _log("plan-stream-worker-done", plan_id=result.get("planId"), conversation_id=result.get("conversationId"))
                await emit({
                    "done": True,
                    "conversationId": result.get("conversationId"),
                    "planId": result.get("planId"),
                    "planMessageId": result.get("planMessageId"),
                    "planMarkdown": result.get("planMarkdown"),
                    "agentId": result.get("agentId"),
                    "skillId": result.get("skillId"),
                })
            except Exception as exc:
                _log("plan-stream-worker-error", error=str(exc), traceback=traceback.format_exc())
                await emit({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")



async def _prepare_plan_approval(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str | None]:
    """Load conversation, apply markdown patch, claim plan (draft/approved → executing)."""
    plan_id = str(body.get("planId") or "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")
    if not str(body.get("agentId") or "").strip():
        raise HTTPException(status_code=400, detail="agentId is required for plan execution")

    session_id, user_id = _actor_from_payload(body)
    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        session_id=session_id,
        user_id=user_id,
    )

    plan = await get_plan_run(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    if plan.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="plan was cancelled (create a new plan)")
    if plan.get("status") in ("executing", "done"):
        raise HTTPException(status_code=409, detail=f"plan is already {plan.get('status')}")

    if isinstance(body.get("planMarkdown"), str) and body.get("planMarkdown").strip():
        await update_plan_run(plan_id, {"planMarkdown": body.get("planMarkdown")})

    if not await claim_plan_run_for_execution(plan_id):
        raise HTTPException(status_code=409, detail="plan already started or cannot be executed")

    plan = await get_plan_run(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    return conv, plan, resolved, plan_id, session_id


async def schedule_plan_approval_background(body: dict[str, Any]) -> dict[str, Any]:
    """Start plan execution in a detached asyncio task (survives client disconnect)."""
    conv, plan, resolved, plan_id, session_id = await _prepare_plan_approval(body)
    assistant_message_id = await append_assistant_placeholder(conv["id"])
    await update_plan_run(plan_id, {"executionMessageId": assistant_message_id})

    async def _noop(_: dict[str, Any]) -> None:
        return None

    async def _bg() -> None:
        try:
            await execute_plan_approval_work(
                plan_id=plan_id,
                conv=conv,
                plan=plan,
                resolved=resolved,
                assistant_message_id=assistant_message_id,
                session_id=session_id,
                emit=_noop,
                emit_progress=_noop,
            )
        except Exception as exc:  # pragma: no cover
            _log("plan-bg-unhandled", error=str(exc), traceback=traceback.format_exc())
            await update_plan_run(plan_id, {"status": "error"})

    t = asyncio.create_task(_bg())
    _register_plan_bg_task(plan_id, t)
    return {
        "conversationId": conv["id"],
        "planId": plan_id,
        "assistantMessageId": assistant_message_id,
        "agentId": resolved["agentId"],
        "runningTaskRefFound": True,
    }


async def ensure_plan_approval_background(body: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure background execution exists for planId.
    - draft/approved: starts execution (normal path)
    - executing + live task ref: returns already-running info
    - executing + missing task ref: recreates detached task using persisted context
    """
    plan_id = str(body.get("planId") or "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")
    if not str(body.get("agentId") or "").strip():
        raise HTTPException(status_code=400, detail="agentId is required for plan execution")

    plan = await get_plan_run(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")

    status = str(plan.get("status") or "")
    if status in ("draft", "approved"):
        return await schedule_plan_approval_background(body)

    # Allow retry from failed runs: move error -> approved, then start again.
    if status == "error":
        await update_plan_run(plan_id, {"status": "approved"})
        return await schedule_plan_approval_background(body)

    if status != "executing":
        raise HTTPException(status_code=409, detail=f"plan is {status}")

    session_id, user_id = _actor_from_payload(body)
    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        session_id=session_id,
        user_id=user_id,
    )

    assistant_message_id = str(plan.get("executionMessageId") or "").strip()
    if not assistant_message_id:
        assistant_message_id = await append_assistant_placeholder(conv["id"])
        await update_plan_run(plan_id, {"executionMessageId": assistant_message_id})

    if is_plan_background_task_running(plan_id):
        return {
            "conversationId": conv["id"],
            "planId": plan_id,
            "assistantMessageId": assistant_message_id,
            "agentId": resolved["agentId"],
            "runningTaskRefFound": True,
            "alreadyRunning": True,
        }

    async def _noop(_: dict[str, Any]) -> None:
        return None

    async def _bg() -> None:
        try:
            await execute_plan_approval_work(
                plan_id=plan_id,
                conv=conv,
                plan=plan,
                resolved=resolved,
                assistant_message_id=assistant_message_id,
                session_id=session_id,
                emit=_noop,
                emit_progress=_noop,
            )
        except Exception as exc:  # pragma: no cover
            _log("plan-bg-resume-unhandled", error=str(exc), traceback=traceback.format_exc())
            await update_plan_run(plan_id, {"status": "error"})

    t = asyncio.create_task(_bg())
    _register_plan_bg_task(plan_id, t)
    return {
        "conversationId": conv["id"],
        "planId": plan_id,
        "assistantMessageId": assistant_message_id,
        "agentId": resolved["agentId"],
        "runningTaskRefFound": True,
        "resumedFromMissingTaskRef": True,
    }



async def execute_plan_approval_work(
    *,
    plan_id: str,
    conv: dict[str, Any],
    plan: dict[str, Any],
    resolved: dict[str, Any],
    assistant_message_id: str,
    session_id: str | None,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    emit_progress: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    try:
        exec_start_ms = _time.time() * 1000
        tokens_emitted = 0
        await emit({"stage": "thinking", "label": "Executing plan", "stageIndex": 0, "agentId": resolved["agentId"]})
    
        steps = plan.get("planJson", {}).get("steps", []) if isinstance(plan.get("planJson"), dict) else []
        plan_markdown_live = str(plan.get("planMarkdown") or "")
        checklist_items = _parse_checklist_items(plan_markdown_live)
        user_message = ""
        for msg in reversed(conv.get("messages") or []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                candidate = str(msg.get("content") or "").strip()
                if candidate:
                    user_message = candidate
                    break
        stage_outputs: dict[str, str] = {}
        step_results: dict[str, Any] = {}
    
        previous_execution_message_id = str(plan.get("executionMessageId") or "").strip()
        reusable_by_skill: dict[str, dict[str, Any]] = {}
        if previous_execution_message_id and previous_execution_message_id != assistant_message_id:
            try:
                previous_calls = await get_skill_calls_by_message_id_full(previous_execution_message_id)
                for call in previous_calls:
                    if str(call.get("state") or "") != "done":
                        continue
                    sid_prev = str(call.get("skillId") or "").strip()
                    if not sid_prev:
                        continue
                    output_rows = call.get("output") if isinstance(call.get("output"), list) else []
                    last_result = None
                    for row in reversed(output_rows):
                        if isinstance(row, dict) and str(row.get("type") or "") == "result":
                            last_result = row
                            break
                    if not isinstance(last_result, dict):
                        continue
                    reusable_by_skill[sid_prev] = {
                        "text": str(last_result.get("text") or ""),
                        "data": last_result.get("data"),
                    }
            except Exception:
                reusable_by_skill = {}

        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            sid = str(step.get("skillId") or "").strip()
            step_id = str(step.get("stepId") or f"step-{idx + 1}")
            if not sid:
                continue
            skill_name = _skill_display_name(sid)
            if resolved.get("allowedSkillIds") and sid not in (resolved.get("allowedSkillIds") or []):
                continue
    
            step_args: dict[str, Any] = dict(step.get("args") or {})

            # Retry optimization: reuse successful outputs from previous interrupted/failed attempt.
            reused = reusable_by_skill.get(sid)
            if reused is not None:
                step_results[step_id] = {"text": reused.get("text"), "data": reused.get("data")}
                if isinstance(reused.get("text"), str) and reused.get("text"):
                    stage_outputs[sid] = str(reused.get("text"))
                if checklist_items:
                    changed_items = _mark_checklist_from_skill(checklist_items, sid, str(reused.get("text") or ""))
                    if changed_items:
                        plan_markdown_live = _render_checklist(plan_markdown_live, checklist_items)
                        await update_plan_run(plan_id, {"planMarkdown": plan_markdown_live})
                        if plan.get("planMessageId"):
                            await update_message_content(
                                conv["id"],
                                str(plan.get("planMessageId")),
                                plan_markdown_live,
                            )
                        await emit_progress(
                            {
                                "stage": "thinking",
                                "type": "task",
                                "message": f"Checklist updated from reused {sid}",
                                "meta": {
                                    "kind": "checklist-update",
                                    "planId": plan_id,
                                    "planMarkdown": plan_markdown_live,
                                    "checkedItems": changed_items,
                                },
                            }
                        )
                await emit_progress(
                    {
                        "stage": "thinking",
                        "type": "task",
                        "message": f"Reusing previous successful output for {skill_name}",
                        "meta": {
                            "kind": "skill-call",
                            "id": f"reused-{sid}-{idx}",
                            "skillId": sid,
                            "skillName": skill_name,
                            "status": "done",
                            "input": {"args": step_args, "reused": True},
                            "outputSummary": str(reused.get("text") or "")[:600],
                        },
                    }
                )
                continue
            if sid == "web-search":
                scout = (step_results.get("scout") or {}).get("data") or {}
                result_block = scout.get("result") or scout
                structured_qs = [
                    str(q.get("query", "")).strip()
                    for q in (result_block.get("searchQueries") or [])
                    if isinstance(q, dict) and q.get("query")
                ]
                legacy_qs = [
                    str(q).strip()
                    for q in (result_block.get("queries") or [])
                    if str(q).strip()
                ]
                chosen_qs = structured_qs if structured_qs else legacy_qs
                if chosen_qs and (not step_args.get("queries") or "(from platform-scout" in str(step_args.get("queries"))):
                    step_args["queries"] = "\n".join(chosen_qs)
                scope = str(result_block.get("scope") or "").strip().lower()
                step_args.setdefault("market", str(result_block.get("marketGuess") or ""))
                step_args.setdefault("businessType", str(result_block.get("businessTypeGuess") or ""))
                step_args.setdefault("operationType", scope if scope in ("local", "global") else "")
                step_args.setdefault("coveredRegion", str(result_block.get("coveredRegion") or ""))
    
            await emit({"stage": "running", "label": f"Running {skill_name}", "stageIndex": idx + 1, "agentId": resolved["agentId"]})
    
            run_id = f"run-{sid}-{idx}-{uuid4().hex[:8]}"
            call_id = await create_skill_call(conv["id"], assistant_message_id, sid, run_id, {"args": step_args})
            page_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            page_worker_task: asyncio.Task | None = None
            if _should_stream_page_nl(sid):
                async def _page_worker() -> None:
                    while True:
                        meta = await page_queue.get()
                        if meta is None:
                            break
                        try:
                            prompt = _build_page_nl_prompt(sid, meta)
                            r = await _ai.chat(
                                prompt,
                                system_prompt="You convert web extraction objects into compact factual notes.",
                                temperature=0.2,
                                provider="openai",
                            )
                            page_url = str(meta.get("url") or "").strip()
                            note = (r.message or "").strip()
                            if note:
                                chunk = f"page: {page_url}\ncontent: {note}\n\n"
                                await append_skill_streamed_text(call_id, chunk)
                            await save_token_usage(
                                assistant_message_id,
                                OPENAI_MODEL,
                                r.input_tokens,
                                r.output_tokens,
                                stage=f"page-nl.{sid}",
                                provider="openai",
                                session_id=session_id,
                            )
                        except Exception:
                            pass
                page_worker_task = asyncio.create_task(_page_worker())
            await emit_progress(
                {
                    "stage": "thinking",
                    "type": "task",
                    "message": f"Running {skill_name}",
                    "meta": {
                        "kind": "skill-call",
                        "id": run_id,
                        "skillId": sid,
                        "skillName": skill_name,
                        "status": "running",
                        "input": {"args": step_args},
                    },
                }
            )
    
            async def on_progress(event: dict[str, Any]) -> None:
                meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
                if (
                    _should_stream_page_nl(sid)
                    and str(meta.get("event") or "").strip().lower() == "page_data"
                    and isinstance(meta, dict)
                ):
                    await page_queue.put(meta)
                if str(meta.get("kind") or "") == "token-usage":
                    await save_token_usage(
                        assistant_message_id,
                        str(meta.get("model") or (CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL)),
                        int(meta.get("inputTokens") or 0),
                        int(meta.get("outputTokens") or 0),
                        stage=str(meta.get("stage") or f"plan-execution.{sid}"),
                        provider=str(meta.get("provider") or ("anthropic" if CLAUDE_API_KEY else "openai")),
                        session_id=session_id,
                    )
                evt_l = str(meta.get("event") or "").strip().lower()
                if evt_l == "checkpoint" and isinstance(meta.get("payload"), dict):
                    try:
                        await push_skill_output(
                            call_id,
                            {"type": "checkpoint", "payload": meta["payload"]},
                        )
                    except Exception:
                        pass
                elif evt_l in ("started", "discovered", "page", "page_data"):
                    try:
                        await push_skill_output(
                            call_id,
                            {
                                "type": "progress",
                                "event": evt_l,
                                "payload": meta,
                            },
                        )
                    except Exception:
                        pass
                evt = str(meta.get("event") or "")
                page_url = str(meta.get("url") or "").strip()
                if evt in ("started", "discovered", "page", "page_data") and page_url:
                    await emit_progress(
                        {
                            "stage": "running",
                            "type": "task",
                            "message": f"Reading page: {page_url}",
                            "meta": {
                                "kind": "page-read",
                                "event": evt,
                                "url": page_url,
                            },
                        }
                    )
                await emit_progress(event)
    
            if sid == "scrape-playwright":
                _SCRAPE_AUTO_RESUME_ATTEMPTS = 2
                result = None
                for attempt in range(_SCRAPE_AUTO_RESUME_ATTEMPTS):
                    attempt_args = dict(step_args)
                    if attempt > 0 and result is not None and result.status == "error":
                        out_rows = await fetch_skill_call_output(call_id)
                        ck = _latest_parallel_checkpoint_from_output(out_rows)
                        if not ck or not _scrape_failure_recoverable(result.error):
                            break
                        skip = _skip_urls_from_scrape_output(out_rows)
                        attempt_args["resumeCheckpoint"] = ck
                        if skip:
                            attempt_args["skipUrls"] = skip
                        _log(
                            "scrape-playwright-auto-resume",
                            attempt=attempt + 1,
                            plan_id=plan_id,
                            skill_call_id=call_id,
                            skip_count=len(skip),
                            err=str(result.error or "")[:200],
                        )
                    result = await run_skill(
                        sid,
                        plan.get("planMarkdown") or "",
                        history=conv.get("messages") or [],
                        args=attempt_args,
                        on_progress=on_progress,
                    )
                    if result.status != "error":
                        break
            else:
                result = await run_skill(
                    sid,
                    plan.get("planMarkdown") or "",
                    history=conv.get("messages") or [],
                    args=step_args,
                    on_progress=on_progress,
                )
            if page_worker_task is not None:
                await page_queue.put(None)
                await page_worker_task
            step_results[step_id] = {"text": result.text, "data": result.data}
    
            await set_skill_call_result(call_id, "error" if result.status == "error" else "done", result.text, result.data, result.error)
            await emit_progress(
                {
                    "stage": "error" if result.status == "error" else "thinking",
                    "type": "task",
                    "message": f"{skill_name} {'failed' if result.status == 'error' else 'completed'}",
                    "meta": {
                        "kind": "skill-call",
                        "id": run_id,
                        "skillId": sid,
                        "skillName": skill_name,
                        "status": "error" if result.status == "error" else "done",
                        "input": {"args": step_args},
                        "outputSummary": (result.text or "")[:600],
                    },
                }
            )
            if checklist_items and result.status != "error":
                changed_items = _mark_checklist_from_skill(checklist_items, sid, result.text or "")
                if changed_items:
                    plan_markdown_live = _render_checklist(plan_markdown_live, checklist_items)
                    await update_plan_run(plan_id, {"planMarkdown": plan_markdown_live})
                    if plan.get("planMessageId"):
                        await update_message_content(
                            conv["id"],
                            str(plan.get("planMessageId")),
                            plan_markdown_live,
                        )
                    await emit_progress(
                        {
                            "stage": "thinking",
                            "type": "task",
                            "message": f"Checklist updated from {sid}",
                            "meta": {
                                "kind": "checklist-update",
                                "planId": plan_id,
                                "planMarkdown": plan_markdown_live,
                                "checkedItems": changed_items,
                            },
                        }
                    )
    
            if result.text:
                stage_outputs[sid] = result.text
    
        formatter_calls = await get_skill_calls_by_message_id(assistant_message_id)
        async def _on_final_token(token: str) -> None:
            nonlocal tokens_emitted
            tokens_emitted += len(token)
            await emit_progress(
                {
                    "stage": "thinking",
                    "type": "task",
                    "message": "Generating final report",
                    "meta": {
                        "kind": "token-usage",
                        "outputChars": tokens_emitted,
                        "outputTokensEstimated": max(1, tokens_emitted // 4),
                    },
                }
            )
            await emit({"token": token})
        fmt = await format_final_answer(
            message=user_message or (plan.get("planMarkdown") or ""),
            start_ms=exec_start_ms,
            skill_calls=formatter_calls,
            last_skill_result=None,
            contexts=resolved.get("contexts") or {},
            on_token=_on_final_token,
        )
        await save_token_usage(
            assistant_message_id,
            fmt.model,
            fmt.input_tokens,
            fmt.output_tokens,
            stage="plan-execution.final-formatting",
            provider=fmt.provider,
            session_id=session_id,
        )
        final_text = (fmt.text or "").strip()
        if final_text and tokens_emitted == 0:
            await emit({"token": final_text})
    
        skills_count = len(await get_skill_calls_by_message_id(assistant_message_id))
        await update_message_content(conv["id"], assistant_message_id, final_text, None, skills_count)
        await save_stage_outputs(conv["id"], stage_outputs, None)
    
        await update_plan_run(plan_id, {"status": "done"})
        token_usage = await get_token_usage(assistant_message_id)
        await emit(
            {
                "done": True,
                "conversationId": conv["id"],
                "messageId": assistant_message_id,
                "runId": fmt.run_id,
                "model": CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
                "durationMs": fmt.duration_ms,
                "stageOutputs": stage_outputs,
                "outputFile": None,
                "agentId": resolved["agentId"],
                "tokenUsage": token_usage,
            }
        )
    except Exception as exc:
        await update_plan_run(plan_id, {"status": "error"})
        await emit({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})

async def _approve_plan_stream_body(body: dict[str, Any]) -> StreamingResponse:
    conv, plan, resolved, plan_id, session_id = await _prepare_plan_approval(body)
    assistant_message_id = await append_assistant_placeholder(conv["id"])

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                await execute_plan_approval_work(
                    plan_id=plan_id,
                    conv=conv,
                    plan=plan,
                    resolved=resolved,
                    assistant_message_id=assistant_message_id,
                    session_id=session_id,
                    emit=emit,
                    emit_progress=emit_progress,
                )
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")
