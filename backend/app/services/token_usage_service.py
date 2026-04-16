"""
Token usage logging service for onboarding LLM calls.

Provides a centralized function to log token usage for all LLM calls during
the onboarding process (RCA questions, precision questions, gap questions,
playbook generation, etc.).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.db import get_pool
from app.repositories import (
    token_usage_repository as token_repo,
    onboarding_repository as onboarding_repo,
)
from app.utils.token_cost import _compute_cost_usd_inr

logger = structlog.get_logger()


async def log_onboarding_token_usage(
    *,
    onboarding_id: str,
    stage: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    provider: str = "openrouter",
    success: bool = True,
    error_msg: str = "",
    raw_output: str = "",
) -> None:
    """
    Log token usage for an LLM call during onboarding.

    Args:
        onboarding_id: The onboarding session ID
        stage: The stage/phase of the onboarding (e.g., "rca_questions", "precision_questions",
               "gap_questions", "playbook_agent1", "playbook_agent2", etc.)
        model: The model name (e.g., "anthropic/claude-sonnet-4-6")
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
        provider: The provider name (default: "openrouter")
        success: Whether the LLM call was successful
        error_msg: Error message if the call failed
        raw_output: Raw LLM output for debugging (only logged on error)
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            user_id = await onboarding_repo.find_user_id(conn, onboarding_id)
            message_id = f"{stage}-{onboarding_id}-{uuid.uuid4().hex[:8]}"
            encoded_model = f"{stage}||{provider}||{model}"
            cost_usd, cost_inr = _compute_cost_usd_inr(model, input_tokens, output_tokens)

            await token_repo.insert(
                conn,
                message_id=message_id,
                session_id=onboarding_id,
                conversation_id=None,
                user_id=str(user_id) if user_id else None,
                model_encoded=encoded_model,
                stage=stage,
                provider=provider,
                model_name=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                cost_inr=cost_inr,
                success=success,
                error_msg=error_msg or None,
                # Store full raw output in DB only on failure (for admin debugging)
                raw_output=raw_output if not success and raw_output else None,
            )

            log_data = {
                "onboarding_id": onboarding_id,
                "stage": stage,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "cost_inr": cost_inr,
                "success": success,
            }

            if not success and error_msg:
                log_data["error"] = error_msg
            if not success and raw_output:
                # Only preview in logs; full output is now stored in DB (token_usage.raw_output)
                log_data["raw_output_preview"] = raw_output[:500]
                log_data["raw_output_db_key"] = message_id

            logger.info("onboarding_token_usage logged", **log_data)

    except Exception as log_exc:
        logger.warning(
            "Failed to log onboarding token usage",
            error=str(log_exc),
            onboarding_id=onboarding_id,
            stage=stage,
        )


# Stage constants for consistency across services
STAGE_RCA_QUESTIONS = "rca_questions"
STAGE_PRECISION_QUESTIONS = "precision_questions"
STAGE_GAP_QUESTIONS = "gap_questions"
STAGE_WEBSITE_AUDIT = "website_audit"
STAGE_BUSINESS_PROFILE = "business_profile"
STAGE_PLAYBOOK_STREAM = "playbook_stream"

