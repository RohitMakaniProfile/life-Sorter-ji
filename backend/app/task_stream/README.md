# Redis Task Stream (Reusable Background Task Streaming)

This module provides a reusable pattern to:

- start a background async Python task,
- persist incremental updates to Redis (durable),
- stream those updates to the frontend via SSE,
- re-attach after frontend refresh using `session_id` (onboarding) or `user_id`,
- ensure errors and final completion still reach late/reconnected clients.

## API Endpoints

- `POST /api/v1/task-stream/start/{task_type}`
  - Body:
    - `session_id?: string`
    - `user_id?: string`
    - `payload: object`
    - `resume_if_exists?: boolean` (default `true`)
  - Returns: `{ stream_id, status }`

- `GET /api/v1/task-stream/events/{stream_id}?cursor=...`
  - Attaches to a specific stream id.

- `GET /api/v1/task-stream/events/{task_type}/resume?session_id=...&user_id=...&cursor=...`
  - Re-attaches by actor identity (no need for `stream_id` if mapping exists in Redis).

## Backend: Register a New Task Type

Create an async task function that accepts:

```python
async def my_task(send, payload) -> dict:
    ...
    await send("stage", stage="running", label="Doing work...")
    await send("token", token="hello")
    return {"result": "final payload"}
```

Then register it:

```python
from app.task_stream.registry import register_task_stream

@register_task_stream("my-task-type")
async def my_task(send, payload):
    ...
    return {"result": "..."}
```

### Event Semantics

- Emit incremental updates using `await send("<event_type>", **fields)`.
- The wrapper will automatically emit a final `done` event when your task returns.
- If your task raises an exception, the wrapper emits an `error` event automatically.

## Frontend: Re-attach after refresh

Use `frontend/src/api/services/taskStream.ts`:

```ts
await startTaskStreamAndListen("my-task-type", {
  sessionId: sid,         // preferred (onboarding)
  userId: uid ?? null,   // optional
  payload: { ... },       // task-specific input
  callbacks: {
    onEvent: (e) => {},
    onDone: (e) => {},
    onError: (e) => {},
  },
});
```

This helper stores `stream_id` + last `cursor` in `localStorage`.
If the page refreshes and `stream_id` exists, it resumes from that cursor.
If not, it falls back to resume-by-actor (`session_id`/`user_id` mapping in Redis).

## Notes

- Implementation uses **Redis Streams** (durable log + cursor replay). Functionally it matches the "pub/sub streaming updates" UX, while also supporting re-attachment.
- Stream TTL/mapping TTL are controlled by:
  - `REDIS_TASKSTREAM_TTL_SECONDS`
  - `REDIS_TASKSTREAM_MAX_STREAM_LEN`

