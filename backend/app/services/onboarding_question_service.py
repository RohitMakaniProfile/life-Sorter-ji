from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException

from app.db import get_pool
from app.models.session import DynamicQuestion
from app.services.onboarding_crawl_service import generate_rca_questions


def _fallback_rca_questions(task: str) -> list[dict[str, Any]]:
    task_label = task.strip() or "this goal"
    return [
        {
            "question": f"What blocks {task_label} most right now?",
            "options": [
                "Not enough qualified leads",
                "Slow manual follow-up process",
                "Low trust / weak proof",
                "Something else / not sure",
            ],
        },
        {
            "question": "Where do prospects drop most often?",
            "options": [
                "Before first response",
                "During qualification call",
                "After proposal/demo stage",
                "Something else / not sure",
            ],
        },
        {
            "question": "What is your biggest execution constraint?",
            "options": [
                "No time / bandwidth",
                "No clear process",
                "No reliable tools/data",
                "Something else / not sure",
            ],
        },
    ]


def _normalize_rca_qa(rca_qa: Any) -> list[dict[str, Any]]:
    if isinstance(rca_qa, str):
        try:
            rca_qa = json.loads(rca_qa)
        except Exception:
            return []
    return rca_qa if isinstance(rca_qa, list) else []


def _normalize_questions_answers(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return value if isinstance(value, list) else []


def _apply_answer_to_last_pending(rca_qa: list[dict[str, Any]], answer: str) -> None:
    if not rca_qa:
        raise HTTPException(status_code=400, detail="No pending question found to answer")
    last = rca_qa[-1]
    if not isinstance(last, dict):
        raise HTTPException(status_code=400, detail="Pending question transcript is corrupted")
    if last.get("answer") is not None:
        raise HTTPException(status_code=400, detail="Last question already has an answer")
    last["answer"] = answer
    rca_qa[-1] = last


async def _persist_rca_qa(conn, *, onboarding_id: Any, rca_qa: list[dict[str, Any]]) -> None:
    await conn.execute(
        "UPDATE onboarding SET rca_qa = $1::jsonb WHERE id = $2",
        json.dumps(rca_qa),
        onboarding_id,
    )


async def generate_next_rca_question_for_onboarding(
    *,
    session_id: str,
    answer: Optional[str],
) -> dict[str, Any]:
    """
    Strictly DB-only RCA question service.

    Reads rca_qa from the onboarding row (pre-populated by the crawl task stream).
    - If answer provided: persist it against the last unanswered question.
    - Return the first remaining unanswered question, or status=complete if none left.
    - Never calls tree, LLM, or any generative fallback.
    """
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, rca_qa, questions_answers, outcome, domain, task, web_summary
            FROM onboarding
            WHERE session_id = $1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

        onboarding_id = row.get("id")
        rca_qa = _normalize_rca_qa(row.get("rca_qa"))
        questions_answers = _normalize_questions_answers(row.get("questions_answers"))
        outcome = str(row.get("outcome") or "").strip()
        domain = str(row.get("domain") or "").strip()
        task = str(row.get("task") or "").strip()
        web_summary = str(row.get("web_summary") or "").strip()

        # Safety fallback:
        # If crawl pre-generation hasn't persisted rca_qa yet, generate once here so
        # users don't get an incorrect "complete" and skip diagnostic entirely.
        if not rca_qa and answer is None and (outcome or domain or task):
            generated = await generate_rca_questions(
                outcome=outcome,
                domain=domain,
                task=task,
                web_summary=web_summary,
                session_id=session_id,
                max_questions=3,
            )
            if not generated:
                generated = _fallback_rca_questions(task)
            if generated:
                rca_qa = [
                    {
                        "question": str(q.get("question") or "").strip(),
                        "options": [str(o).strip() for o in (q.get("options") or []) if str(o).strip()],
                        "answer": None,
                    }
                    for q in generated
                    if str(q.get("question") or "").strip()
                ]
                if rca_qa:
                    await _persist_rca_qa(conn, onboarding_id=onboarding_id, rca_qa=rca_qa)

        if answer is not None:
            # All questions are pre-generated — apply answer to FIRST unanswered, not last.
            first_pending = next(
                (i for i, item in enumerate(rca_qa) if isinstance(item, dict) and item.get("answer") is None),
                None,
            )
            if first_pending is not None:
                rca_qa[first_pending]["answer"] = answer
                questions_answers.append({
                    "question": str(rca_qa[first_pending].get("question") or ""),
                    "answer": answer,
                    "question_type": "rca",
                })
                await _persist_rca_qa(conn, onboarding_id=onboarding_id, rca_qa=rca_qa)
                await conn.execute(
                    "UPDATE onboarding SET questions_answers = $1::jsonb, updated_at = NOW() WHERE id = $2",
                    json.dumps(questions_answers),
                    onboarding_id,
                )

        first_unanswered_idx = next(
            (i for i, item in enumerate(rca_qa) if isinstance(item, dict) and item.get("answer") is None),
            None,
        )

        if first_unanswered_idx is not None:
            item = rca_qa[first_unanswered_idx]
            return {
                "status": "question",
                "question": DynamicQuestion(
                    question=str(item.get("question") or ""),
                    options=list(item.get("options") or []),
                    allows_free_text=True,
                    section="rca",
                    section_label="Diagnostic",
                    insight="",
                ),
                "match_source": "pre_generated",
                "complete_summary": "",
            }

        return {
            "status": "complete",
            "question": None,
            "match_source": "pre_generated",
            "complete_summary": "Diagnostic complete.",
            "complete_handoff": "",
        }