from __future__ import annotations

import asyncio
import json
import re
import time as _time
import traceback
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .ai import AiHelper
from .agent.final_formatter import format_final_answer
from .agent.orchestrator import RunOpts, run_agent_turn_stream
from .auth_google import (
    decode_phase2_jwt,
    get_internal_google_admin_emails,
    get_internal_google_super_admin_emails,
    Phase2AuthedUser,
    issue_phase2_jwt,
    is_allowed_internal_email,
    verify_google_or_firebase_token,
)
from .config import CLAUDE_API_KEY, CLAUDE_MODEL, OPENAI_MODEL, STORAGE_BUCKET
from .db import get_pool
from .skills import first_skill_id, get_skill, list_skills, run_skill
from .stores import (
    append_skill_streamed_text,
    append_assistant_placeholder,
    append_message,
    create_agent,
    create_plan_run,
    create_skill_call,
    delete_agent,
    delete_conversation,
    ensure_default_agents,
    get_agent,
    get_conversation,
    get_or_create_conversation,
    get_plan_run,
    get_skill_calls_by_message_id,
    get_skill_calls_by_message_id_full,
    get_stage_outputs,
    get_token_usage,
    list_insight_feedback,
    list_agents,
    save_token_usage,
    list_conversations,
    push_skill_output,
    save_stage_outputs,
    set_skill_call_result,
    update_agent,
    update_message_content,
    update_message_meta,
    update_plan_run,
    set_insight_feedback,
)

router = APIRouter()

def _log(label: str, **fields: Any) -> None:
    try:
        print(f"[phase2.router] {label} | {json.dumps(fields, default=str, ensure_ascii=False)}")
    except Exception:
        print(f"[phase2.router] {label} | <log-serialize-error>")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_url_from_message(msg: str) -> str:
    m = re.search(r"https?://\S+", msg or "")
    if not m:
        return ""
    return m.group(0).rstrip("),.;]\"'")


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


