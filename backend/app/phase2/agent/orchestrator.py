from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from app.config import get_settings
from app.services.ai_helper import ai_helper as _ai
from app.skills.service import SkillManifest, SkillRunResult, get_skill, list_skills, run_skill
from ..stores import (
    create_skill_call,
    get_skill_calls_by_message_id,
    get_skill_calls_by_message_id_full,
    push_skill_output,
    set_skill_call_result,
)
from .gemini_models import get_planner_models
from .skill_call_summarizer import build_calls_summary
from .skill_input_extractor import extract_skill_args
from .final_formatter import format_final_answer, FormatterResult


def prune_history(history: list[dict[str, Any]], max_tokens: int = 8_000) -> list[dict[str, Any]]:
    char_budget = max_tokens * 4
    total = sum(len(m.get("content", "")) for m in history)
    if total <= char_budget:
        return history
    if not history:
        return history
    anchor = history[0]
    used = len(anchor.get("content", ""))
    tail: list[dict[str, Any]] = []
    for m in reversed(history[1:]):
        if used + len(m.get("content", "")) > char_budget:
            break
        tail.insert(0, m)
        used += len(m.get("content", ""))
    return [anchor, *tail]


def repair_transcript(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in history:
        if not str(msg.get("content") or "").strip():
            continue
        if out and out[-1]["role"] == msg["role"]:
            out[-1] = {**out[-1], "content": out[-1]["content"] + "\n\n" + msg["content"]}
        else:
            out.append(dict(msg))
    return out

ProgressCb = Callable[[dict[str, Any]], Awaitable[None] | None]
TokenCb = Callable[[str], Awaitable[None] | None]
StageCb = Callable[[str, str, int], Awaitable[None] | None]

MAX_LOOPS = 15

REPEATABLE_SKILLS = {
    "web-search",
    "platform-scout",
    "platform-taxonomy",
    "classify-links",
    "business-scan",
    "scrape-agentbrowser",
    "scrape-playwright",
    "scrape-bs4",
    "scrape-googlebusiness",
    "quora-search",
    "find-platform-handles",
    "instagram-sentiment",
    "youtube-sentiment",
    "playstore-sentiment",
}
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)

DEFAULT_SELECTOR_CONTEXT = "\n".join([
    "You are a router that decides which local skill(s) to run next.",
    "",
    "General behaviour:",
    "- You may select ZERO, ONE, or MULTIPLE skills per round; multiple skills in skillIds run in parallel. but try to select as many skills as possible in each round.",
    "- Never choose a skill that has already been used with the same obvious target (e.g. same URL or same platform) unless there is a strong new reason.",
    "- If NONE of the skills clearly apply to the user message, set done = true and skillIds = [].",
    "",
    "Response format:",
    '- Always reply with JSON only: { "done": boolean, "skillIds": ["id1", "id2", ...] }.',
    "- Use skillIds = [] when done or when no skill applies.",
])


@dataclass
class RunOpts:
    allowed_skill_ids: list[str] | None = None
    contexts: dict[str, str] = field(default_factory=dict)
    conversation_id: str | None = None
    message_id: str | None = None


@dataclass
class OrchestratorResult:
    run_id: str
    status: str
    text: str
    error: str | None
    stage_outputs: dict[str, Any]
    duration_ms: int


async def _emit(cb: ProgressCb | None, event: dict[str, Any]) -> None:
    if cb is None:
        return
    result = cb(event)
    if asyncio.iscoroutine(result):
        await result


async def _emit_stage(cb: StageCb | None, stage: str, label: str, idx: int) -> None:
    if cb is None:
        return
    result = cb(stage, label, idx)
    if asyncio.iscoroutine(result):
        await result


