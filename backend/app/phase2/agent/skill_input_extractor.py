from __future__ import annotations

import json
import re
from typing import Any

from app.config import get_settings
from app.services.ai_helper import AIHelper
from .gemini_models import get_planner_models

_ai = AIHelper()

_SYSTEM_PROMPT = """You extract **structured arguments** for a skill from the user's message and any **prior skill outputs** appended below.

You may be given:
- An AGENT CONTEXT block describing the overall assistant behaviour.
- A SKILL ID and an expected JSON schema for its arguments.
- A USER MESSAGE that may end with a section "--- PRIOR SKILL OUTPUTS ..." containing rawData (JSON) and excerpts from skills already run (e.g. find-platform-handles with platforms.instagram URL).

Your job is to infer the **best concrete values** for each field in the schema, using the agent context, user message, **and PRIOR SKILL OUTPUTS when present**.

Guidelines:
- If PRIOR SKILL OUTPUTS contains an Instagram profile URL or handle for the task, use it for handle/postUrl fields — do not substitute the company website URL.
- If PRIOR SKILL OUTPUTS contains find-platform-handles rawData with platforms array, use the URL for the matching platform: youtube → channelUrl or videoUrl for youtube-sentiment; playstore URL → appId (package name from URL) for playstore-sentiment; instagram → handle/postUrl for instagram-sentiment.
- Think in terms of: skill X expects arguments about topic Y.
- Extract concrete entities (URLs, usernames, ids, search queries, free-text prompts, numeric limits, flags, etc.) from the user message, agent context, and prior outputs.
- Do not copy the entire user message into a single field unless the schema clearly expects one long prompt field.
- If a required field cannot be determined exactly, choose the most reasonable value from context.
- Output must conform to the schema; use optional fields only when appropriate.
- For number/integer fields, include a sensible number if the user did not specify one."""


def _parse_prior_platforms(message: str) -> dict[str, str]:
    try:
        idx = message.find('"platforms"')
        if idx == -1:
            return {}
        after = message[idx:]
        arr_start = after.find("[")
        if arr_start == -1:
            return {}
        depth = 1
        end = arr_start + 1
        while end < len(after) and depth > 0:
            if after[end] == "[":
                depth += 1
            elif after[end] == "]":
                depth -= 1
            end += 1
        if depth != 0:
            return {}
        arr_str = after[arr_start:end]
        platforms = json.loads(arr_str)
        out: dict[str, str] = {}
        for p in platforms:
            platform = str(p.get("platform") or "").lower()
            url = str(p.get("url") or "")
            handle = str(p.get("handle") or "")
            app_id = str(p.get("appId") or "")
            if platform == "youtube" and url:
                out["youtube"] = url
            if platform == "instagram":
                if url:
                    out["instagram"] = url
                if handle:
                    out["instagramHandle"] = handle
            if platform == "playstore" and url:
                out["playstore"] = url
                m = re.search(r"[?&]id=([^&]+)", url)
                if m:
                    out["playstoreAppId"] = m.group(1)
        return out
    except Exception:
        return {}


def _extract_json_from_raw(raw: str) -> str:
    fenced = re.search(r"```json([\s\S]*?)```", raw, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    generic = re.search(r"```([\s\S]*?)```", raw)
    if generic:
        return generic.group(1).strip()
    return raw.strip()


def _is_retryable(err_msg: str) -> bool:
    lower = err_msg.lower()
    return any(k in lower for k in ["503", "429", "unavailable", "resource_exhausted", "overloaded", "high demand"])


def _is_404(err_msg: str) -> bool:
    lower = err_msg.lower()
    return any(k in lower for k in ["404", "not_found", '"code":404'])


async def extract_skill_args(
    skill_id: str,
    message: str,
    input_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not input_schema or not isinstance(input_schema.get("properties"), dict):
        return None

    if not (get_settings().OPENROUTER_API_KEY or "").strip():
        return None

    try:
        props: dict[str, Any] = input_schema.get("properties", {})
        fields_desc = "\n".join(
            f"- {key} ({prop.get('type', 'string')}"
            + (", optional" if prop.get("optional") else "")
            + ")"
            + (f": {prop['description']}" if prop.get("description") else "")
            for key, prop in props.items()
        )

        prompt = "\n".join([
            _SYSTEM_PROMPT,
            "",
            f"SKILL ID: {skill_id}",
            "EXPECTED FIELDS (JSON schema-like):",
            fields_desc or "(none)",
            "",
            "USER MESSAGE (may include a trailing PRIOR SKILL OUTPUTS block from earlier skills):",
            message,
        ])
        model_ids = get_planner_models()

        parsed: dict[str, Any] | None = None
        last_err: Exception | None = None
        for model_id in model_ids:
            try:
                parsed = await _ai.complete_json_with_candidates(
                    model_candidates=AIHelper.model_candidates(
                        model_id,
                        prefix_env="OPENROUTER_MODEL_PREFIX",
                    ),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=700,
                )
                last_err = None
                break
            except Exception as e:
                err_msg = str(e)
                last_err = e
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if (status_code == 404 or _is_404(err_msg)) and model_ids.index(model_id) < len(model_ids) - 1:
                    continue
                if status_code in (429, 503) or _is_retryable(err_msg):
                    if model_ids.index(model_id) < len(model_ids) - 1:
                        continue
                break

        if last_err or not parsed:
            return None

        prior = _parse_prior_platforms(message)
        if prior:
            if skill_id == "youtube-sentiment" and prior.get("youtube"):
                if not parsed.get("channelUrl") and not parsed.get("videoUrl"):
                    parsed["channelUrl"] = prior["youtube"]
            if skill_id == "instagram-sentiment" and prior.get("instagram"):
                if not parsed.get("handle") and not parsed.get("postUrl"):
                    parsed["handle"] = prior.get("instagramHandle") or prior["instagram"]
                if not parsed.get("postUrl"):
                    parsed["postUrl"] = prior["instagram"]
            if skill_id == "playstore-sentiment" and prior.get("playstore"):
                if not parsed.get("appId") and prior.get("playstoreAppId"):
                    parsed["appId"] = prior["playstoreAppId"]

        if skill_id == "playstore-sentiment":
            parsed["distribution"] = "1:2,2:3,3:5,4:5,5:2"
            if not parsed.get("country"):
                parsed["country"] = "in"
        if skill_id == "scrape-playwright":
            parsed["deep"] = True
            parsed["parallel"] = True
            parsed["maxPages"] = 9999
            parsed["maxDepth"] = 10

        for key, prop in props.items():
            if parsed.get(key) is not None:
                continue
            t = prop.get("type", "string")
            optional = prop.get("optional") is True
            if prop.get("default") is not None:
                parsed[key] = prop["default"]
            elif t in ("number", "integer"):
                if key == "maxDepth":
                    parsed[key] = 5
                elif key == "maxPages":
                    parsed[key] = 10
                elif key == "maxVideos":
                    parsed[key] = 5
                else:
                    parsed[key] = 10
            elif t == "string" and optional:
                parsed[key] = ""

        return parsed

    except Exception as e:
        err_msg = str(e)
        if _is_404(err_msg):
            import warnings
            warnings.warn(f"[skill_input_extractor] Gemini model not available (404) for {skill_id}.")
        else:
            import warnings
            warnings.warn(f"[skill_input_extractor] {skill_id} extraction failed: {err_msg}")
        return None
