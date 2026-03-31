# Backend Wrappers — Usage Guide

Do wrappers hain:

| File | Kaam |
|---|---|
| `wrapper/openrouter.py` | OpenRouter LLM calls — boilerplate khatam |
| `wrapper/sse.py` | SSE streaming endpoints — Queue + StreamingResponse khatam |

---

## 1. `OpenRouter` — LLM Call Wrapper

### Import

```python
from app.wrapper.openrouter import OpenRouter
from app.config import get_settings
```

### Instance banana

```python
# Default model = OPENROUTER_MODEL (z-ai/glm-5) — 90% cases
llm = OpenRouter()

# Custom temperature / tokens
llm = OpenRouter(temperature=0.3, max_tokens=500)

# Claude model (playbook / high-quality output)
llm = OpenRouter(
    model=get_settings().OPENROUTER_CLAUDE_MODEL,
    temperature=0.7,
    max_tokens=10000,
)
```

> **Rule:** Ek baar banao, baar baar reuse karo. Module-level ya function start mein banao.

---

### Methods — Kab kya use karo

```
complete()              → sirf text chahiye
complete_full()         → text + usage (logging ke liye)
stream()                → SSE / token-by-token
complete_messages()     → multi-turn / custom history
complete_messages_full()→ multi-turn + usage
stream_messages()       → multi-turn + streaming
```

---

### `complete()` — Simple blocking call

**Kab:** Sirf answer chahiye, usage log nahi karna.

```python
llm = OpenRouter(temperature=0.5, max_tokens=300)

text = await llm.complete(
    system="You are a JSON extractor. Return only valid JSON.",
    user=f"Extract key info from: {raw_text}",
)

parsed = json.loads(text)
```

---

### `complete_full()` — Text + Usage (logging ke liye)

**Kab:** `session_store.add_llm_call_log()` call karna ho — token counts chahiye.

```python
llm = OpenRouter(temperature=0.5, max_tokens=1500)

result = await llm.complete_full(
    system=MY_SYSTEM_PROMPT,
    user=user_context,
)

text  = result["message"]
usage = result["usage"]
# usage = {"prompt_tokens": 120, "completion_tokens": 340, "total_tokens": 460}

session_store.add_llm_call_log(
    session_id=session_id,
    service="openrouter",
    model=llm.model,
    purpose="my_agent",
    system_prompt="[MY_SYSTEM_PROMPT]",
    user_message=user_context[:500],
    temperature=llm.temperature,
    max_tokens=llm.max_tokens,
    latency_ms=latency_ms,
    token_usage=usage,
)
```

---

### `stream()` — Token-by-token streaming

**Kab:** SSE endpoint mein playbook / long content generate karna ho.

```python
llm = OpenRouter(
    model=get_settings().OPENROUTER_CLAUDE_MODEL,
    temperature=0.7,
    max_tokens=10000,
)

async def on_token(token: str) -> None:
    await send("token", token=token)   # SSE wrapper ke send() se connect karo

full_text = await llm.stream(
    system=AGENT_PROMPT,
    user=input_context,
    on_token=on_token,
)
# full_text = complete generated text (sab tokens joined)
```

---

### `complete_messages()` — Multi-turn / Custom history

**Kab:** Conversation history bhejni ho ya system ke alawa aur roles chahiye.

```python
llm = OpenRouter(temperature=0.7, max_tokens=2000)

text = await llm.complete_messages([
    {"role": "system",    "content": "You are a helpful assistant."},
    {"role": "user",      "content": "My business sells handmade candles."},
    {"role": "assistant", "content": "Great! What's your main challenge?"},
    {"role": "user",      "content": "I can't get repeat customers."},
])
```

---

### `stream_messages()` — Multi-turn + Streaming

```python
full_text = await llm.stream_messages(
    messages=[
        {"role": "system", "content": PROMPT},
        {"role": "user",   "content": ctx},
    ],
    on_token=on_token,
)
```

---

### Model selection cheat sheet

```python
# GLM — fast, cheap, most calls
llm = OpenRouter()
llm = OpenRouter(temperature=0.3, max_tokens=300)

# Claude — high quality (playbook, RCA, precision Q)
llm = OpenRouter(model=get_settings().OPENROUTER_CLAUDE_MODEL, max_tokens=10000)

# Claude — low temp for structured/JSON output
llm = OpenRouter(model=get_settings().OPENROUTER_CLAUDE_MODEL, temperature=0.2, max_tokens=2000)
```

---

## 2. `sse_response()` — SSE Streaming Wrapper

### Import

```python
from app.wrapper.sse import sse_response, SseSender
```

### Basic usage

```python
@router.post("/my-stream")
async def my_endpoint(request: Request, body: MyRequest = Body(...)):

    async def task(send: SseSender) -> None:
        await send("stage", stage="running", label="Processing...")

        # kaam karo...
        result = "final output"

        await send("done", result=result)

    return await sse_response(task)
```

**Note:** `try/except` ki zaroorat nahi — wrapper automatically exception ko `error` event mein convert karta hai.

---

### `send()` function — Event types

```python
# Stage update (frontend ko progress dikhao)
await send("stage", stage="generating", label="Writing your playbook...")

# Token (LLM streaming)
await send("token", token="Hello")

# Done (final result ke saath)
await send("done", playbook="...", website_audit="...", icp_card="...")

# Error (automatically called by wrapper on exception)
# await send("error", message="Something went wrong")  ← khud nahi banana
```