def _append_prior_skill_outputs(user_message: str, calls: list[dict[str, Any]]) -> str:
    if not calls:
        return user_message
    blocks = []
    for c in calls:
        parts = [f"skillId: {c.get('skillId', '?')}"]
        text_excerpt = str(c.get("rawText") or "")[:4000]
        if text_excerpt.strip():
            parts.append(f"rawText excerpt:\n{text_excerpt}")
        blocks.append("\n".join(parts))
    return "\n".join([
        user_message.strip(),
        "",
        "---",
        "PRIOR SKILL OUTPUTS (use rawData and excerpts below to fill arguments for the NEXT skill — e.g. Instagram handle/URL from find-platform-handles; do not use only the original user message when this block contains the right entity):",
        "\n\n---\n\n".join(blocks),
    ])


def _build_planning_prompt(
    message: str,
    selector_context: str,
    skills_for_prompt: list[dict[str, str]],
    calls_summary: str,
    last_skill_raw_output: str,
    skill_calls: list[dict[str, Any]],
    used_skill_ids: list[str],
    checklist_unchecked: list[str] | None = None,
    parallel_limit: int = 3,
) -> str:
    skills_md = "\n".join(
        f"- **{s['id']}** — {s['name']}: {s.get('description', '')}"
        for s in skills_for_prompt
    )
    last_data_excerpt = ""
    if skill_calls:
        last = skill_calls[-1]
        raw_data = last.get("rawData")
        if raw_data is not None:
            last_data_excerpt = f"\nLast skill structured rawData (JSON excerpt):\n{json.dumps(raw_data)[:3000]}\n"

    checklist_unchecked = checklist_unchecked or []
    parts = [selector_context, "", "Available skills:", skills_md, "", f"User message:\n{message}", ""]
    if checklist_unchecked:
        parts += [
            "Unchecked plan checklist items (focus ONLY on these):",
            "\n".join(f"- {it}" for it in checklist_unchecked),
            "",
            "Selection policy:",
            "- Choose skills that best satisfy unchecked items only.",
            f"- Select between 1 and {parallel_limit} skills this round.",
            "- Do not over-call skills; run parallel only when items are independent.",
        ]
    else:
        parts += [f"Skill calls so far (summary):\n{calls_summary}"]
        if last_skill_raw_output:
            parts.append(f"\nLast skill raw output:\n{last_skill_raw_output}\n")
        if last_data_excerpt:
            parts.append(last_data_excerpt)
    parts.append(
        f"Skills used so far in this turn (repeats allowed if args/target differs): {', '.join(used_skill_ids) or '(none)'}"
    )
    parts.append("")
    parts.append(
        'Reply with JSON only: { "done": boolean, "skillIds": ["id1", "id2", ...] }. Use skillIds = [] when done or when no skill applies.'
    )
    return "\n".join(p for p in parts if isinstance(p, str) and p.strip() != "")


def _is_retryable_model(err_msg: str) -> bool:
    lower = err_msg.lower()
    return any(k in lower for k in ["503", "429", "unavailable", "resource_exhausted", "overloaded", "high demand"])


def _is_404_model(err_msg: str) -> bool:
    lower = err_msg.lower()
    return any(k in lower for k in ["404", "not_found", '"code":404'])


def _extract_url(message: str) -> str:
    m = URL_RE.search(message or "")
    return m.group(0).rstrip("),.;]\"'") if m else ""


