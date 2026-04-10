from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4
from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

_DATA_PATH = Path(__file__).parent.parent / "data" / "business_problem_journey.json"
_SCALE_PATH = Path(__file__).parent.parent / "data" / "scale_questions.json"

with _DATA_PATH.open() as _f:
    _JOURNEY: dict[str, Any] = json.load(_f)

with _SCALE_PATH.open() as _f:
    _SCALE_QUESTIONS: list[dict[str, Any]] = json.load(_f)

# outcome text → outcome id (e.g. "Lead Generation" → "lead-generation")
_OUTCOME_TEXT_TO_ID: dict[str, str] = {
    o["text"]: o["id"] for o in _JOURNEY["outcomes"]
}

_OUTCOME_LABEL: dict[str, str] = {
    "lead-generation": "Lead Generation",
    "sales-retention": "Sales & Retention",
    "business-strategy": "Business Strategy",
    "save-time": "Save Time",
}

JOURNEY_STEP_OUTCOME    = "outcome"
JOURNEY_STEP_DOMAIN     = "domain"
JOURNEY_STEP_TASK       = "task"
JOURNEY_STEP_URL        = "url"
JOURNEY_STEP_SCALE      = "scale"
JOURNEY_STEP_DIAGNOSTIC = "diagnostic"
JOURNEY_STEP_PRECISION  = "precision"
JOURNEY_STEP_GAP        = "gap"
JOURNEY_STEP_PLAYBOOK   = "playbook"
JOURNEY_STEP_COMPLETE   = "complete"
onboarding_t = Table("onboarding")


# ── small utils ────────────────────────────────────────────────────────────────

def _as_list(v: Any) -> list[Any]:
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, list) else []
        except Exception:
            return []
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, dict) else {}
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


# ── helpers ────────────────────────────────────────────────────────────────

def get_outcome_options() -> list[str]:
    return [o["text"] for o in _JOURNEY["outcomes"]]


def get_domain_options(selected_outcome_text: str) -> list[str] | None:
    outcome_id = _OUTCOME_TEXT_TO_ID.get(selected_outcome_text)
    if not outcome_id:
        return None
    return list(_JOURNEY["outcome_domains"].get(outcome_id, []))


def get_task_options(selected_domain: str) -> list[str] | None:
    tasks = _JOURNEY["domain_tasks"].get(selected_domain)
    return list(tasks) if tasks else None


def get_scale_questions() -> list[dict[str, Any]]:
    """Return all scale questions with their IDs, question text, and options."""
    return _SCALE_QUESTIONS


def get_scale_question_by_id(q_id: str) -> dict[str, Any] | None:
    """Return a specific scale question by its ID."""
    for q in _SCALE_QUESTIONS:
        if q.get("id") == q_id:
            return q
    return None


def _build_scale_message(index: int, acc: dict[str, Any]) -> dict[str, Any]:
    """Build assistant message for one scale question, carrying accumulated context."""
    q = _SCALE_QUESTIONS[index]
    options = list(q["options"])
    scale_answers: dict = dict(acc.get("scaleAnswers") or {})

    if q.get("multi_select"):
        already = scale_answers.get(q["id"], [])
        if isinstance(already, list) and already:
            selected_labels = ", ".join(already)
            content = (
                f"**{q['question']}**\n\n"
                f"Selected so far: {selected_labels}\n\n"
                "Pick more or click **Done ✓** to continue."
            )
            remaining = [o for o in options if o not in already]
            options = remaining + ["Done ✓"]
        else:
            content = f"**{q['question']}**"
    else:
        content = f"**{q['question']}**"

    return {
        "content": content,
        "options": options,
        "allowCustomAnswer": False,
        "journeyStep": JOURNEY_STEP_SCALE,
        "journeySelections": {**acc, "scaleIndex": index, "scaleAnswers": scale_answers},
        "kind": "final",
    }


def start_scale_questions(url: str = "", acc: dict[str, Any] | None = None) -> dict[str, Any]:
    """First scale question message, called after URL typed or Skip."""
    base = dict(acc or {})
    if url:
        base["websiteUrl"] = url
    intro = (
        f"Thanks! I've noted your URL: **{url}**\n\n" if url
        else "No problem, I'll provide general recommendations.\n\n"
    )
    first = _SCALE_QUESTIONS[0]
    return {
        "content": (
            f"{intro}To give you the most relevant recommendations, "
            "I have a few quick questions about your business.\n\n"
            f"**{first['question']}**"
        ),
        "options": list(first["options"]),
        "allowCustomAnswer": False,
        "journeyStep": JOURNEY_STEP_SCALE,
        "journeySelections": {**base, "scaleIndex": 0, "scaleAnswers": {}},
        "kind": "final",
    }