**Rule:** `send()` mein pehla argument `type` hota hai. Baaki sab `**kwargs` hain — jo bhi daaloge frontend ko milega.

---

### OpenRouter wrapper ke saath — Full SSE + LLM example

```python
from app.wrapper.openrouter import OpenRouter
from app.wrapper.sse import sse_response, SseSender
from app.config import get_settings

llm = OpenRouter(
    model=get_settings().OPENROUTER_CLAUDE_MODEL,
    temperature=0.7,
    max_tokens=10000,
)

@router.post("/generate-stream")
async def generate_stream(request: Request, body: MyRequest = Body(...)):

    async def task(send: SseSender) -> None:
        # Stage 1
        await send("stage", stage="preparing", label="Preparing context...")
        context = build_context(body.session_id)

        # Stage 2 — streaming LLM
        await send("stage", stage="generating", label="Writing...")

        async def on_token(token: str) -> None:
            await send("token", token=token)

        full_text = await llm.stream(
            system=MY_SYSTEM_PROMPT,
            user=context,
            on_token=on_token,
        )

        # Done
        await send("done", output=full_text, session_id=body.session_id)

    return await sse_response(task)
```

---

### Extra headers chahiye toh

```python
return await sse_response(
    task,
    extra_headers={"Access-Control-Allow-Origin": "*"},
)
```

---

### Frontend pe kaise parse hoga

Frontend `playbookGenerateStream()` in events ko already handle karta hai:

```typescript
// core.ts mein already hai:
if (data.type === 'token') callbacks.onToken?.(data.token);
if (data.type === 'stage') callbacks.onStage?.(data.stage, data.label);
if (data.type === 'done')  callbacks.onDone?.(data);
if (data.type === 'error') callbacks.onError?.(data.message);
```

---

## 3. Dono saath — Real-world pattern

**Naya SSE endpoint banana ho toh exactly yeh template copy karo:**

```python
from app.wrapper.openrouter import OpenRouter
from app.wrapper.sse import sse_response, SseSender
from app.config import get_settings

# Module level — ek baar initialize
_llm = OpenRouter(
    model=get_settings().OPENROUTER_CLAUDE_MODEL,
    temperature=0.7,
    max_tokens=8000,
)

@router.post("/my-new-stream")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def my_new_stream(request: Request, body: MyRequest = Body(...)):
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def task(send: SseSender) -> None:
        await send("stage", stage="thinking", label="Analyzing...")

        # Step 1 — blocking call (fast)
        context = await _llm.complete(
            system="Extract key info. Return JSON.",
            user=str(session.business_profile),
        )

        await send("stage", stage="generating", label="Generating...")

        # Step 2 — streaming call (words appear live)
        async def on_token(token: str) -> None:
            await send("token", token=token)

        output = await _llm.stream(
            system=MY_MAIN_PROMPT,
            user=context,
            on_token=on_token,
        )

        # Save to session
        session_store.update_session(session)

        await send("done", output=output, session_id=body.session_id)

    return await sse_response(task)
```

---

## 4. Kya nahi karna (common mistakes)

```python
# ❌ Galat — openrouter_service directly call karna
result = await openrouter_service.chat_completion(
    model=settings.OPENROUTER_MODEL,
    messages=[{"role": "system", ...}, {"role": "user", ...}],
    temperature=0.7,
    max_tokens=1500,
)
text = result["message"]

# ✅ Sahi — wrapper use karo
llm = OpenRouter(temperature=0.7, max_tokens=1500)
text = await llm.complete(system=PROMPT, user=context)
```

```python
# ❌ Galat — SSE ke liye manually Queue banana
queue: asyncio.Queue[str | None] = asyncio.Queue()
async def _send(obj): await queue.put(f"data: {json.dumps(obj)}\n\n")
async def _run():
    try: ...
    except Exception as exc: await _send({"type": "error", "message": str(exc)})
    finally: await queue.put(None)
async def event_generator():
    asyncio.create_task(_run())
    while True:
        item = await queue.get()
        if item is None: break
        yield item
return StreamingResponse(event_generator(), media_type="text/event-stream", ...)

# ✅ Sahi — sse_response use karo
async def task(send): ...
return await sse_response(task)
```

---

## 5. Quick Reference

```python
# OpenRouter
from app.wrapper.openrouter import OpenRouter

llm = OpenRouter()                          # GLM, temp=0.7, max=4096
llm = OpenRouter(temperature=0.3)          # GLM, temp=0.3
llm = OpenRouter(model="anthropic/...")    # Claude

await llm.complete(system, user)           # → str
await llm.complete_full(system, user)      # → {"message": str, "usage": dict}
await llm.stream(system, user, on_token)   # → str (full text)
await llm.complete_messages([...])         # → str
await llm.complete_messages_full([...])    # → {"message": str, "usage": dict}
await llm.stream_messages([...], on_token) # → str (full text)

# SSE
from app.wrapper.sse import sse_response, SseSender

async def task(send: SseSender) -> None:
    await send("stage", stage="x", label="y")
    await send("token", token="hello")
    await send("done", result="...")

return await sse_response(task)
return await sse_response(task, extra_headers={"X-Custom": "value"})
```
