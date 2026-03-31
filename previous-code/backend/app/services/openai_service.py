"""
═══════════════════════════════════════════════════════════════
OPENAI SERVICE — Async wrapper for OpenAI Chat, TTS, Translation
═══════════════════════════════════════════════════════════════
Uses the official openai Python SDK with AsyncOpenAI client.
Provides:
  • chat_completion() — multi-persona chat with history
  • text_to_speech() — TTS using tts-1 model
  • translate_text() — LLM-based translation (English → Hindi)
"""

from __future__ import annotations

from typing import Optional

import structlog
from openai import AsyncOpenAI

from app.config import get_settings
from app.data.personas import build_system_prompt

logger = structlog.get_logger()


def _get_client() -> AsyncOpenAI:
    """Create an async OpenAI client using the active API key."""
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.openai_api_key_active)


# ── Chat Completion ────────────────────────────────────────────


async def chat_completion(
    message: str,
    persona: str = "default",
    context: Optional[dict] = None,
    conversation_history: Optional[list[dict]] = None,
) -> dict:
    """
    Generate a chat completion using OpenAI.

    Args:
        message: The user's message text.
        persona: One of 'product', 'contributor', 'assistant', 'default'.
        context: Optional context dict (generateBrief, domain, subDomain, etc.).
        conversation_history: List of prior {role, content} messages.

    Returns:
        dict with 'message' (str) and 'usage' (dict) keys.
    """
    settings = get_settings()
    client = _get_client()

    # Build system prompt from persona
    system_prompt = build_system_prompt(persona, context)

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    if conversation_history:
        messages.extend(conversation_history)

    # Add current user message
    messages.append({"role": "user", "content": message})

    # Tune parameters based on context
    is_generating_brief = context and context.get("generateBrief", False)
    is_redirecting = context and context.get("isRedirecting", False)

    temperature = 0.5 if is_generating_brief else 0.7
    max_tokens = 1500 if is_generating_brief else (150 if is_redirecting else 600)

    logger.info(
        "OpenAI chat request",
        persona=persona,
        messages_count=len(messages),
        is_brief=is_generating_brief,
        model=settings.OPENAI_MODEL_NAME,
    )

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL_NAME,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    ai_message = response.choices[0].message.content or (
        "Sorry, I could not generate a response."
    )

    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }

    logger.info("OpenAI chat response received", usage=usage)

    return {"message": ai_message, "usage": usage}


# ── Company Search GPT ─────────────────────────────────────────


async def company_search_gpt(
    search_prompt: str,
    query: str,
) -> str:
    """
    Use GPT for intelligent company search/scoring.

    Args:
        search_prompt: The full system prompt with company data.
        query: The user's search requirement.

    Returns:
        Raw GPT response string (JSON expected).
    """
    settings = get_settings()
    client = _get_client()

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": search_prompt},
            {"role": "user", "content": f'Find the best startups for: "{query}"'},
        ],
        temperature=0.2,
        max_tokens=500,
    )

    return response.choices[0].message.content or ""


async def company_explanation_gpt(
    explanation_prompt: str,
    query: str,
) -> str:
    """
    Generate a helpful explanation of matched companies.

    Args:
        explanation_prompt: System prompt with matched company details.
        query: The user's requirement text.

    Returns:
        Human-friendly explanation string.
    """
    settings = get_settings()
    client = _get_client()

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": explanation_prompt},
            {"role": "user", "content": f'Explain these tools for: "{query}"'},
        ],
        temperature=0.7,
        max_tokens=600,
    )

    return response.choices[0].message.content or ""


# ── Text-to-Speech ─────────────────────────────────────────────


async def text_to_speech(
    text: str,
    language: str = "english",
) -> bytes:
    """
    Convert text to speech using OpenAI TTS.

    If language is 'hindi', translates first, then generates audio.

    Args:
        text: The text to convert to speech.
        language: 'english' or 'hindi'.

    Returns:
        MP3 audio bytes.
    """
    client = _get_client()
    text_to_speak = text

    # Translate to Hindi if requested
    if language == "hindi":
        text_to_speak = await translate_text(text, target_language="hindi")

    speed = 0.9 if language == "hindi" else 0.95

    logger.info(
        "OpenAI TTS request",
        language=language,
        text_length=len(text_to_speak),
        speed=speed,
    )

    response = await client.audio.speech.create(
        model="tts-1",
        voice="nova",  # Warm and empathetic voice
        input=text_to_speak,
        speed=speed,
    )

    # Read the binary response
    audio_bytes = response.read()

    logger.info("OpenAI TTS response received", audio_size=len(audio_bytes))

    return audio_bytes


# ── Translation ────────────────────────────────────────────────


async def translate_text(
    text: str,
    target_language: str = "hindi",
) -> str:
    """
    Translate text using OpenAI chat completion.

    Args:
        text: The source text (English).
        target_language: Target language name.

    Returns:
        Translated text string.
    """
    client = _get_client()

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a translator. Translate the following English text to "
                    f"{target_language}. Keep the same warm, empathetic tone. "
                    f"Use simple {target_language} that is easy to understand. "
                    f"Translate naturally, not word-by-word. Keep any names as they are."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content or text
