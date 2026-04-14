from __future__ import annotations

import json
from typing import Any

from app.config import SKILLS_ROOT
from .models import SkillManifest

_SKILLS: dict[str, SkillManifest] = {}


def _default_stage_labels() -> dict[str, str]:
    return {"thinking": "Thinking", "running": "Running", "done": "Done", "error": "Error"}


def load_skills() -> None:
    global _SKILLS
    skills: dict[str, SkillManifest] = {}

    if not SKILLS_ROOT.exists():
        print(f"[skills.loader] SKILLS_ROOT not found: {SKILLS_ROOT}")
    else:
        for child in sorted(SKILLS_ROOT.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "skill.json"
            if not manifest_path.exists():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[skills.loader] failed to parse {manifest_path}: {exc}")
                continue
            sid = str(raw.get("id", "")).strip()
            entry = str(raw.get("entry", "")).strip()
            if not sid or not entry:
                continue
            labels = raw.get("stageLabels") if isinstance(raw.get("stageLabels"), dict) else {}
            stage_labels = {**_default_stage_labels(), **{str(k): str(v) for k, v in labels.items()}}
            stages = (
                raw.get("stages") if isinstance(raw.get("stages"), list)
                else ["thinking", "running", "done"]
            )
            post_summary = (
                raw.get("postprocessSummary")
                if isinstance(raw.get("postprocessSummary"), dict)
                else {}
            )
            summary_mode = str(post_summary.get("mode") or "single").strip().lower()
            if summary_mode not in ("single", "multi_page"):
                summary_mode = "single"
            skills[sid] = SkillManifest(
                id=sid,
                name=str(raw.get("name", sid)),
                description=str(raw.get("description", "")),
                emoji=str(raw.get("emoji", "🛠️")),
                entry=entry,
                directory=child,
                stages=[str(s) for s in stages],
                stage_labels=stage_labels,
                input_schema=(
                    raw.get("inputSchema")
                    if isinstance(raw.get("inputSchema"), dict)
                    else None
                ),
                summary_mode=summary_mode,
                summary_array_path=(
                    str(post_summary.get("arrayPath")).strip()
                    if post_summary.get("arrayPath")
                    else None
                ),
                summary_content_field=str(post_summary.get("contentField") or "snapshot"),
                summary_url_field=str(post_summary.get("urlField") or "url"),
            )

    # Built-in platform-scout
    if "platform-scout" not in skills:
        skills["platform-scout"] = SkillManifest(
            id="platform-scout",
            name="Platform Scout",
            description="Infer business scope and build review + competitor queries",
            emoji="🧭",
            entry="",
            directory=SKILLS_ROOT,
            stages=["thinking", "running", "done"],
            stage_labels=_default_stage_labels(),
            input_schema={
                "type": "object",
                "properties": {
                    "businessUrl": {"type": "string"},
                    "regionHint": {"type": "string"},
                    "languageHint": {"type": "string"},
                },
            },
        )

    _SKILLS = skills
    print(f"[skills.loader] loaded {len(_SKILLS)} skill(s): {sorted(_SKILLS.keys())}")


def get_skill(skill_id: str) -> SkillManifest | None:
    return _SKILLS.get(skill_id)


def list_skills() -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "emoji": s.emoji,
            "description": s.description,
            "stages": s.stages,
            "stageLabels": s.stage_labels,
            "inputSchema": s.input_schema,
        }
        for s in _SKILLS.values()
    ]


def first_skill_id() -> str | None:
    for sid in _SKILLS:
        return sid
    return None

