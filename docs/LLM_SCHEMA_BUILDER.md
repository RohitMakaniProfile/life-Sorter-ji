# LLM Schema Builder (`llm_schema.py`)

> Define a Python class → get strict JSON output from any LLM. No hand-written JSON schemas.

**Location:** `backend/app/services/llm_schema.py`

---

## Why This Exists

When calling LLMs via OpenRouter, you can force the model to return **only** valid JSON matching an exact schema. But the raw API needs a verbose `response_format` dict — 40+ lines for even a simple shape.

This builder lets you define the shape as a Pydantic model (same syntax you already use for FastAPI request/response bodies) and auto-generates the OpenRouter `response_format` from it.

**Analogy:** PyPika is to SQL queries what LLMSchema is to LLM output schemas.

---

## Quick Start

### 1. Define your schema

```python
from pydantic import Field
from app.services.llm_schema import LLMSchema

class RCAQuestion(LLMSchema):
    question: str = Field(..., description="A diagnostic question")
    options: list[str] = Field(..., description="3-5 multiple-choice options")

class RCAQuestionsResponse(LLMSchema):
    questions: list[RCAQuestion] = Field(..., description="Exactly 3 RCA questions")
```

### 2. Pass to LLM call

```python
from app.services.ai_helper import ai_helper

result = await ai_helper.complete(
    model="anthropic/claude-sonnet-4-6",
    messages=[
        {"role": "system", "content": "Generate 3 diagnostic questions..."},
        {"role": "user", "content": json.dumps(context)},
    ],
    temperature=0.3,
    max_tokens=1024,
    response_format=RCAQuestionsResponse.to_response_format("rca_questions"),
    #                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #                This single line replaces 40+ lines of hand-written JSON schema
)
```

### 3. Parse the response

```python
raw = result.get("message", "")
parsed = RCAQuestionsResponse.parse_response(raw)

# parsed.questions → list of RCAQuestion objects
for q in parsed.questions:
    print(q.question)    # str — guaranteed
    print(q.options)     # list[str] — guaranteed
```

That's it. The LLM **cannot** return anything outside this schema.

---

## Supported Types

| Python type | JSON Schema output | Example |
|---|---|---|
| `str` | `{"type": "string"}` | `name: str` |
| `int` | `{"type": "integer"}` | `count: int` |
| `float` | `{"type": "number"}` | `score: float` |
| `bool` | `{"type": "boolean"}` | `is_active: bool` |
| `list[str]` | `{"type": "array", "items": {"type": "string"}}` | `tags: list[str]` |
| `list[MySchema]` | `{"type": "array", "items": {"type": "object", ...}}` | `items: list[LineItem]` |
| `MySchema` | `{"type": "object", "properties": {...}}` | `address: Address` |
| `Literal["a", "b"]` | `{"type": "string", "enum": ["a", "b"]}` | `type: Literal["buy", "sell"]` |
| `dict[str, Any]` | `{"type": "object"}` | `metadata: dict[str, Any]` |
| `Optional[str]` | `{"type": "string"}` (field becomes non-required) | `note: Optional[str]` |

### Field descriptions

Use Pydantic `Field(description=...)` to add descriptions. These are passed to the LLM as hints inside the schema:

```python
class Step(LLMSchema):
    action: str = Field(..., description="What the user should do")
    priority: Literal["high", "medium", "low"] = Field(..., description="Urgency level")
```

---

## Nesting

Schemas nest to any depth. Define inner objects as their own `LLMSchema` class:

```python
class Option(LLMSchema):
    label: str
    score: float

class Question(LLMSchema):
    text: str
    options: list[Option]          # ← nested list of objects

class Survey(LLMSchema):
    title: str
    questions: list[Question]      # ← 2 levels deep
```

Generated output:
```json
{
  "title": "Customer Feedback",
  "questions": [
    {
      "text": "How satisfied are you?",
      "options": [
        {"label": "Very", "score": 5.0},
        {"label": "Somewhat", "score": 3.0}
      ]
    }
  ]
}
```

---

## API Reference

### `LLMSchema` (base class)

Extend this instead of `BaseModel` for any schema you want to use with LLM structured outputs.

#### `.to_response_format(name: str, *, strict: bool = True) → dict`

Generates the full `response_format` dict for OpenRouter / OpenAI:

```python
MySchema.to_response_format("my_schema")
# Returns:
# {
#   "type": "json_schema",
#   "json_schema": {
#     "name": "my_schema",
#     "strict": true,
#     "schema": { "type": "object", "properties": {...}, ... }
#   }
# }
```

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Identifier for the schema (any string, sent to OpenRouter) |
| `strict` | `bool` | Default `True`. When true, the LLM is constrained to this exact schema. |

#### `.parse_response(raw: str) → LLMSchema`

Parses a raw LLM response string, validates it against the schema, and returns a typed object.

```python
parsed = MySchema.parse_response('{"name": "test", "score": 4.5}')
parsed.name   # "test"
parsed.score  # 4.5
```

- First tries `json.loads` directly (for clean structured output responses)
- Falls back to `_extract_json_value` (strips reasoning text / code fences if model leaked any)
- Raises `ValidationError` if the JSON doesn't match the schema
- Raises `ValueError` if the response is empty

#### `.json_schema() → dict`

Returns the raw JSON Schema object (without the OpenRouter wrapper). Useful for debugging:

```python
import json
print(json.dumps(MySchema.json_schema(), indent=2))
```

---

## Real-World Schemas

These are already defined or ready to use in the codebase:

### RCA Questions (`onboarding_crawl_service.py`)

```python
class RCAQuestion(LLMSchema):
    question: str = Field(..., description="A concrete diagnostic RCA question")
    options: list[str] = Field(..., description="3-5 short multiple-choice options")

class RCAQuestionsResponse(LLMSchema):
    questions: list[RCAQuestion] = Field(..., description="Exactly 3 diagnostic RCA questions")
```

### Precision Questions (for `claude_rca_service.py`)

```python
class PrecisionQuestion(LLMSchema):
    type: Literal["contradiction", "blind_spot", "unlock"] = Field(..., description="Question type")
    insight: str = Field(..., description="Short hypothesis being tested")
    question: str = Field(..., description="The actual question")
    options: list[str] = Field(..., description="Multiple-choice options")
    section_label: str = Field(..., description="Short UI label")

class PrecisionQuestionsResponse(LLMSchema):
    questions: list[PrecisionQuestion] = Field(..., description="Exactly 3 precision questions")
```

### Gap Questions (for `claude_rca_service.py`)

```python
class GapQuestion(LLMSchema):
    id: str = Field(..., description="Question ID like Q1, Q2")
    label: str = Field(..., description="Short label")
    question: str = Field(..., description="The specific question")
    why_matters: str = Field(..., description="What shifts in the playbook")
    options: list[str] = Field(..., description="4 options + free text option")

class GapQuestionsResponse(LLMSchema):
    questions: list[GapQuestion] = Field(..., description="0-3 gap questions")
```

---

## How It Works (Brief)

```
Python class              →  _python_type_to_json_schema()  →  JSON Schema dict  →  OpenRouter API
─────────────                ─────────────────────────────      ────────────────      ──────────────
class Q(LLMSchema):          Walks each field's type            {"type":"object",     response_format=
    question: str             annotation recursively.             "properties":{        {"type":"json_schema",
    options: list[str]        str → "string"                       "question":           "json_schema":{
                              list[str] → array of string           {"type":"string"},     "name":"...",
                              Literal[...] → enum                  "options":              "schema":{...}}}
                              LLMSchema → recurse                   {"type":"array",
                                                                     "items":{"type":"string"}}
                                                                 },
                                                                 "required":["question","options"],
                                                                 "additionalProperties":false}
```

1. **Define** — you write a Pydantic model extending `LLMSchema`
2. **Convert** — `.to_response_format()` walks each field, maps Python types to JSON Schema types, wraps in the OpenRouter envelope
3. **Send** — passed as `response_format` to the API. OpenRouter enforces the schema at generation time — the model physically cannot output non-conforming JSON
4. **Parse** — `.parse_response()` deserializes the response and validates it with Pydantic. If structured outputs worked, this is a simple `json.loads`. If not, it falls back to extracting JSON from noisy output.

---

## Adding a New Schema (Checklist)

1. **Define the schema** in the service file that uses it:
   ```python
   from app.services.llm_schema import LLMSchema
   from pydantic import Field
   
   class MyItem(LLMSchema):
       name: str = Field(..., description="Item name")
       score: float = Field(..., description="0-10 score")
   
   class MyResponse(LLMSchema):
       items: list[MyItem] = Field(..., description="Scored items")
   ```

2. **Pass to the LLM call:**
   ```python
   result = await _ai.complete(
       ...,
       response_format=MyResponse.to_response_format("my_response"),
   )
   ```

3. **Parse the response:**
   ```python
   parsed = MyResponse.parse_response(result.get("message", ""))
   for item in parsed.items:
       print(item.name, item.score)
   ```

No need to touch `llm_schema.py`, `openrouter_service.py`, or `ai_helper.py`. Just define → pass → parse.