def _diagnostic_message(question: dict[str, Any], acc: dict[str, Any]) -> dict[str, Any]:
    """Wrap an RCA DynamicQuestion dict as a journey message."""
    options = list(question.get("options") or [])
    allows_free = question.get("allows_free_text", True)
    return {
        "content": question.get("question", ""),
        "options": options,
        "allowCustomAnswer": allows_free,
        "journeyStep": JOURNEY_STEP_DIAGNOSTIC,
        "journeySelections": acc,
        "kind": "final",
    }


def _precision_question_message(
    q: dict[str, Any], index: int, total: int, acc: dict[str, Any]
) -> dict[str, Any]:
    options = list(q.get("options") or [])
    return {
        "content": q.get("question", ""),
        "options": options,
        "allowCustomAnswer": True,
        "journeyStep": JOURNEY_STEP_PRECISION,
        "journeySelections": {**acc, "precisionIndex": index, "precisionTotal": total},
        "kind": "final",
    }


def _gap_question_message(
    q: dict[str, Any], index: int, all_questions: list[dict[str, Any]], acc: dict[str, Any]
) -> dict[str, Any]:
    options = list(q.get("options") or [])
    label = str(q.get("label") or "")
    question = str(q.get("question") or "")
    content = f"**{label}**\n\n{question}" if label else question
    return {
        "content": content,
        "options": options,
        "allowCustomAnswer": True,
        "journeyStep": JOURNEY_STEP_GAP,
        "journeySelections": {
            **acc,
            "gapIndex": index,
            "gapQuestions": all_questions,
        },
        "kind": "final",
    }


async def _ensure_onboarding_session(acc: dict[str, Any]) -> str:
    """
    Create (or reuse) an onboarding session for the journey.
    Returns the session_id stored in acc, or creates a new one.
    """
    existing_sid = str(acc.get("onboardingSessionId") or "").strip()
    if existing_sid:
        return existing_sid

    from app.services.onboarding_service import upsert_onboarding_patch

    sid = str(uuid4())
    outcome_text = str(acc.get("outcome") or "")
    outcome_id = _OUTCOME_TEXT_TO_ID.get(outcome_text, "")
    patch: dict[str, Any] = {}
    if outcome_id:
        patch["outcome"] = outcome_id
    if acc.get("domain"):
        patch["domain"] = str(acc["domain"])
    if acc.get("task"):
        patch["task"] = str(acc["task"])
    if acc.get("websiteUrl"):
        patch["website_url"] = str(acc["websiteUrl"])
    if acc.get("scaleAnswers"):
        patch["scale_answers"] = acc["scaleAnswers"]

    await upsert_onboarding_patch(sid, patch)
    return sid


# ── precision ──────────────────────────────────────────────────────────────────

