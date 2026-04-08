import { API_ROUTES } from '../routes';
import { apiRequest } from '../http';

export type TaskStreamEvent = {
  stream_id?: string;
  type: string;
  cursor?: string;
  // Task-specific fields (token/stage/done/error payload)
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

function safeLocalStorageRemove(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

function actorKey(taskType: string, onboardingId?: string | null, userId?: string | null): string {
  const s = (onboardingId ?? '').trim();
  const u = (userId ?? '').trim();
  if (u) return `${taskType}:user:${u}`;
  if (s) return `${taskType}:onboarding:${s}`;
  return `${taskType}:anon`;
}

function streamIdStorageKey(taskType: string, onboardingId?: string | null, userId?: string | null): string {
  return `${STORAGE_PREFIX}:stream_id:${actorKey(taskType, onboardingId, userId)}`;
}

function cursorStorageKey(streamId: string): string {
  return `${STORAGE_PREFIX}:cursor:${streamId}`;
}

async function listenTaskStreamUrl(
  url: string,
  callbacks: TaskStreamCallbacks,
  opts?: { streamIdKey?: string; onCleanup?: () => void },
): Promise<void> {
  const response = await apiRequest(url, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    // Clean up stored stream ID on 404 (stream not found / expired)
    if (response.status === 404) {
      opts?.onCleanup?.();
    }
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
          if (opts?.streamIdKey) safeLocalStorageSet(opts.streamIdKey, parsed.stream_id);
        }

        if (parsed.type === 'done') {
          // Clean up stored stream ID when task completes successfully
          opts?.onCleanup?.();
          callbacks.onDone?.(parsed);
        }
        if (parsed.type === 'error') {
          // Clean up stored stream ID when task errors out
          opts?.onCleanup?.();
          callbacks.onError?.(parsed);
        }
      } catch {
        // ignore malformed line
      }
    }
  }
}

export async function startTaskStreamAndListen(
  taskType: string,
  opts: {
    onboardingId?: string | null;
    userId?: string | null;
    payload?: Record<string, unknown>;
    resumeIfExists?: boolean;
    callbacks: TaskStreamCallbacks;
  },
): Promise<void> {
  const onboardingId = opts.onboardingId ?? null;
  const userId = opts.userId ?? null;
  const payload = opts.payload ?? {};
  const streamIdKey = streamIdStorageKey(taskType, onboardingId, userId);

  // Helper to clean up stored stream ID and cursor
  const cleanup = () => {
    const storedId = safeLocalStorageGet(streamIdKey);
    safeLocalStorageRemove(streamIdKey);
    if (storedId) {
      safeLocalStorageRemove(cursorStorageKey(storedId));
    }
  };

  // 1) If we already have a stream_id for this actor/taskType, resume directly.
  const storedStreamId = safeLocalStorageGet(streamIdKey);
  if (storedStreamId) {
    const cursor = safeLocalStorageGet(cursorStorageKey(storedStreamId));
    const url = `${API_ROUTES.taskStream.eventsByStreamId(storedStreamId)}${
      cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
    }`;
    await listenTaskStreamUrl(url, opts.callbacks, { streamIdKey, onCleanup: cleanup });
    return;
  }

  // 2) Start the background task (or get existing stream_id) from the backend.
  // We intentionally skip an explicit actor-resume probe here because:
  // - fresh actors naturally return 404 (noise in logs/devtools)
  // - start endpoint already supports resume_if_exists and reuses active streams
  const startRes = await apiRequest(API_ROUTES.taskStream.start(taskType), {
    method: 'POST',
    body: JSON.stringify({
      onboarding_id: onboardingId,
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
  safeLocalStorageSet(streamIdKey, streamId);

  const cursor = safeLocalStorageGet(cursorStorageKey(streamId));
  const url = `${API_ROUTES.taskStream.eventsByStreamId(streamId)}${
    cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  }`;
  await listenTaskStreamUrl(url, opts.callbacks, { streamIdKey, onCleanup: cleanup });
}

/**
 * Listen to a task stream directly by its stream ID.
 * Use this when the backend returns a taskStream metadata object with a streamId.
 */
export async function listenToTaskStreamById(
  streamId: string,
  callbacks: TaskStreamCallbacks,
  opts?: { taskType?: string; onboardingId?: string | null; userId?: string | null },
): Promise<void> {
  const taskType = opts?.taskType ?? 'unknown';
  const streamIdKey = streamIdStorageKey(taskType, opts?.onboardingId ?? null, opts?.userId ?? null);

  // Store the stream ID for potential resume
  safeLocalStorageSet(streamIdKey, streamId);

  const cleanup = () => {
    safeLocalStorageRemove(streamIdKey);
    safeLocalStorageRemove(cursorStorageKey(streamId));
  };

  const cursor = safeLocalStorageGet(cursorStorageKey(streamId));
  const url = `${API_ROUTES.taskStream.eventsByStreamId(streamId)}${
    cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  }`;

  await listenTaskStreamUrl(url, callbacks, { streamIdKey, onCleanup: cleanup });
}

export function getStoredTaskStreamId(taskType: string, opts: { onboardingId?: string | null; userId?: string | null }): string | null {
  return safeLocalStorageGet(streamIdStorageKey(taskType, opts.onboardingId ?? null, opts.userId ?? null));
}

export function storeTaskStreamId(taskType: string, streamId: string, opts: { onboardingId?: string | null; userId?: string | null }): void {
  safeLocalStorageSet(streamIdStorageKey(taskType, opts.onboardingId ?? null, opts.userId ?? null), streamId);
}

export function clearStoredTaskStreamId(taskType: string, opts: { onboardingId?: string | null; userId?: string | null }): void {
  const key = streamIdStorageKey(taskType, opts.onboardingId ?? null, opts.userId ?? null);
  const streamId = safeLocalStorageGet(key);
  safeLocalStorageRemove(key);
  if (streamId) {
    safeLocalStorageRemove(cursorStorageKey(streamId));
  }
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
    onboardingId?: string | null;
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
        onboardingId: opts.onboardingId,
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
