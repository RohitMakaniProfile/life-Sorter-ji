"""
SSE (Server-Sent Events) streaming response wrapper.

Eliminates the repeated asyncio.Queue + StreamingResponse boilerplate
that every streaming endpoint needs.

Usage in a FastAPI router:
    from app.wrapper.sse import sse_response, SseSender

    @router.post("/my-stream")
    async def my_endpoint(body: MyBody):

        async def task(send: SseSender) -> None:
            await send("stage", stage="running", label="Processing...")

            # do work, call LLM, etc.
            result = await some_llm_call(on_token=lambda t: send("token", token=t))

            await send("done", result=result)
            # Note: errors are caught automatically — no need for try/except here

        return await sse_response(task)

Event format emitted (matches frontend playbookGenerateStream parser):
    data: {"type": "stage", "stage": "...", "label": "..."}\n\n
    data: {"type": "token", "token": "..."}\n\n
    data: {"type": "done",  ...any fields...}\n\n
    data: {"type": "error", "message": "..."}\n\n
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from fastapi.responses import StreamingResponse

# Type alias — the `send` helper passed into your task function
SseSender = Callable[..., Awaitable[None]]

_DEFAULT_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",   # tells nginx: don't buffer SSE
    "Connection": "keep-alive",
}


async def sse_response(
    task: Callable[[SseSender], Awaitable[None]],
    extra_headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """
    Build a StreamingResponse that runs `task` in the background and
    forwards its events to the client as SSE.

    Args:
        task:          Async function that receives a `send` helper.
                       Call `await send("type", key=value, ...)` to emit events.
        extra_headers: Additional HTTP headers merged into the SSE defaults.

    Returns:
        A FastAPI StreamingResponse with media_type="text/event-stream".

    How it works:
        1. An asyncio.Queue bridges the push-based `send` callback and
           the pull-based async generator that FastAPI reads from.
        2. `task` runs as a background asyncio Task — it fills the queue.
        3. `event_generator` drains the queue and yields SSE lines.
        4. A None sentinel in the queue signals "stream finished".
        5. Any exception in `task` is caught and emitted as an error event.

    Example:
        async def generate(send: SseSender) -> None:
            await send("stage", stage="generating", label="Writing...")

            async def on_token(token: str) -> None:
                await send("token", token=token)

            text = await llm.stream(system=PROMPT, user=ctx, on_token=on_token)
            await send("done", text=text)

        return await sse_response(generate)
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(event_type: str, **data: Any) -> None:
        """Encode an event dict and push it into the queue."""
        payload = json.dumps({"type": event_type, **data})
        await queue.put(f"data: {payload}\n\n")

    async def _run() -> None:
        try:
            await task(send)
        except Exception as exc:
            await send("error", message=str(exc))
        finally:
            await queue.put(None)  # sentinel — tells generator to stop

    async def event_generator():
        asyncio.create_task(_run())   # fire task in background
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    headers = {**_DEFAULT_HEADERS, **(extra_headers or {})}

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )
