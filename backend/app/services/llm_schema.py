"""
LLM Structured Output Schema Builder
=====================================

Type-safe builder for OpenRouter / OpenAI structured outputs — like PyPika
for query building, but for LLM response schemas.

Instead of hand-writing verbose JSON schema dicts:

    _RCA_RESPONSE_FORMAT = {
        "type": "json_schema",
        "json_schema": {
            "name": "rca_questions",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": { ... 40 lines ... },
                ...
            }
        }
    }

You define a Pydantic model and call .to_response_format():

    class RCAQuestions(LLMSchema):
        questions: list[RCAQuestion]

    response_format = RCAQuestions.to_response_format("rca_questions")

Works with any OpenRouter / OpenAI compatible API that supports
response_format.type = "json_schema".

Usage examples:
    # 1. Simple schema
    class Sentiment(LLMSchema):
        label: str
        score: float

    fmt = Sentiment.to_response_format("sentiment")

    # 2. Nested schema
    class Option(LLMSchema):
        text: str

    class Question(LLMSchema):
        question: str
        options: list[Option]

    class Quiz(LLMSchema):
        questions: list[Question]

    fmt = Quiz.to_response_format("quiz")

    # 3. Use with ai_helper
    result = await ai_helper.complete(
        model="anthropic/claude-sonnet-4-6",
        messages=[...],
        response_format=Quiz.to_response_format("quiz"),
    )
    parsed = Quiz.parse_response(result.get("message", ""))
"""

from __future__ import annotations

import json
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# Core schema builder
# ---------------------------------------------------------------------------


def _python_type_to_json_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema dict.

    Handles: str, int, float, bool, list[T], Optional[T],
    Literal["a","b"], nested LLMSchema subclasses, and
    Union types.
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Handle None / NoneType
    if annotation is type(None):
        return {"type": "null"}

    # Literal["a", "b", "c"] → enum
    if origin is Literal:
        return {"type": "string", "enum": list(args)}

    # Optional[X] is Union[X, None]
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            # Optional[X] → just use X's schema (structured outputs don't
            # support oneOf well; the field should be marked non-required
            # at the parent level if truly optional)
            return _python_type_to_json_schema(non_none[0])
        # General Union — rare, just use first type
        return _python_type_to_json_schema(non_none[0])

    # list[X] → {"type": "array", "items": ...}
    if origin is list:
        item_type = args[0] if args else Any
        items_schema = _python_type_to_json_schema(item_type)
        return {"type": "array", "items": items_schema}

    # dict[str, X] → {"type": "object"} (loose)
    if origin is dict:
        return {"type": "object"}

    # Nested LLMSchema subclass → recurse
    if isinstance(annotation, type) and issubclass(annotation, LLMSchema):
        return annotation.json_schema()

    # Primitives
    _PRIMITIVE_MAP: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }
    if annotation in _PRIMITIVE_MAP:
        return {"type": _PRIMITIVE_MAP[annotation]}

    # Fallback
    return {"type": "string"}


class LLMSchema(BaseModel):
    """
    Base class for LLM structured output schemas.

    Subclass this instead of plain BaseModel when you want to use a model
    as an OpenRouter structured output schema.

    class MyOutput(LLMSchema):
        name: str
        score: float

    # Generate OpenRouter response_format dict
    fmt = MyOutput.to_response_format("my_output")

    # Validate + parse raw LLM response string
    obj = MyOutput.parse_response(raw_json_string)
    """

    # Subclasses can set field descriptions via Field(..., description="...")
    # which will be included in the JSON schema.

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """Build a strict JSON Schema object for this model.

        Returns a dict like:
            {
                "type": "object",
                "properties": { ... },
                "required": [...],
                "additionalProperties": false
            }
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for field_name, field_info in cls.model_fields.items():
            annotation = field_info.annotation
            prop_schema = _python_type_to_json_schema(annotation)

            # Add description from Field(..., description="...")
            desc = field_info.description
            if desc:
                prop_schema["description"] = desc

            properties[field_name] = prop_schema

            # All fields are required in strict mode unless Optional
            if field_info.is_required():
                required.append(field_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    @classmethod
    def to_response_format(cls, name: str, *, strict: bool = True) -> dict[str, Any]:
        """Build the full OpenRouter / OpenAI response_format dict.

        Usage:
            result = await ai_helper.complete(
                ...,
                response_format=MySchema.to_response_format("my_schema"),
            )

        Produces:
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "<name>",
                    "strict": true,
                    "schema": { ... }
                }
            }
        """
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": strict,
                "schema": cls.json_schema(),
            },
        }

    @classmethod
    def parse_response(cls, raw: str) -> "LLMSchema":
        """Parse and validate a raw LLM JSON response string.

        Tries direct json.loads first. Falls back to _extract_json_value
        for responses that include stray text around the JSON.

        Raises ValidationError if the JSON doesn't match the schema.
        """
        text = (raw or "").strip()
        if not text:
            raise ValueError("Empty LLM response")

        # Try direct parse
        try:
            data = json.loads(text)
            return cls.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            pass

        # Fallback: extract JSON from noisy output
        from app.services.ai_helper import _extract_json_value
        extracted = _extract_json_value(text)
        data = json.loads(extracted)
        return cls.model_validate(data)