def _parse_checklist_items(markdown: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ln in (markdown or "").splitlines():
        line = ln.strip()
        if not line.startswith(("- [", "* [")):
            continue
        checked = line.lower().startswith("- [x]") or line.lower().startswith("* [x]")
        text = re.sub(r"^[-*]\s+\[[ xX]\]\s+", "", line).strip()
        if not text:
            continue
        items.append({"text": text, "done": checked})
    return items


def _unchecked_items(items: list[dict[str, Any]]) -> list[str]:
    return [str(i.get("text") or "").strip() for i in items if not i.get("done") and str(i.get("text") or "").strip()]


def _optimal_parallel_count(unchecked_count: int) -> int:
    if unchecked_count <= 1:
        return 1
    if unchecked_count <= 4:
        return 2
    return 3


async def _mark_checklist_items_from_summary(
    checklist_items: list[dict[str, Any]],
    *,
    skill_id: str,
    summary_text: str,
) -> None:
    unchecked = _unchecked_items(checklist_items)
    if not unchecked or not (summary_text or "").strip():
        return
    payload = {
        "uncheckedItems": unchecked,
        "skillId": skill_id,
        "skillSummary": summary_text[:12000],
    }
    try:
        res = await _ai.chat(
            message="\n".join(
                [
                    "Given unchecked checklist items and one skill summary, return which checklist items are now satisfied.",
                    'Return JSON only with shape: { "checkedItems": ["exact item text", ...] }',
                    "Rules: choose only items directly supported by evidence from the summary. No guessing.",
                    json.dumps(payload, ensure_ascii=False),
                ]
            ),
            system_prompt="You are a strict evidence matcher.",
            conversation_history=[],
        )
        parsed = json.loads((res.message or "").strip())
        checked = parsed.get("checkedItems") if isinstance(parsed, dict) else []
        checked_set = {str(x).strip() for x in (checked or []) if str(x).strip()}
        if checked_set:
            for item in checklist_items:
                txt = str(item.get("text") or "").strip()
                if txt in checked_set:
                    item["done"] = True
    except Exception:
        lower = (summary_text or "").lower()
        for item in checklist_items:
            if item.get("done"):
                continue
            txt = str(item.get("text") or "").strip().lower()
            tokens = [t for t in re.findall(r"[a-z0-9]{4,}", txt) if t not in {"with", "from", "that", "this", "have", "will"}]
            if tokens and sum(1 for t in tokens if t in lower) >= min(3, max(1, len(tokens) // 2)):
                item["done"] = True


async def run_single_skill_fallback(
    message: str,
    skill_id: str,
    manifest: SkillManifest,
    history: list[dict[str, Any]],
    on_stage: StageCb | None,
    on_token: TokenCb | None,
    on_progress: ProgressCb | None,
    conversation_id: str | None,
    message_id: str | None,
) -> OrchestratorResult:
    start = time.time()
    run_id = f"run-{skill_id}-{int(start * 1000)}"

    extracted_args: dict[str, Any] = {}
    if manifest.input_schema:
        try:
            maybe = await extract_skill_args(skill_id, message, manifest.input_schema)
            if maybe:
                extracted_args = maybe
        except Exception:
            pass

    await _emit_stage(on_stage, "thinking", "Thinking", 0)
    await _emit(on_progress, {
        "stage": "thinking",
        "type": "task",
        "message": f"Running skill: {skill_id}",
        "meta": {
            "kind": "skill-call",
            "id": run_id,
            "skillId": skill_id,
            "status": "running",
            "input": {"args": extracted_args},
        },
    })
    await _emit_stage(on_stage, "scraping", f"Running {skill_id}", 1)

    skill_call_id: str | None = None
    if conversation_id and message_id:
        skill_call_id = await create_skill_call(
            conversation_id, message_id, skill_id, run_id, {"args": extracted_args}
        )

    async def _on_prog(event: dict[str, Any]) -> None:
        if skill_call_id:
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            has_data = meta and (meta.get("event") is not None or meta.get("url") is not None or
                                  any(k != "at" for k in meta.keys()))
            if has_data:
                await push_skill_output(skill_call_id, {
                    "type": "progress",
                    "event": str(meta.get("event")) if meta.get("event") else None,
                    "payload": meta,
                })
        await _emit(on_progress, event)

    result = await run_skill(skill_id, message, history=prune_history(repair_transcript(history)), args=extracted_args or None, on_progress=_on_prog)

    if skill_call_id:
        await set_skill_call_result(
            skill_call_id,
            "error" if result.status == "error" else "done",
            result.text, result.data, result.error,
        )

    await _emit(on_progress, {
        "stage": "error" if result.status == "error" else "thinking",
        "type": "task",
        "message": f"Skill {skill_id} {'failed' if result.status == 'error' else 'completed'}",
        "meta": {
            "kind": "skill-call",
            "id": run_id,
            "skillId": skill_id,
            "status": "error" if result.status == "error" else "done",
            "input": {"args": extracted_args},
            "outputSummary": (result.text or "")[:600],
        },
    })

    return OrchestratorResult(
        run_id=run_id,
        status=result.status,
        text=result.text,
        error=result.error,
        stage_outputs={},
        duration_ms=result.duration_ms,
    )


async def run_agent_turn_stream(
    message: str,
    history: list[dict[str, Any]],
    skill_id: str,
    on_stage: StageCb | None = None,
    on_token: TokenCb | None = None,
    on_progress: ProgressCb | None = None,
    opts: RunOpts | None = None,
) -> OrchestratorResult:
    opts = opts or RunOpts()
    manifest = get_skill(skill_id)

    if not manifest:
        return OrchestratorResult(
            run_id=f"no-skill-{int(time.time() * 1000)}",
            status="error",
            text="",
            error="No skill registered with that id.",
            stage_outputs={},
            duration_ms=0,
        )

    settings = get_settings()
    if not (settings.OPENROUTER_API_KEY or "").strip():
        return await run_single_skill_fallback(
            message,
            skill_id,
            manifest,
            history,
            on_stage,
            on_token,
            on_progress,
            opts.conversation_id,
            opts.message_id,
        )

    model_ids = get_planner_models()

    allowed_skill_ids = opts.allowed_skill_ids
    contexts = opts.contexts or {}
    conversation_id = opts.conversation_id
    message_id_opt = opts.message_id

    persist_to_db = bool(conversation_id and message_id_opt)

    used_skill_ids: list[str] = []
    used_call_keys: set[str] = set()
    skill_calls: list[dict[str, Any]] = []
    start = time.time()
    last_skill_result: dict[str, Any] | None = None
    last_skill_raw_output = ""
    plan_unavailable = False
    checklist_source = str(contexts.get("planMarkdown") or message)
    checklist_items = _parse_checklist_items(checklist_source)

    for loop in range(MAX_LOOPS):
        if plan_unavailable:
            break

        if message_id_opt:
            skill_calls = await get_skill_calls_by_message_id(message_id_opt)

        calls_summary = await build_calls_summary(skill_calls)
        unchecked_items = _unchecked_items(checklist_items)
        parallel_limit = _optimal_parallel_count(len(unchecked_items)) if unchecked_items else 3

        all_skills = list_skills()
        skills_for_prompt = [
            {"id": s["id"], "name": s["name"], "description": s.get("description", "")}
            for s in all_skills
            if (not allowed_skill_ids or s["id"] in allowed_skill_ids)
        ]

        selector_context = "\n\n".join(filter(None, [
            DEFAULT_SELECTOR_CONTEXT,
            (contexts.get("skillSelectorContext") or "").strip(),
        ]))

        planning_prompt = _build_planning_prompt(
            message=message,
            selector_context=selector_context,
            skills_for_prompt=skills_for_prompt,
            calls_summary=calls_summary,
            last_skill_raw_output=last_skill_raw_output,
            skill_calls=skill_calls,
            used_skill_ids=used_skill_ids,
            checklist_unchecked=unchecked_items,
            parallel_limit=parallel_limit,
        )

        plan: dict[str, Any] = {"done": True, "skillIds": []}
        last_plan_error: Exception | None = None

        for model_id in model_ids:
            try:
                parsed = await _ai.complete_json_with_candidates(
                    model_candidates=_ai.model_candidates(
                        model_id,
                        prefix_env="OPENROUTER_MODEL_PREFIX",
                    ),
                    messages=[{"role": "user", "content": planning_prompt}],
                    temperature=0.3,
                    max_tokens=900,
                )
                skill_ids_raw = parsed.get("skillIds") or []
                if isinstance(skill_ids_raw, str):
                    skill_ids_raw = [skill_ids_raw] if skill_ids_raw else []
                plan = {
                    "done": bool(parsed.get("done", True)),
                    "skillIds": [s for s in skill_ids_raw if isinstance(s, str)],
                }
                last_plan_error = None
                break
            except Exception as e:
                last_plan_error = e
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code == 404:
                    plan_unavailable = True
                    break
                # For retryable/transient failures, try next model id.
                if status_code in (429, 503) and model_ids.index(model_id) < len(model_ids) - 1:
                    continue
                break

        if plan_unavailable or last_plan_error:
            return await run_single_skill_fallback(
                message,
                skill_id,
                manifest,
                history,
                on_stage,
                on_token,
                on_progress,
                conversation_id,
                message_id_opt,
            )
        if loop == 0:
            seed_url = _extract_url(message)
            already_used_playwright = any(c.get("skillId") == "scrape-playwright" for c in skill_calls)
            can_use_playwright = (not allowed_skill_ids) or ("scrape-playwright" in allowed_skill_ids)
            if seed_url and can_use_playwright and not already_used_playwright:
                skill_ids_existing = plan.get("skillIds") or []
                if "scrape-playwright" not in skill_ids_existing:
                    plan["skillIds"] = ["scrape-playwright", *skill_ids_existing]
        if plan.get("done") or not plan.get("skillIds"):
            break
        if parallel_limit > 0 and len(plan["skillIds"]) > parallel_limit:
            plan["skillIds"] = plan["skillIds"][:parallel_limit]

        planned_manifests: list[SkillManifest] = []
        for sid in plan["skillIds"]:
            m = get_skill(sid)
            if not m:
                continue
            if allowed_skill_ids and sid not in allowed_skill_ids:
                continue
            planned_manifests.append(m)
            if sid not in used_skill_ids:
                used_skill_ids.append(sid)

        if not planned_manifests:
            break

        if unchecked_items:
            skill_input_message = "\n".join(
                [
                    message.strip(),
                    "",
                    "Unchecked checklist items:",
                    "\n".join(f"- {it}" for it in unchecked_items),
                ]
            )
        else:
            skill_input_message = _append_prior_skill_outputs(message, skill_calls)

        extracted_args_list: list[dict[str, Any]] = []
        filtered_manifests: list[SkillManifest] = []
        for m in planned_manifests:
            args: dict[str, Any] = {}
            if m.input_schema:
                extracted = await extract_skill_args(m.id, skill_input_message, m.input_schema)
                if extracted:
                    args = extracted
            call_key = f"{m.id}:{json.dumps(args, sort_keys=True)}" if m.id in REPEATABLE_SKILLS else m.id
            if call_key in used_call_keys:
                continue
            used_call_keys.add(call_key)
            filtered_manifests.append(m)
            extracted_args_list.append(args)

        if not filtered_manifests:
            break

        await _emit_stage(on_stage, "thinking", "Thinking", loop)

        run_ids: list[str] = []
        for idx, m in enumerate(filtered_manifests):
            args = extracted_args_list[idx]
            run_id = f"run-{m.id}-{int(time.time() * 1000)}-{idx}"
            run_ids.append(run_id)
            await _emit(on_progress, {
                "stage": "thinking",
                "type": "task",
                "message": f"Running skill: {m.id}",
                "meta": {
                    "kind": "skill-call",
                    "id": run_id,
                    "skillId": m.id,
                    "status": "running",
                    "input": {"args": args} if args else {},
                },
            })

        skill_call_ids: list[str | None] = []
        if persist_to_db and conversation_id and message_id_opt:
            for idx, m in enumerate(filtered_manifests):
                args = extracted_args_list[idx]
                run_id = run_ids[idx]
                cid = await create_skill_call(
                    conversation_id, message_id_opt, m.id, run_id, {"args": args} if args else {}
                )
                skill_call_ids.append(cid)
        else:
            skill_call_ids = [None] * len(filtered_manifests)

        async def _run_one(idx: int) -> tuple[int, SkillRunResult]:
            m = filtered_manifests[idx]
            args = extracted_args_list[idx]
            skill_call_id = skill_call_ids[idx]

            async def _on_prog(event: dict[str, Any]) -> None:
                if skill_call_id:
                    meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
                    has_data = meta and (
                        meta.get("event") is not None or meta.get("url") is not None
                        or any(k != "at" for k in meta.keys())
                    )
                    if has_data:
                        await push_skill_output(skill_call_id, {
                            "type": "progress",
                            "event": str(meta.get("event")) if meta.get("event") else None,
                            "payload": meta,
                        })
                await _emit(on_progress, event)

            result = await run_skill(m.id, skill_input_message, history=prune_history(repair_transcript(history)), args=args or None, on_progress=_on_prog)
            return idx, result

        batch_results = await asyncio.gather(*(_run_one(i) for i in range(len(filtered_manifests))))

        batch_excerpts: list[str] = []
        for idx, skill_result in batch_results:
            m = filtered_manifests[idx]
            skill_call_id = skill_call_ids[idx]
            run_id = run_ids[idx]
            args = extracted_args_list[idx]
            raw_text = skill_result.text or ""
            batch_excerpts.append(raw_text)

            last_skill_result = {
                "runId": run_id,
                "status": skill_result.status,
                "text": raw_text,
                "error": skill_result.error,
                "data": skill_result.data,
                "stageOutputs": {},
            }

            if skill_call_id:
                await set_skill_call_result(
                    skill_call_id,
                    "error" if skill_result.status == "error" else "done",
                    raw_text, skill_result.data, skill_result.error,
                )
            else:
                skill_calls.append({
                    "id": run_id,
                    "skillId": m.id,
                    "status": "error" if skill_result.status == "error" else "ok",
                    "input": {"args": args},
                    "startedAt": "",
                    "endedAt": "",
                    "durationMs": skill_result.duration_ms,
                    "rawText": raw_text,
                    "rawData": skill_result.data,
                    "error": skill_result.error,
                })

            await _emit(on_progress, {
                "stage": "error" if skill_result.status == "error" else "thinking",
                "type": "task",
                "message": f"Skill {m.id} {'failed' if skill_result.status == 'error' else 'completed'}",
                "meta": {
                    "kind": "skill-call",
                    "id": run_id,
                    "skillId": m.id,
                    "status": "error" if skill_result.status == "error" else "done",
                    "input": {"args": args},
                    "outputSummary": raw_text[:600],
                },
            })
            if checklist_items and skill_result.status != "error" and raw_text.strip():
                await _mark_checklist_items_from_summary(
                    ai,
                    checklist_items,
                    skill_id=m.id,
                    summary_text=raw_text,
                )

        last_skill_raw_output = "\n\n---\n\n".join(batch_excerpts)
        if persist_to_db and message_id_opt:
            skill_calls = await get_skill_calls_by_message_id(message_id_opt)

    if plan_unavailable or (not skill_calls and not last_skill_result):
        return await run_single_skill_fallback(
            message, skill_id, manifest, history,
            on_stage, on_token, on_progress,
            conversation_id, message_id_opt,
        )

    if skill_calls:
        formatter_calls = skill_calls
        if message_id_opt:
            try:
                formatter_calls = await get_skill_calls_by_message_id_full(message_id_opt)
            except Exception:
                pass

        fmt = await format_final_answer(
            message=message,
            start_ms=start * 1000,
            skill_calls=formatter_calls,
            last_skill_result=last_skill_result,
            contexts=contexts,
            on_token=on_token,
        )
        return OrchestratorResult(
            run_id=fmt.run_id,
            status=fmt.status,
            text=fmt.text,
            error=fmt.error,
            stage_outputs=fmt.stage_outputs,
            duration_ms=fmt.duration_ms,
        )

    return OrchestratorResult(
        run_id=(last_skill_result or {}).get("runId") or f"orchestrator-{int(time.time() * 1000)}",
        status=(last_skill_result or {}).get("status") or "ok",
        text=(last_skill_result or {}).get("text") or "",
        error=(last_skill_result or {}).get("error"),
        stage_outputs={},
        duration_ms=int((time.time() - start) * 1000),
    )
