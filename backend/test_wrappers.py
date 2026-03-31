"""
Quick smoke-test for both wrappers.
Run from backend/ directory:
    python3 test_wrappers.py
"""

import asyncio
import sys
import os

# Make sure app package is importable
sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────
# TEST 1 — OpenRouter wrapper: complete()
# ─────────────────────────────────────────────
async def test_openrouter_complete():
    print("\n[1] OpenRouter.complete() — blocking call")
    from app.wrapper.openrouter import OpenRouter
    from app.config import get_settings

    settings = get_settings()
    print(f"    model : {settings.OPENROUTER_MODEL}")

    # GLM-5 is a reasoning model — needs higher max_tokens so it has room to
    # respond after its internal thinking pass (same as rest of codebase uses 300+)
    llm = OpenRouter(temperature=0.5, max_tokens=400)
    text = await llm.complete(
        system="You are a helpful assistant.",
        user="What is 2 + 2? Answer with just the number.",
    )
    print(f"    reply : {repr(text)}")
    assert isinstance(text, str) and len(text) > 0, "Expected non-empty string"
    print("    ✅ PASS")


# ─────────────────────────────────────────────
# TEST 2 — OpenRouter wrapper: complete_full() — checks usage dict
# ─────────────────────────────────────────────
async def test_openrouter_complete_full():
    print("\n[2] OpenRouter.complete_full() — returns message + usage")
    from app.wrapper.openrouter import OpenRouter

    llm = OpenRouter(temperature=0.5, max_tokens=400)
    result = await llm.complete_full(
        system="You are a helpful assistant.",
        user="Name one color. Just say the word.",
    )
    print(f"    message : {repr(result.get('message'))}")
    print(f"    usage   : {result.get('usage')}")
    assert "message" in result, "Expected 'message' key"
    assert "usage" in result, "Expected 'usage' key"
    usage = result.get("usage") or {}
    assert isinstance(usage.get("prompt_tokens"), int), "prompt_tokens missing"
    assert isinstance(usage.get("completion_tokens"), int), "completion_tokens missing"
    assert isinstance(result["message"], str) and len(result["message"]) > 0
    print("    ✅ PASS")


# ─────────────────────────────────────────────
# TEST 3 — OpenRouter wrapper: stream() — tokens arrive one by one
# ─────────────────────────────────────────────
async def test_openrouter_stream():
    print("\n[3] OpenRouter.stream() — streaming tokens")
    from app.wrapper.openrouter import OpenRouter
    from app.config import get_settings

    settings = get_settings()
    llm = OpenRouter(
        model=settings.OPENROUTER_CLAUDE_MODEL,  # Claude for streaming test
        temperature=0.5,
        max_tokens=80,
    )

    tokens_received: list[str] = []

    async def on_token(token: str) -> None:
        tokens_received.append(token)
        print(f"    token> {repr(token)}")

    full_text = await llm.stream(
        system="You are a helpful assistant. Reply briefly.",
        user="Say hello in 3 words.",
        on_token=on_token,
    )
    print(f"    full_text      : {repr(full_text)}")
    print(f"    tokens_count   : {len(tokens_received)}")
    assert len(tokens_received) > 0, "Expected at least 1 token via callback"
    assert full_text == "".join(tokens_received), "full_text should equal joined tokens"
    print("    ✅ PASS")


# ─────────────────────────────────────────────
# TEST 4 — SSE wrapper: sse_response() — queue + generator logic
# ─────────────────────────────────────────────
async def test_sse_response():
    print("\n[4] sse_response() — SSE queue + generator (no HTTP server needed)")
    from app.wrapper.sse import sse_response
    from fastapi.responses import StreamingResponse
    import json

    events_emitted: list[dict] = []

    async def my_task(send) -> None:
        await send("stage", stage="running", label="Testing...")
        await send("token", token="Hello")
        await send("token", token=" World")
        await send("done", result="Hello World")

    response = await sse_response(my_task)

    assert isinstance(response, StreamingResponse), "Should return StreamingResponse"
    assert response.media_type == "text/event-stream", "Wrong media_type"
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"

    # Consume the generator to collect emitted events
    async for chunk in response.body_iterator:
        line = chunk.strip()
        if line.startswith("data: "):
            data = json.loads(line[6:])
            events_emitted.append(data)
            print(f"    event> {data}")

    assert len(events_emitted) == 4, f"Expected 4 events, got {len(events_emitted)}"
    assert events_emitted[0]["type"] == "stage"
    assert events_emitted[1]["type"] == "token" and events_emitted[1]["token"] == "Hello"
    assert events_emitted[2]["type"] == "token" and events_emitted[2]["token"] == " World"
    assert events_emitted[3]["type"] == "done"
    print("    ✅ PASS")


# ─────────────────────────────────────────────
# TEST 5 — SSE wrapper: error handling — exception auto-becomes error event
# ─────────────────────────────────────────────
async def test_sse_error_handling():
    print("\n[5] sse_response() — exception auto-converted to error event")
    from app.wrapper.sse import sse_response
    import json

    async def failing_task(send) -> None:
        await send("stage", stage="running", label="About to fail...")
        raise ValueError("Something went wrong in task")

    response = await sse_response(failing_task)

    events_emitted: list[dict] = []
    async for chunk in response.body_iterator:
        line = chunk.strip()
        if line.startswith("data: "):
            data = json.loads(line[6:])
            events_emitted.append(data)
            print(f"    event> {data}")

    assert events_emitted[-1]["type"] == "error", "Last event should be error"
    assert "Something went wrong" in events_emitted[-1]["message"]
    print("    ✅ PASS")


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────
async def main():
    print("=" * 55)
    print("  WRAPPER TESTS")
    print("=" * 55)

    passed = 0
    failed = 0

    tests = [
        ("OpenRouter.complete()", test_openrouter_complete),
        ("OpenRouter.complete_full()", test_openrouter_complete_full),
        ("OpenRouter.stream()", test_openrouter_stream),
        ("sse_response() — events", test_sse_response),
        ("sse_response() — error handling", test_sse_error_handling),
    ]

    for name, fn in tests:
        try:
            await fn()
            passed += 1
        except Exception as e:
            print(f"\n    ❌ FAIL — {name}")
            print(f"       {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 55)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 55)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
