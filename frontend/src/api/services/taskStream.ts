import { API_ROUTES } from '../routes';
import { apiRequest } from '../http';

export type TaskStreamEvent = {
  stream_id?: string;
  type: string;
  cursor?: string;
  // Task-specific fields (token/stage/done/error payload)
  [key: string]: unknown;
};

export type TaskStreamMeta = {
  stream_id: string;
  status?: string;
  task_type?: string;
  session_id?: string;
  user_id?: string;
  created_at?: string;
  last_cursor?: string;
  last_seq?: string;
  [key: string]: unknown;
};

type TaskStreamCallbacks = {
  onEvent?: (event: TaskStreamEvent) => void;
  onDone?: (event: TaskStreamEvent) => void;
  onError?: (event: TaskStreamEvent) => void;
};

const STORAGE_PREFIX = 'ikshan-taskstream';

function safeLocalStorageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeLocalStorageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore
  }
}

function actorKey(taskType: string, sessionId?: string | null, userId?: string | null): string {
  const s = (sessionId ?? '').trim();
  const u = (userId ?? '').trim();
  if (s) return `${taskType}:session:${s}`;
  if (u) return `${taskType}:user:${u}`;
  return `${taskType}:anon`;
}

function streamIdStorageKey(taskType: string, sessionId?: string | null, userId?: string | null): string {
  return `${STORAGE_PREFIX}:stream_id:${actorKey(taskType, sessionId, userId)}`;
}

function cursorStorageKey(streamId: string): string {
  return `${STORAGE_PREFIX}:cursor:${streamId}`;
}

async function listenTaskStreamUrl(url: string, callbacks: TaskStreamCallbacks, streamIdKey?: string): Promise<void> {
  const response = await apiRequest(url, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(`Task stream request failed: ${response.status}${detail ? ` — ${detail}` : ''}`);
  }

  if (!response.body) throw new Error('No response body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const parsed = JSON.parse(line.slice(6)) as TaskStreamEvent;
        callbacks.onEvent?.(parsed);

        if (parsed.cursor && parsed.stream_id) {
          safeLocalStorageSet(cursorStorageKey(parsed.stream_id), parsed.cursor);
          if (streamIdKey) safeLocalStorageSet(streamIdKey, parsed.stream_id);
        }

        if (parsed.type === 'done') callbacks.onDone?.(parsed);
        if (parsed.type === 'error') callbacks.onError?.(parsed);
      } catch {
        // ignore malformed line
      }
    }
  }
}

export async function startTaskStreamAndListen(
  taskType: string,
  opts: {
    sessionId?: string | null;
    userId?: string | null;
    payload?: Record<string, unknown>;
    resumeIfExists?: boolean;
    callbacks: TaskStreamCallbacks;
  },
): Promise<void> {
  const sessionId = opts.sessionId ?? null;
  const userId = opts.userId ?? null;
  const payload = opts.payload ?? {};

  // 1) If we already have a stream_id for this actor/taskType, resume directly.
  const storedStreamId = safeLocalStorageGet(streamIdStorageKey(taskType, sessionId, userId));
  if (storedStreamId) {
    const cursor = safeLocalStorageGet(cursorStorageKey(storedStreamId));
    const url = `${API_ROUTES.taskStream.eventsByStreamId(storedStreamId)}${
      cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
    }`;
    await listenTaskStreamUrl(url, opts.callbacks);
    return;
  }

  // 2) Fallback: try resuming by actor (covers refresh cases where localStorage was cleared).
  try {
    const params = new URLSearchParams();
    if (sessionId) params.set('session_id', sessionId);
    if (userId) params.set('user_id', userId);
    const resumeUrl =
      params.toString().length > 0
        ? `${API_ROUTES.taskStream.eventsByActor(taskType)}?${params.toString()}`
        : API_ROUTES.taskStream.eventsByActor(taskType);
    await listenTaskStreamUrl(resumeUrl, opts.callbacks, streamIdStorageKey(taskType, sessionId, userId));
    return;
  } catch (err: any) {
    const msg = String(err?.message || '');
    if (!msg.includes('Task stream request failed: 404')) throw err;
  }

  // 3) Otherwise start the background task (or get existing stream_id) from the backend.
  const startRes = await apiRequest(API_ROUTES.taskStream.start(taskType), {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      payload,
      resume_if_exists: opts.resumeIfExists ?? true,
    }),
  });
  if (!startRes.ok) {
    throw new Error(await startRes.text().catch(() => `Start failed: ${startRes.status}`));
  }
  const startJson = (await startRes.json()) as { stream_id: string };
  const streamId = startJson.stream_id;
  safeLocalStorageSet(streamIdStorageKey(taskType, sessionId, userId), streamId);

  const cursor = safeLocalStorageGet(cursorStorageKey(streamId));
  const url = `${API_ROUTES.taskStream.eventsByStreamId(streamId)}${
    cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  }`;
  await listenTaskStreamUrl(url, opts.callbacks);
}

export function getStoredTaskStreamId(taskType: string, opts: { sessionId?: string | null; userId?: string | null }): string | null {
  return safeLocalStorageGet(streamIdStorageKey(taskType, opts.sessionId ?? null, opts.userId ?? null));
}

export async function getTaskStreamStatus(streamId: string): Promise<TaskStreamMeta> {
  const res = await apiRequest(API_ROUTES.taskStream.statusByStreamId(streamId), { method: 'GET' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Task stream status failed: ${res.status}${text ? ` — ${text}` : ''}`);
  }
  return (await res.json()) as TaskStreamMeta;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => window.setTimeout(r, ms));
}

/**
 * Higher-level reusable runner for resumable background task streams.
 *
 * Use this when multiple tasks share the same pattern:
 * - start/resume a backend background task
 * - stream incremental updates to the UI
 * - auto-retry on network disconnects (without duplicating the task)
 *
 * Notes:
 * - This function never starts a "new" task if a stream already exists; it always resumes (`resumeIfExists=true`).
 * - If the stream finishes (done/error), the backend will replay the final event on re-attach.
 */
export async function runResumableTaskStream(
  taskType: string,
  opts: {
    sessionId?: string | null;
    userId?: string | null;
    payload?: Record<string, unknown>;
    callbacks: TaskStreamCallbacks;
    /** Retries when the stream disconnects before done/error. */
    maxRetries?: number;
    /** Optional hook to stop retries (e.g. component unmounted). */
    shouldStop?: () => boolean;
  },
): Promise<void> {
  const maxRetries = Math.max(0, Number(opts.maxRetries ?? 4));
  const shouldStop = opts.shouldStop ?? (() => false);

  let attempt = 0;
  let finished = false;
  let lastErr: any = null;

  const wrappedCallbacks: TaskStreamCallbacks = {
    onEvent: (e) => {
      if (shouldStop()) return;
      if (e?.type === 'done' || e?.type === 'error') finished = true;
      opts.callbacks.onEvent?.(e);
    },
    onDone: (e) => {
      if (shouldStop()) return;
      finished = true;
      opts.callbacks.onDone?.(e);
    },
    onError: (e) => {
      if (shouldStop()) return;
      finished = true;
      opts.callbacks.onError?.(e);
    },
  };

  while (attempt <= maxRetries && !shouldStop()) {
    try {
      await startTaskStreamAndListen(taskType, {
        sessionId: opts.sessionId,
        userId: opts.userId,
        payload: opts.payload,
        resumeIfExists: true,
        callbacks: wrappedCallbacks,
      });

      if (finished || shouldStop()) return;

      // Stream ended but no done/error event — treat as disconnect and retry.
      if (attempt >= maxRetries) return;
      attempt += 1;
      await sleep(Math.min(2500 * attempt, 8000));
      continue;
    } catch (err) {
      lastErr = err;
      if (attempt >= maxRetries || shouldStop()) break;
      attempt += 1;
      await sleep(Math.min(2500 * attempt, 8000));
    }
  }

  // If we exhausted retries and still didn't finish, surface an error event consistently.
  if (!finished && !shouldStop()) {
    opts.callbacks.onError?.({ type: 'error', message: String(lastErr?.message || lastErr || 'Stream failed') });
  }
}