async def _precision_start(acc: dict[str, Any]) -> dict[str, Any]:
    """Start precision questions after RCA diagnostic is complete."""
    from app.db import get_pool
    from app.services.claude_rca_service import generate_precision_questions

    sid = str(acc.get("onboardingSessionId") or "").strip()
    if not sid:
        return _complete_message(acc)

    pool = get_pool()
    async with pool.acquire() as conn:
        load_precision_ctx_q = build_query(
            PostgreSQLQuery.from_(onboarding_t)
            .select(
                onboarding_t.outcome,
                onboarding_t.domain,
                onboarding_t.task,
                onboarding_t.scale_answers,
                onboarding_t.rca_qa,
            )
            .where(onboarding_t.id == Parameter("%s")),
            [sid],
        )
        row = await conn.fetchrow(load_precision_ctx_q.sql, *load_precision_ctx_q.params)

    if not row:
        return _complete_message(acc)

    outcome = str(row.get("outcome") or "")
    domain = str(row.get("domain") or "")
    task = str(row.get("task") or "")
    scale_answers = _as_dict(row.get("scale_answers"))
    rca_qa = _as_list(row.get("rca_qa"))
    rca_history = [
        {"question": str(it.get("question") or ""), "answer": str(it.get("answer") or "")}
        for it in rca_qa
        if isinstance(it, dict) and it.get("answer") not in (None, "")
    ]

    if not rca_history:
        # Nothing to base precision on — skip straight to gap/playbook.
        return await _gap_start(acc)

    outcome_label = _OUTCOME_LABEL.get(outcome, "")

    try:
        questions = await generate_precision_questions(
            outcome=outcome,
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            rca_history=rca_history,
            scale_answers=scale_answers or None,
            web_summary="",
            business_profile_text="",
        )
    except Exception:
        questions = []

    if not questions:
        pool = get_pool()
        async with pool.acquire() as conn:
            mark_precision_empty_q = build_query(
                PostgreSQLQuery.update(onboarding_t)
                .set(onboarding_t.precision_questions, Parameter("%s"))
                .set(onboarding_t.precision_answers, Parameter("%s"))
                .set(onboarding_t.precision_status, "complete")
                .set(onboarding_t.precision_completed_at, fn.Now())
                .set(onboarding_t.updated_at, fn.Now())
                .where(onboarding_t.id == Parameter("%s")),
                [json.dumps([]), json.dumps([]), sid],
            )
            await conn.execute(mark_precision_empty_q.sql, *mark_precision_empty_q.params)
        return await _gap_start(acc)

    cleaned = [
        {
            "type": str(q.get("type") or ""),
            "insight": str(q.get("insight") or ""),
            "question": str(q.get("question") or ""),
            "options": list(q.get("options") or []),
            "section_label": str(q.get("section_label") or ""),
        }
        for q in questions[:3]
    ]

    pool = get_pool()
    async with pool.acquire() as conn:
        save_precision_questions_q = build_query(
            PostgreSQLQuery.update(onboarding_t)
            .set(onboarding_t.precision_questions, Parameter("%s"))
            .set(onboarding_t.precision_answers, Parameter("%s"))
            .set(onboarding_t.precision_status, "awaiting_answers")
            .set(onboarding_t.precision_completed_at, None)
            .set(onboarding_t.updated_at, fn.Now())
            .where(onboarding_t.id == Parameter("%s")),
            [json.dumps(cleaned), json.dumps([]), sid],
        )
        await conn.execute(save_precision_questions_q.sql, *save_precision_questions_q.params)

    return _precision_question_message(cleaned[0], 0, len(cleaned), acc)


# ── gap questions ──────────────────────────────────────────────────────────────

async def _gap_start(acc: dict[str, Any]) -> dict[str, Any]:
    """Gap questions are now handled via the REST API (/gap-questions/start). Go straight to playbook."""
    return await _playbook_start(acc)


# ── playbook stream ────────────────────────────────────────────────────────────

async def _playbook_start(acc: dict[str, Any]) -> dict[str, Any]:
    """Start the playbook task stream and return a waiting message."""
    from app.task_stream.service import TaskStreamService
    from app.task_stream.registry import TASK_STREAM_REGISTRY

    onboarding_id = str(acc.get("onboardingSessionId") or "").strip()
    if not onboarding_id:
        return _complete_message(acc)

    task_type = "playbook/onboarding-generate"
    task_fn = TASK_STREAM_REGISTRY.get(task_type)
    if not task_fn:
        return _complete_message(acc)

    try:
        service = TaskStreamService()
        started = await service.start_task_stream(
            task_type=task_type,
            task_fn=task_fn,
            payload={"onboarding_id": onboarding_id},
            onboarding_id=onboarding_id,
            user_id=None,
            resume_if_exists=True,
        )
        stream_id = str(started.get("stream_id") or "")
    except Exception:
        return _complete_message(acc)

    return {
        "content": (
            "Generating your personalised playbook — this may take a moment. "
            "I'll show it here as soon as it's ready."
        ),
        "options": [],
        "allowCustomAnswer": False,
        "journeyStep": JOURNEY_STEP_PLAYBOOK,
        "journeySelections": {**acc, "streamId": stream_id},
        "kind": "final",
    }


# ── main step machine ──────────────────────────────────────────────────────────

