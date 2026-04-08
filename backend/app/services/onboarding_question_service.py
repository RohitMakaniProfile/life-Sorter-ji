from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException

from app.db import get_pool
from app.models.session import DynamicQuestion


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


def _first_unanswered_index(rca_qa: list[dict[str, Any]]) -> int | None:
    return next(
        (i for i, item in enumerate(rca_qa) if isinstance(item, dict) and item.get("answer") is None),
        None,
    )


def _apply_answer_to_pending(rca_qa: list[dict[str, Any]], answer: str) -> int:
    if not rca_qa:
        raise HTTPException(status_code=400, detail="No pending question found to answer")
    idx = _first_unanswered_index(rca_qa)
    if idx is None:
        raise HTTPException(status_code=400, detail="No pending question found to answer")
    item = rca_qa[idx]
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail="Pending question transcript is corrupted")
    if item.get("answer") is not None:
        raise HTTPException(status_code=400, detail="Pending question already has an answer")
    item["answer"] = answer
    rca_qa[idx] = item
    return idx


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
    RCA question service with DB-first behavior.

    Reads rca_qa from onboarding row.
    - If no questions exist yet, generate and persist up to 3 using onboarding context.
    - If answer provided: persist it against the first unanswered question.
    - Return the first remaining unanswered question, or status=complete if none left.
    """
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, rca_qa, questions_answers, outcome, domain, task, web_summary, scale_answers
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
        scale_answers_raw = row.get("scale_answers")
        if isinstance(scale_answers_raw, str):
            try:
                parsed = json.loads(scale_answers_raw)
                scale_answers = parsed if isinstance(parsed, dict) else {}
            except Exception:
                scale_answers = {}
        else:
            scale_answers = scale_answers_raw if isinstance(scale_answers_raw, dict) else {}

        if not rca_qa:
            from app.services.onboarding_crawl_service import generate_rca_questions

            generated = await generate_rca_questions(
                outcome=str(row.get("outcome") or ""),
                domain=str(row.get("domain") or ""),
                task=str(row.get("task") or ""),
                web_summary=str(row.get("web_summary") or ""),
                scale_answers=scale_answers,
                max_questions=3,
            )
            rca_qa = [
                {
                    "question": str(q.get("question") or ""),
                    "options": list(q.get("options") or []),
                    "answer": None,
                }
                for q in generated
                if isinstance(q, dict) and str(q.get("question") or "").strip()
            ]
            if rca_qa:
                await _persist_rca_qa(conn, onboarding_id=onboarding_id, rca_qa=rca_qa)
            else:
                raise HTTPException(
                    status_code=503,
                    detail="Could not generate RCA questions yet. Try again shortly.",
                )

        if answer is not None:
            answered_idx = _apply_answer_to_pending(rca_qa, answer)
            try:
                answered = rca_qa[answered_idx] if 0 <= answered_idx < len(rca_qa) else {}
                if isinstance(answered, dict):
                    questions_answers.append({
                        "question": str(answered.get("question") or ""),
                        "answer": str(answered.get("answer") or ""),
                        "question_type": "rca",
                    })
            except Exception:
                pass
            await _persist_rca_qa(conn, onboarding_id=onboarding_id, rca_qa=rca_qa)
            await conn.execute(
                "UPDATE onboarding SET questions_answers = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(questions_answers),
                onboarding_id,
            )

        first_unanswered_idx = _first_unanswered_index(rca_qa)

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