def _auth_bearer_token_from_request(req: Request) -> str | None:
    raw = req.headers.get("Authorization") or ""
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def _require_phase2_user(req: Request) -> Any:
    token = _auth_bearer_token_from_request(req)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")
    try:
        decoded = decode_phase2_jwt(token)
        email = decoded.email.lower()
        is_super_admin = email in get_internal_google_super_admin_emails()
        is_internal_admin = email in get_internal_google_admin_emails()
        is_admin = is_super_admin or is_internal_admin

        # IMPORTANT: Only Google login creates the Phase2 user row.
        # If a token refers to a non-existent user, treat it as invalid so the frontend can logout.
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, email FROM users WHERE id = $1::uuid", decoded.user_id)
            if not row:
                raise HTTPException(status_code=401, detail="User not found for token; please login again")
            db_email = str(row["email"] or "").strip().lower()
            if db_email and db_email != email:
                raise HTTPException(status_code=401, detail="Token/user mismatch; please login again")

        return Phase2AuthedUser(
            user_id=decoded.user_id,
            email=decoded.email,
            is_admin=is_admin,
            is_super_admin=is_super_admin,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid auth token: {str(exc)}") from exc


@router.post("/api/phase2/auth/google/exchange")
async def p2_google_exchange(req: Request) -> dict[str, Any]:
    """
    Exchanges a Firebase Google ID token (from the internal-only login page)
    for an Ikshan Phase2 JWT to be used in subsequent API calls.
    """
    body = await req.json()
    id_token = str(body.get("idToken") or "").strip()
    if not id_token:
        raise HTTPException(status_code=400, detail="idToken is required")

    decoded = await verify_google_or_firebase_token(id_token)
    email = str(decoded.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=403, detail="Email claim missing from token")

    if not is_allowed_internal_email(email):
        raise HTTPException(status_code=403, detail="Email not allowed for Phase2")

    is_super_admin = email in get_internal_google_super_admin_emails()
    is_internal_admin = email in get_internal_google_admin_emails()
    is_admin = is_super_admin or is_internal_admin

    full_name = str(decoded.get("name") or decoded.get("full_name") or "").strip()
    avatar_url = str(decoded.get("picture") or decoded.get("avatar_url") or "").strip()
    auth_provider = "google"

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if row:
            user_id = str(row["id"])
        else:
            inserted = await conn.fetchrow(
                """
                INSERT INTO users (email, full_name, avatar_url, auth_provider, email_verified_at)
                VALUES ($1, $2, $3, $4, NOW())
                RETURNING id
                """,
                email,
                full_name,
                avatar_url,
                auth_provider,
            )
            assert inserted is not None
            user_id = str(inserted["id"])

    token = issue_phase2_jwt(
        user_id=user_id,
        email=email,
        is_admin=is_admin,
        is_super_admin=is_super_admin,
    )
    return {"token": token, "userId": user_id, "email": email, "isAdmin": is_admin, "isSuperAdmin": is_super_admin}


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


async def _resolve_agent_and_skill(payload: dict[str, Any], *, current_user: Any) -> dict[str, Any]:
    default_skill = first_skill_id() or "platform-scout"
    default_contexts = _load_default_phase2_contexts()

    agent_id = str(payload.get("agentId") or "").strip()
    allowed_from_request = payload.get("allowedSkillIds") if isinstance(payload.get("allowedSkillIds"), list) else []
    allowed_from_request = [str(s) for s in allowed_from_request if isinstance(s, str)]

    if agent_id:
        agent = await get_agent(
            agent_id,
            user_id=current_user.user_id,
            is_admin=current_user.is_admin,
            for_execution=True,
        )
        if agent:
            allowed = [s for s in agent.get("allowedSkillIds", []) if isinstance(s, str)]
            chosen = next((sid for sid in allowed if get_skill(sid)), default_skill)
            return {
                "agentId": agent_id,
                "skillId": chosen,
                "allowedSkillIds": allowed,
                "isLocked": bool(agent.get("isLocked")),
                "contexts": {
                    "skillSelectorContext": (agent.get("skillSelectorContext") or default_contexts.get("skillSelectorContext") or ""),
                    "finalOutputFormattingContext": (agent.get("finalOutputFormattingContext") or default_contexts.get("finalOutputFormattingContext") or ""),
                },
            }
        raise HTTPException(status_code=403, detail="Agent not accessible")

    first_allowed = next((sid for sid in allowed_from_request if get_skill(sid)), None)
    chosen = first_allowed or default_skill
    return {
        "agentId": chosen,
        "skillId": chosen,
        "allowedSkillIds": allowed_from_request,
        "isLocked": False,
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
    current_user: Any,
    emit_progress=None,
) -> dict[str, Any]:
    message = str(body.get("message") or "").strip()
    _log("plan-draft-start", message_preview=message[:200], has_emit_progress=emit_progress is not None)
    resolved = await _resolve_agent_and_skill(body, current_user=current_user)
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    contexts = resolved.get("contexts", {})
    _log("plan-draft-conversation-resolved", conversation_id=conv.get("id"), agent_id=resolved.get("agentId"))

    cancel_plan_id = str(body.get("cancelPlanId") or "").strip()
    if cancel_plan_id:
        existing = await get_plan_run(cancel_plan_id, user_id=current_user.user_id, is_admin=current_user.is_admin)
        if existing and existing.get("conversationId") == conv["id"] and existing.get("status") == "draft":
            await update_plan_run(
                cancel_plan_id,
                {"status": "cancelled"},
                user_id=current_user.user_id,
                is_admin=current_user.is_admin,
            )

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
    plan_message_id = await append_message(conv["id"], "assistant", placeholder, kind="plan")

    await _emit_plan_progress(emit_progress, "Analyzing request context", event="plan-started")
    url = _extract_url_from_message(message)

    async def _run_skill_for_plan(sid: str, args: dict[str, Any], input_msg: str) -> Any:
        if not get_skill(sid):
            _log("plan-skill-missing", skill_id=sid)
            return None
        run_id = f"plan-{plan_message_id}-{sid}-{int(_time.time() * 1000)}"
        _log("plan-skill-start", skill_id=sid, run_id=run_id, args=args)
        skill_call_id = await create_skill_call(conv["id"], plan_message_id, sid, run_id, {"args": args})
        page_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        page_worker_task: asyncio.Task | None = None

        if _should_stream_page_nl(sid):
            async def _page_worker() -> None:
                # Prefer Claude when configured; avoid hard-failing on OpenAI quota.
                ai = AiHelper(temperature=0.2)
                while True:
                    meta = await page_queue.get()
                    if meta is None:
                        break
                    try:
                        prompt = _build_page_nl_prompt(sid, meta)
                        r = await ai.chat(
                            message=prompt,
                            system_prompt="You convert web extraction objects into compact factual notes.",
                        )
                        page_url = str(meta.get("url") or "").strip()
                        note = (r.message or "").strip()
                        if note:
                            chunk = f"page: {page_url}\ncontent: {note}\n\n"
                            await append_skill_streamed_text(skill_call_id, chunk)
                        await save_token_usage(
                            plan_message_id,
                            (CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL),
                            r.input_tokens,
                            r.output_tokens,
                            stage=f"page-nl.{sid}",
                            provider=("anthropic" if CLAUDE_API_KEY else "openai"),
                        )
                    except Exception:
                        pass
            page_worker_task = asyncio.create_task(_page_worker())

        async def _on_prog(event: dict[str, Any]) -> None:
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            if str(meta.get("event") or "").strip():
                _log("plan-skill-progress", skill_id=sid, run_id=run_id, event=meta.get("event"), meta_keys=list(meta.keys()))
            if (
                _should_stream_page_nl(sid)
                and str(meta.get("event") or "").strip().lower() == "page_data"
                and isinstance(meta, dict)
            ):
                await page_queue.put(meta)
            stream_kind = str(meta.get("streamKind") or "info").strip().lower()
            if stream_kind == "data":
                await push_skill_output(skill_call_id, {
                    "type": "progress",
                    "event": str(meta.get("event")) if meta.get("event") else None,
                    "payload": meta,
                })

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
        "- Infer and state **B2B vs B2C** (or Hybrid + primary) from on-site + scout evidence; align checklist tasks with that lens (B2C → preferences, sentiment, shopper conversion; B2B → demand, ROI, decision factors, competitive positioning, sales conversion).",
        '- Include a section titled "Phase 6 — Targeted Collection (Reviews + Competitors)" scoped to the B2B or B2C buyer.',
        '- Include a short "Assumptions to verify" section so user can confirm the inferred basics (scope/region/category).',
        '- Add an "Inferred Business Profile" section with: market, operation type (local/global), region, and **primary buyer model (B2B / B2C / Hybrid)**.',
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
        ai = AiHelper(temperature=0.2)
        ai_result = await ai.chat(
            message=plan_prompt,
            system_prompt="You are a planning assistant. Output only Markdown. No code fences.",
        )
        plan_markdown = ai_result.message.strip()
        await save_token_usage(
            plan_message_id,
            active_model,
            ai_result.input_tokens,
            ai_result.output_tokens,
            stage="plan-creation.draft",
            provider="anthropic" if CLAUDE_API_KEY else "openai",
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
    is_locked = bool(resolved.get("isLocked"))
    reveal_secrets = bool(current_user.is_admin) or not is_locked
    allowed_skill_ids_out = resolved.get("allowedSkillIds", []) if reveal_secrets else []
    contexts_out = contexts if reveal_secrets else {}
    return {
        "conversationId": conv["id"],
        "planId": plan_run["id"],
        "planMessageId": plan_message_id,
        "planMarkdown": plan_markdown,
        "agentId": resolved["agentId"],
        "skillId": (resolved["skillId"] if reveal_secrets else ""),
        "allowedSkillIds": allowed_skill_ids_out,
        "contexts": contexts_out,
    }


def _build_retry_message(
    original_message: str,
    retry_from_stage: str,
    stage_outputs: dict[str, str],
    skill_stages: list[str] | None = None,
) -> str:
    stages = skill_stages or []
    stage_idx = stages.index(retry_from_stage) if retry_from_stage in stages else -1
    if stage_idx <= 0:
        return original_message
    prior_outputs = [
        f"[{stages[i]} output]\n{stage_outputs[stages[i]]}"
        for i in range(stage_idx)
        if stages[i] in stage_outputs and stage_outputs[stages[i]]
    ]
    if not prior_outputs:
        return original_message
    return "\n".join([
        f'RETRY from stage "{retry_from_stage}". Previous stages already completed successfully:',
        "",
        "\n\n".join(prior_outputs),
        "",
        f"Original request: {original_message}",
        "",
        f"Resume from step: {retry_from_stage}. Skip all prior steps.",
    ])


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

@router.get("/api/health")
async def p2_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ikshan-phase2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": {"provider": "openai", "model": OPENAI_MODEL},
    }


@router.get("/api/skills")
async def p2_skills_root(current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    return {"skills": list_skills()}


@router.get("/api/chat/skills")
async def p2_skills_chat(current_user: Any = Depends(_require_phase2_user)) -> list[dict[str, Any]]:
    return list_skills()


@router.get("/api/agents")
async def p2_agents_list(current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    return {"agents": await list_agents(user_id=current_user.user_id, is_admin=current_user.is_admin)}


@router.post("/api/agents")
async def p2_agents_create(req: Request, current_user: Any = Depends(_require_phase2_user)) -> JSONResponse:
    body = await req.json()
    if not (current_user.is_admin or current_user.is_super_admin):
        raise HTTPException(status_code=403, detail="Only admins can create agents")
    agent_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="id is required")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        agent = await create_agent(
            {
                "id": agent_id,
                "name": name,
                "emoji": body.get("emoji") or "🤖",
                "description": body.get("description") or "",
                "allowedSkillIds": body.get("allowedSkillIds") if isinstance(body.get("allowedSkillIds"), list) else [],
                "skillSelectorContext": body.get("skillSelectorContext") or "",
                "finalOutputFormattingContext": body.get("finalOutputFormattingContext") or "",
                "visibility": body.get("visibility") or "private",
                "isLocked": body.get("isLocked") or False,
            }
            ,
            created_by_user_id=current_user.user_id,
            is_admin=current_user.is_admin,
            is_super_admin=current_user.is_super_admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content={"agent": agent})


@router.get("/api/agents/{agent_id}")
async def p2_agents_get(agent_id: str, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    agent = await get_agent(agent_id, user_id=current_user.user_id, is_admin=current_user.is_admin, for_execution=False)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent": agent}


@router.patch("/api/agents/{agent_id}")
async def p2_agents_patch(agent_id: str, req: Request, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    body = await req.json()
    patch: dict[str, Any] = {}
    for key in ["name", "emoji", "description", "allowedSkillIds", "skillSelectorContext", "finalOutputFormattingContext", "visibility"]:
        if key in body:
            patch[key] = body[key]
    updated = await update_agent(
        agent_id,
        patch,
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent": updated}


@router.delete("/api/agents/{agent_id}")
async def p2_agents_delete(agent_id: str, current_user: Any = Depends(_require_phase2_user)) -> JSONResponse:
    ok = await delete_agent(
        agent_id,
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return JSONResponse(status_code=204, content=None)


@router.get("/api/files/download")
async def p2_files_download(path: str = Query(...), current_user: Any = Depends(_require_phase2_user)) -> FileResponse:
    if not _allowed_file_path(path):
        raise HTTPException(status_code=403, detail="Access denied")
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = "audio/mpeg" if p.name.endswith(".mp3") else "video/mp4"
    return FileResponse(str(p), media_type=media, filename=p.name)


@router.post("/api/chat/message")
async def p2_chat_message(req: Request, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    resolved = await _resolve_agent_and_skill(body, current_user=current_user)
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await append_message(conv["id"], "user", message)

    result = await run_agent_turn_stream(
        message,
        conv.get("messages") or [],
        resolved["skillId"],
        opts=RunOpts(
            allowed_skill_ids=resolved.get("allowedSkillIds") or None,
            contexts=resolved.get("contexts") or {},
        ),
    )

    text = result.text or ""

    if result.status == "error" and not text:
        try:
            ai = AiHelper(temperature=0.3)
            ai_res = await ai.chat(
                message=message,
                system_prompt="You are a helpful assistant. The skill automation failed. Answer to the best of your ability.",
                conversation_history=conv.get("messages") or [],
            )
            text = ai_res.message.strip() or "I could not run the automation for this request. Please try again or adjust the prompt."
        except Exception:
            text = "I could not run the automation for this request. Please try again or adjust the prompt."

    await append_message(conv["id"], "assistant", text, outputFile=None)
    await save_stage_outputs(conv["id"], {}, None)
    return {
        "message": text,
        "conversationId": conv["id"],
        "runId": result.run_id,
        "model": CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
        "durationMs": result.duration_ms,
        "stageOutputs": {},
        "outputFile": None,
    }


@router.post("/api/chat/stream")
async def p2_chat_stream(req: Request, current_user: Any = Depends(_require_phase2_user)) -> StreamingResponse:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    retry_from_stage = str(body.get("retryFromStage") or "").strip()
    retry_stage_outputs: dict[str, str] = body.get("stageOutputs") or {}
    if retry_from_stage and isinstance(retry_stage_outputs, dict):
        message = _build_retry_message(message, retry_from_stage, retry_stage_outputs)

    resolved = await _resolve_agent_and_skill(body, current_user=current_user)
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    reveal_secrets = bool(current_user.is_admin) or not bool(resolved.get("isLocked"))

    await append_message(conv["id"], "user", message)
    assistant_message_id = await append_assistant_placeholder(conv["id"])

    merged_stage_outputs = await get_stage_outputs(conv["id"])

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            if str(meta.get("kind") or "") == "token-usage":
                await save_token_usage(
                    assistant_message_id,
                    str(meta.get("model") or (CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL)),
                    int(meta.get("inputTokens") or 0),
                    int(meta.get("outputTokens") or 0),
                    stage=str(meta.get("stage") or "chat-execution"),
                    provider=str(meta.get("provider") or ("anthropic" if CLAUDE_API_KEY else "openai")),
                )
            if not reveal_secrets and isinstance(event.get("meta"), dict):
                meta2 = dict(event.get("meta") or {})
                for k in ("skillId", "skill_id", "skill"):
                    meta2.pop(k, None)
                event = dict(event)
                event["meta"] = meta2
            await emit({"progress": event})

        async def worker() -> None:
            try:
                tokens_emitted = 0

                async def on_stage(stage: str, label: str, idx: int) -> None:
                    await emit(
                        {
                            "stage": stage,
                            "label": (label if reveal_secrets else "Running step"),
                            "stageIndex": idx,
                            "agentId": resolved["agentId"],
                        }
                    )

                async def on_token(token: str) -> None:
                    nonlocal tokens_emitted
                    await emit({"token": token})
                    tokens_emitted += len(token)

                await emit({"stage": "thinking", "label": "Thinking", "stageIndex": 0, "agentId": resolved["agentId"]})

                result = await run_agent_turn_stream(
                    message,
                    conv.get("messages") or [],
                    resolved["skillId"],
                    on_stage=on_stage,
                    on_token=on_token,
                    on_progress=emit_progress,
                    opts=RunOpts(
                        allowed_skill_ids=resolved.get("allowedSkillIds") or None,
                        contexts=resolved.get("contexts") or {},
                        conversation_id=conv["id"],
                        message_id=assistant_message_id,
                    ),
                )

                text = result.text or ""
                if result.status == "error" and not text:
                    text = "I could not run the automation for this request. Please try again."

                if text and tokens_emitted == 0:
                    await emit({"token": text})
                elif result.status == "error" and tokens_emitted == 0:
                    await emit({"token": text})

                skills_count = len(
                    await get_skill_calls_by_message_id(
                        assistant_message_id,
                        user_id=current_user.user_id,
                        is_admin=current_user.is_admin,
                    )
                )
                await update_message_content(conv["id"], assistant_message_id, text, None, skills_count)
                await save_stage_outputs(conv["id"], merged_stage_outputs, None)

                token_usage = await get_token_usage(
                    assistant_message_id,
                    user_id=current_user.user_id,
                    is_admin=current_user.is_admin,
                )
                await emit(
                    {
                        "done": True,
                        "conversationId": conv["id"],
                        "messageId": assistant_message_id,
                        "runId": result.run_id,
                        "model": CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
                        "durationMs": result.duration_ms,
                        "stageOutputs": merged_stage_outputs,
                        "outputFile": None,
                        "agentId": resolved["agentId"],
                        "tokenUsage": token_usage,
                    }
                )
            except Exception as exc:
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


@router.post("/api/chat/plan")
async def p2_chat_plan(req: Request, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    return await _create_plan_draft(body=body, current_user=current_user)


@router.post("/api/chat/plan/stream")
async def p2_chat_plan_stream(req: Request, current_user: Any = Depends(_require_phase2_user)) -> StreamingResponse:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

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
                result = await _create_plan_draft(body=body, current_user=current_user, emit_progress=emit_progress)
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


@router.post("/api/chat/plan/approve/stream")
async def p2_approve_plan_stream(req: Request, current_user: Any = Depends(_require_phase2_user)) -> StreamingResponse:
    body = await req.json()
    plan_id = str(body.get("planId") or "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")

    resolved = await _resolve_agent_and_skill(body, current_user=current_user)
    reveal_secrets = bool(current_user.is_admin) or not bool(resolved.get("isLocked"))
    conv = await get_or_create_conversation(
        body.get("conversationId"),
        resolved["agentId"],
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    plan = await get_plan_run(plan_id, user_id=current_user.user_id, is_admin=current_user.is_admin)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    if plan.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="plan was cancelled (create a new plan)")
    if plan.get("status") in ("executing", "done"):
        raise HTTPException(status_code=409, detail=f"plan is already {plan.get('status')}")

    if isinstance(body.get("planMarkdown"), str) and body.get("planMarkdown").strip():
        await update_plan_run(
            plan_id,
            {"planMarkdown": body.get("planMarkdown")},
            user_id=current_user.user_id,
            is_admin=current_user.is_admin,
        )
    await update_plan_run(
        plan_id,
        {"status": "approved"},
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
    )

    assistant_message_id = await append_assistant_placeholder(conv["id"])
    _log(
        "approve-stream-start",
        plan_id=plan_id,
        conversation_id=conv.get("id"),
        assistant_message_id=assistant_message_id,
        agent_id=resolved.get("agentId"),
        user_id=str(current_user.user_id),
        is_admin=bool(current_user.is_admin),
        is_super_admin=bool(getattr(current_user, "is_super_admin", False)),
    )

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                exec_start_ms = _time.time() * 1000
                tokens_emitted = 0
                await update_plan_run(
                    plan_id,
                    {"status": "executing"},
                    user_id=current_user.user_id,
                    is_admin=current_user.is_admin,
                )
                await emit({"stage": "thinking", "label": "Executing plan", "stageIndex": 0, "agentId": resolved["agentId"]})
                steps = plan.get("planJson", {}).get("steps", []) if isinstance(plan.get("planJson"), dict) else []
                _log("approve-stream-executing", plan_id=plan_id, conversation_id=conv.get("id"), step_count=len(steps))
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

                for idx, step in enumerate(steps):
                    if not isinstance(step, dict):
                        continue
                    sid = str(step.get("skillId") or "").strip()
                    step_id = str(step.get("stepId") or f"step-{idx + 1}")
                    if not sid:
                        continue
                    if resolved.get("allowedSkillIds") and sid not in (resolved.get("allowedSkillIds") or []):
                        continue

                    step_args: dict[str, Any] = dict(step.get("args") or {})
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

                    await emit(
                        {
                            "stage": "running",
                            "label": (f"Running {sid}" if reveal_secrets else "Running step"),
                            "stageIndex": idx + 1,
                            "agentId": resolved["agentId"],
                        }
                    )

                    run_id = f"run-{sid}-{idx}-{uuid4().hex[:8]}"
                    call_id = await create_skill_call(conv["id"], assistant_message_id, sid, run_id, {"args": step_args})
                    page_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
                    page_worker_task: asyncio.Task | None = None
                    if _should_stream_page_nl(sid):
                        async def _page_worker() -> None:
                            # Prefer Claude when configured; avoid hard-failing on OpenAI quota.
                            ai = AiHelper(temperature=0.2)
                            while True:
                                meta = await page_queue.get()
                                if meta is None:
                                    break
                                try:
                                    prompt = _build_page_nl_prompt(sid, meta)
                                    r = await ai.chat(
                                        message=prompt,
                                        system_prompt="You convert web extraction objects into compact factual notes.",
                                    )
                                    page_url = str(meta.get("url") or "").strip()
                                    note = (r.message or "").strip()
                                    if note:
                                        chunk = f"page: {page_url}\ncontent: {note}\n\n"
                                        await append_skill_streamed_text(call_id, chunk)
                                    await save_token_usage(
                                        assistant_message_id,
                                        (CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL),
                                        r.input_tokens,
                                        r.output_tokens,
                                        stage=f"page-nl.{sid}",
                                        provider=("anthropic" if CLAUDE_API_KEY else "openai"),
                                    )
                                except Exception:
                                    pass
                        page_worker_task = asyncio.create_task(_page_worker())
                    await emit_progress(
                        {
                            "stage": "thinking",
                            "type": "task",
                            "message": f"Running skill: {sid}",
                            "meta": {
                                "kind": "skill-call",
                                "id": run_id,
                                "skillId": (sid if reveal_secrets else ""),
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
                            )
                        stream_kind = str(meta.get("streamKind") or "info").strip().lower()
                        if stream_kind == "data":
                            await push_skill_output(
                                call_id,
                                {"type": "progress", "event": str(meta.get("event")) if meta.get("event") else None, "payload": meta},
                            )
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
                            "message": f"Skill {sid} {'failed' if result.status == 'error' else 'completed'}",
                            "meta": {
                                "kind": "skill-call",
                                "id": run_id,
                                "skillId": (sid if reveal_secrets else ""),
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
                            await update_plan_run(
                                plan_id,
                                {"planMarkdown": plan_markdown_live},
                                user_id=current_user.user_id,
                                is_admin=current_user.is_admin,
                            )
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

                formatter_calls = await get_skill_calls_by_message_id(
                    assistant_message_id,
                    user_id=current_user.user_id,
                    is_admin=current_user.is_admin,
                )
                last_heartbeat_s = _time.time()
                async def _on_final_token(token: str) -> None:
                    nonlocal tokens_emitted
                    nonlocal last_heartbeat_s
                    tokens_emitted += len(token)
                    now_s = _time.time()
                    if now_s - last_heartbeat_s >= 10:
                        last_heartbeat_s = now_s
                        _log(
                            "approve-stream-final-formatter-heartbeat",
                            plan_id=plan_id,
                            conversation_id=conv.get("id"),
                            output_chars=tokens_emitted,
                            output_tokens_est=max(1, tokens_emitted // 4),
                        )
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
                _log(
                    "approve-stream-final-formatter-done",
                    plan_id=plan_id,
                    conversation_id=conv.get("id"),
                    provider=fmt.provider,
                    model=fmt.model,
                    input_tokens=fmt.input_tokens,
                    output_tokens=fmt.output_tokens,
                    output_chars=len(fmt.text or ""),
                )
                await save_token_usage(
                    assistant_message_id,
                    fmt.model,
                    fmt.input_tokens,
                    fmt.output_tokens,
                    stage="plan-execution.final-formatting",
                    provider=fmt.provider,
                )
                final_text = (fmt.text or "").strip()
                if final_text and tokens_emitted == 0:
                    await emit({"token": final_text})

                skills_count = len(
                    await get_skill_calls_by_message_id(
                        assistant_message_id,
                        user_id=current_user.user_id,
                        is_admin=current_user.is_admin,
                    )
                )
                await update_message_content(conv["id"], assistant_message_id, final_text, None, skills_count)
                await save_stage_outputs(conv["id"], stage_outputs, None)

                await update_plan_run(
                    plan_id,
                    {"status": "done"},
                    user_id=current_user.user_id,
                    is_admin=current_user.is_admin,
                )
                token_usage = await get_token_usage(
                    assistant_message_id,
                    user_id=current_user.user_id,
                    is_admin=current_user.is_admin,
                )
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
            except asyncio.CancelledError:
                # Client disconnected (tab closed, network drop, etc.)
                _log("approve-stream-worker-cancelled", plan_id=plan_id, conversation_id=conv.get("id"))
                raise
            except Exception as exc:
                _log("approve-stream-worker-error", error=str(exc), traceback=traceback.format_exc(), plan_id=plan_id, conversation_id=conv.get("id"))
                await update_plan_run(
                    plan_id,
                    {"status": "error"},
                    user_id=current_user.user_id,
                    is_admin=current_user.is_admin,
                )
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


@router.get("/api/chat/messages")
async def p2_chat_messages(conversationId: str | None = None, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    conv = await get_or_create_conversation(
        conversationId,
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
        is_super_admin=current_user.is_super_admin,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "messages": conv.get("messages") or [],
        "conversationId": conv["id"],
        "agentId": conv.get("agentId"),
        "lastStageOutputs": conv.get("lastStageOutputs") or {},
        "lastOutputFile": conv.get("lastOutputFile"),
    }


@router.get("/api/chat/skill-calls")
async def p2_chat_skill_calls(messageId: str | None = None, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    if not messageId or not messageId.strip():
        raise HTTPException(status_code=400, detail="messageId is required")
    return {
        "skillCalls": await get_skill_calls_by_message_id_full(
            messageId.strip(),
            user_id=current_user.user_id,
            is_admin=current_user.is_admin,
        )
    }


@router.get("/api/chat/token-usage")
async def p2_chat_token_usage(messageId: str | None = None, current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    if not messageId or not messageId.strip():
        raise HTTPException(status_code=400, detail="messageId is required")
    return await get_token_usage(
        messageId.strip(),
        user_id=current_user.user_id,
        is_admin=current_user.is_admin,
    )


@router.get("/api/chat/insight-feedback")
async def p2_list_insight_feedback(
    messageId: str | None = None,
    current_user: Any = Depends(_require_phase2_user),
) -> dict[str, Any]:
    if not messageId or not messageId.strip():
        raise HTTPException(status_code=400, detail="messageId is required")
    items = await list_insight_feedback(messageId.strip(), user_id=current_user.user_id, is_admin=current_user.is_admin)
    return {"feedback": items}


@router.post("/api/chat/insight-feedback")
async def p2_set_insight_feedback(
    req: Request,
    current_user: Any = Depends(_require_phase2_user),
) -> dict[str, Any]:
    body = await req.json()
    message_id = str(body.get("messageId") or "").strip()
    insight_index = body.get("insightIndex")
    rating = body.get("rating")
    if not message_id:
        raise HTTPException(status_code=400, detail="messageId is required")
    if insight_index is None:
        raise HTTPException(status_code=400, detail="insightIndex is required")
    if rating is None:
        raise HTTPException(status_code=400, detail="rating is required")
    try:
        saved = await set_insight_feedback(
            message_id,
            insight_index=int(insight_index),
            rating=int(rating),
            user_id=current_user.user_id,
            is_admin=current_user.is_admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"feedback": saved}


@router.get("/api/chat/conversations")
async def p2_chat_conversations(current_user: Any = Depends(_require_phase2_user)) -> dict[str, Any]:
    return {
        "conversations": await list_conversations(
            user_id=current_user.user_id,
            is_super_admin=current_user.is_super_admin,
        )
    }


@router.delete("/api/chat/conversations/{conversation_id}")
async def p2_chat_delete_conversation(
    conversation_id: str,
    current_user: Any = Depends(_require_phase2_user),
) -> dict[str, bool]:
    return {
        "ok": await delete_conversation(
            conversation_id,
            user_id=current_user.user_id,
            is_super_admin=current_user.is_super_admin,
        )
    }
