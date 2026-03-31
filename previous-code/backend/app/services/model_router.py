"""
═══════════════════════════════════════════════════════════════
MODEL ROUTER — Tiered Model Selection for Speed + Cost
═══════════════════════════════════════════════════════════════
Routes LLM calls to the appropriate model tier:
  Tier 1 (fast):   GPT-4o-mini — for Agent 1, Agent 2, crawl summary, all RCA Qs,
                    task filter, precision questions
  Tier 2 (premium): GLM-5 via OpenRouter — for Agent 3, 4, 5 (playbook pipeline)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import get_settings


@dataclass
class ModelConfig:
    """Configuration for a single LLM call."""
    model: str
    provider: str          # "openrouter" or "openai"
    api_key: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout: float
    referer: str = "https://ikshan.ai"
    title: str = "Ikshan Engine"


# ── Task-to-tier mapping ──────────────────────────────────────

# Tasks routed to fast Tier 1 model (GPT-4o-mini: 2-4s vs GLM-5: 8-12s)
TIER1_TASKS = {
    "playbook_agent1",        # Context Parser — structured output, low creativity
    "playbook_agent2",        # ICP Analyst — structured output, speed priority
    "crawl_summary",          # Website summary — simple extraction
    "first_rca_question",     # First diagnostic Q — wide-form, fast start
    "rca_question",           # Subsequent RCA Qs — task-anchored prompt keeps quality
    "task_filter",            # Task alignment filter — categorization task
    "precision_questions",    # Precision questions — cross-reference task
}

# Everything else goes to Tier 2 (premium): Agent 3, Agent 4, Agent 5


def get_model_config(
    task: str,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> ModelConfig:
    """
    Return the model configuration for a given task.

    Args:
        task: Identifier like 'playbook_agent1', 'rca_question', 'playbook_agent3', etc.
        temperature: Override default temperature.
        max_tokens: Override default max_tokens.
        timeout: Override default timeout.
    """
    settings = get_settings()

    if task in TIER1_TASKS:
        # Tier 1: GPT-4o-mini via OpenAI
        return ModelConfig(
            model=settings.OPENAI_MODEL_NAME,    # gpt-4o-mini
            provider="openai",
            api_key=settings.openai_api_key_active,
            base_url="https://api.openai.com/v1/chat/completions",
            temperature=temperature if temperature is not None else 0.4,
            max_tokens=max_tokens or 3000,
            timeout=timeout or 60.0,
            title="Ikshan Tier1",
        )

    # Tier 2: GLM-5 via OpenRouter (default — premium)
    return ModelConfig(
        model=settings.OPENROUTER_MODEL,       # z-ai/glm-5
        provider="openrouter",
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1/chat/completions",
        temperature=temperature if temperature is not None else 0.7,
        max_tokens=max_tokens or 4000,
        timeout=timeout or 120.0,
        title="Ikshan Tier2",
    )


# ── Cost estimation (per 1K tokens, approximate INR) ──────────

COST_PER_1K = {
    "gpt-4o-mini": {"input": 0.10, "output": 0.30},
    "z-ai/glm-5": {"input": 1.50, "output": 2.00},
}


def estimate_cost_inr(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in INR for a single LLM call."""
    rates = COST_PER_1K.get(model, {"input": 1.0, "output": 1.5})
    return (prompt_tokens / 1000 * rates["input"]) + (completion_tokens / 1000 * rates["output"])
