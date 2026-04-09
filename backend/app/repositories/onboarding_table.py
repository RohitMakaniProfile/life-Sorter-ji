from __future__ import annotations

from typing import Any

from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import BuiltQuery, build_query

onboarding_t = Table("onboarding")


def insert_onboarding_default_values_returning() -> str:
    return (
        "INSERT INTO onboarding DEFAULT VALUES "
        "RETURNING id, user_id, outcome, domain, task, "
        "website_url, gbp_url, scale_answers, business_profile, questions_answers, crawl_cache_key, "
        "onboarding_completed_at, created_at, updated_at"
    )


def update_onboarding_rca_qa_query(onboarding_id: Any, rca_qa_json: str) -> BuiltQuery:
    return build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.rca_qa, Parameter("%s"))
        .where(onboarding_t.id == Parameter("%s")),
        [rca_qa_json, onboarding_id],
    )


def update_onboarding_questions_answers_query(onboarding_id: Any, qa_json: str) -> BuiltQuery:
    return build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.questions_answers, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [qa_json, onboarding_id],
    )