async def next_step(
    current_step: str,
    selected_option: str,
    journey_selections: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Advance the journey by one step.
    `journey_selections` is the full accumulated context from the last assistant message.
    Returns the next assistant message payload, or None if step is unrecognised.
    """
    prev = dict(journey_selections or {})

    # ── Playbook retry ──────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_PLAYBOOK:
        # Any message on the playbook step restarts generation (handles retry after failure)
        return await _playbook_start(prev)

    # ── Q1: Outcome ─────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_OUTCOME:
        domains = get_domain_options(selected_option)
        if not domains:
            return None
        outcome_id = _OUTCOME_TEXT_TO_ID.get(selected_option, "")
        acc = {**prev, "outcome": selected_option, "outcomeId": outcome_id}
        return {
            "content": f"Great choice! Which area within **{selected_option}** do you want to focus on?",
            "options": domains,
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_DOMAIN,
            "journeySelections": acc,
        }

    # ── Q2: Domain ──────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_DOMAIN:
        tasks = get_task_options(selected_option)
        if not tasks:
            return None
        acc = {**prev, "domain": selected_option}
        return {
            "content": f"What specific task do you need help with in **{selected_option}**?",
            "options": tasks,
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_TASK,
            "journeySelections": acc,
        }

    # ── Q3: Task ────────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_TASK:
        acc = {**prev, "task": selected_option}
        return {
            "content": (
                f"Perfect! To give you the most personalised recommendations for **{selected_option}**, "
                "please share your **Website URL** or **Google Business Profile URL**.\n\n"
                "You can also click **Skip** and I'll provide general guidance instead."
            ),
            "options": ["Skip"],
            "allowCustomAnswer": True,
            "journeyStep": JOURNEY_STEP_URL,
            "journeySelections": acc,
        }

    # ── URL: Skip clicked ────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_URL:
        return start_scale_questions(url="", acc=prev)

    # ── Scale questions ──────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_SCALE:
        scale_index: int = int(prev.get("scaleIndex", 0))
        scale_answers: dict = dict(prev.get("scaleAnswers") or {})
        q = _SCALE_QUESTIONS[scale_index]
        q_id = q["id"]

        if q.get("multi_select"):
            if selected_option == "Done ✓":
                pass  # fall through to advance
            else:
                current_list = scale_answers.get(q_id, [])
                if not isinstance(current_list, list):
                    current_list = []
                if selected_option not in current_list:
                    current_list = current_list + [selected_option]
                scale_answers[q_id] = current_list
                acc = {**prev, "scaleAnswers": scale_answers, "scaleIndex": scale_index}
                return _build_scale_message(scale_index, acc)
        else:
            scale_answers[q_id] = selected_option

        next_index = scale_index + 1
        acc = {**prev, "scaleAnswers": scale_answers}

        if next_index < len(_SCALE_QUESTIONS):
            return _build_scale_message(next_index, acc)

        # All scale questions answered → create onboarding session + first RCA question
        from app.services.onboarding_question_service import generate_next_rca_question_for_onboarding

        sid = await _ensure_onboarding_session({**acc})
        acc["onboardingSessionId"] = sid

        rca = await generate_next_rca_question_for_onboarding(onboarding_id=sid, answer=None)
        if rca.get("status") == "question" and rca.get("question"):
            q_dict = rca["question"]
            if hasattr(q_dict, "__dict__"):
                q_dict = q_dict.__dict__
            return _diagnostic_message(q_dict, acc)

        # RCA returned complete immediately — move to precision
        return await _precision_start(acc)

    # ── Diagnostic (RCA) ─────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_DIAGNOSTIC:
        from app.services.onboarding_question_service import generate_next_rca_question_for_onboarding

        sid = str(prev.get("onboardingSessionId") or "").strip()
        if not sid:
            sid = await _ensure_onboarding_session(prev)
            prev = {**prev, "onboardingSessionId": sid}

        rca = await generate_next_rca_question_for_onboarding(onboarding_id=sid, answer=selected_option)

        if rca.get("status") == "question" and rca.get("question"):
            q_dict = rca["question"]
            if hasattr(q_dict, "__dict__"):
                q_dict = q_dict.__dict__
            return _diagnostic_message(q_dict, {**prev})

        # Diagnostic complete → start precision questions
        return await _precision_start({**prev})

    # ── Precision questions ──────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_PRECISION:
        from app.db import get_pool

        sid = str(prev.get("onboardingSessionId") or "").strip()
        precision_index = int(prev.get("precisionIndex", 0))

        pool = get_pool()
        async with pool.acquire() as conn:
            load_precision_state_q = build_query(
                PostgreSQLQuery.from_(onboarding_t)
                .select(
                    onboarding_t.id,
                    onboarding_t.precision_questions,
                    onboarding_t.precision_answers,
                    onboarding_t.questions_answers,
                )
                .where(onboarding_t.id == Parameter("%s")),
                [sid],
            )
            row = await conn.fetchrow(load_precision_state_q.sql, *load_precision_state_q.params)

        if not row:
            return await _gap_start(prev)

        precision_questions = _as_list(row.get("precision_questions"))
        precision_answers = _as_list(row.get("precision_answers"))

        answer_payload: dict[str, Any] = {
            "question_index": precision_index,
            "answer": selected_option,
        }
        if precision_index < len(precision_questions):
            pq = precision_questions[precision_index]
            answer_payload["question"] = str(pq.get("question") or "")
            answer_payload["type"] = str(pq.get("type") or "")
        precision_answers.append(answer_payload)

        qa_log = _as_list(row.get("questions_answers"))
        qa_log.append(
            {
                "question": answer_payload.get("question", f"Precision Question {precision_index + 1}"),
                "answer": selected_option,
                "question_type": "precision",
            }
        )

        next_idx = precision_index + 1
        all_answered = next_idx >= len(precision_questions)

        pool = get_pool()
        async with pool.acquire() as conn:
            if all_answered:
                persist_precision_complete_q = build_query(
                    PostgreSQLQuery.update(onboarding_t)
                    .set(onboarding_t.precision_answers, Parameter("%s"))
                    .set(onboarding_t.precision_status, "complete")
                    .set(onboarding_t.precision_completed_at, fn.Now())
                    .set(onboarding_t.questions_answers, Parameter("%s"))
                    .set(onboarding_t.updated_at, fn.Now())
                    .where(onboarding_t.id == Parameter("%s")),
                    [json.dumps(precision_answers), json.dumps(qa_log), sid],
                )
                await conn.execute(persist_precision_complete_q.sql, *persist_precision_complete_q.params)
            else:
                persist_precision_progress_q = build_query(
                    PostgreSQLQuery.update(onboarding_t)
                    .set(onboarding_t.precision_answers, Parameter("%s"))
                    .set(onboarding_t.precision_status, "awaiting_answers")
                    .set(onboarding_t.questions_answers, Parameter("%s"))
                    .set(onboarding_t.updated_at, fn.Now())
                    .where(onboarding_t.id == Parameter("%s")),
                    [json.dumps(precision_answers), json.dumps(qa_log), sid],
                )
                await conn.execute(persist_precision_progress_q.sql, *persist_precision_progress_q.params)

        if all_answered:
            return await _gap_start(prev)

        next_q = precision_questions[next_idx]
        return _precision_question_message(next_q, next_idx, len(precision_questions), prev)

    # ── Gap questions ────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_GAP:
        from app.db import get_pool

        gap_index = int(prev.get("gapIndex", 0))
        gap_questions: list[dict[str, Any]] = list(prev.get("gapQuestions") or [])
        gap_answers: dict[str, Any] = dict(prev.get("gapAnswers") or {})

        # Record the current answer
        if gap_index < len(gap_questions):
            current_q = gap_questions[gap_index]
            q_id = str(current_q.get("id") or str(gap_index))
            gap_answers[q_id] = {
                "label": str(current_q.get("label") or ""),
                "question": str(current_q.get("question") or ""),
                "answer": selected_option,
            }

        next_idx = gap_index + 1
        if next_idx < len(gap_questions):
            acc = {**prev, "gapIndex": next_idx, "gapAnswers": gap_answers}
            return _gap_question_message(gap_questions[next_idx], next_idx, gap_questions, acc)

        # All gap questions answered — format and persist
        formatted_lines = []
        for qa in gap_answers.values():
            label = str(qa.get("label") or "")
            answer = str(qa.get("answer") or "")
            formatted_lines.append(f"{label}: {answer}" if label else answer)
        formatted_answers = "\n".join(formatted_lines)

        sid = str(prev.get("onboardingSessionId") or "").strip()
        if sid:
            pool = get_pool()
            async with pool.acquire() as conn:
                persist_gap_answers_q = build_query(
                    PostgreSQLQuery.update(onboarding_t)
                    .set(onboarding_t.gap_answers, Parameter("%s"))
                    .set(onboarding_t.playbook_status, "ready")
                    .set(onboarding_t.updated_at, fn.Now())
                    .where(onboarding_t.id == Parameter("%s")),
                    [formatted_answers, sid],
                )
                await conn.execute(persist_gap_answers_q.sql, *persist_gap_answers_q.params)

        return await _playbook_start({**prev, "gapAnswers": gap_answers})

    return None


def _complete_message(acc: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": (
            "Great, I have everything I need! Let me now put together personalised "
            "recommendations for you. Feel free to ask me anything or describe what "
            "you'd like to explore further."
        ),
        "options": [],
        "allowCustomAnswer": True,
        "journeyStep": JOURNEY_STEP_COMPLETE,
        "journeySelections": acc,
        "kind": "final",
    }
