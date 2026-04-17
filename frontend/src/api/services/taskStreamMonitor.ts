type ActorKey = string;

export type TaskStreamMonitorRow = {
  taskType: string;
  streamId: string;
  status: 'running' | 'done' | 'error' | 'cancelled' | 'unknown';
  lastEventType?: string;
  lastUpdatedAtMs: number;
  lastSeq?: number;
  lastCursor?: string;
  stage?: string;
  label?: string;
  errorMessage?: string;
};

type Snapshot = Record<ActorKey, Record<string, TaskStreamMonitorRow>>;

let snapshot: Snapshot = {};
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

export function makeActorKey(opts: { onboardingId?: string | null; userId?: string | null }): ActorKey {
  const sid = opts.onboardingId ?? null;
  const uid = opts.userId ?? null;
  return `oid:${sid || ''}|uid:${uid || ''}`;
}

export function subscribeTaskStreamMonitor(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getTaskStreamMonitorSnapshot(): Snapshot {
  return snapshot;
}

function upsertRow(actorKey: ActorKey, taskType: string, patch: Partial<TaskStreamMonitorRow>) {
  const now = Date.now();
  const prevActor = snapshot[actorKey] || {};
  const prev = prevActor[taskType];
  const next: TaskStreamMonitorRow = {
    taskType,
    streamId: patch.streamId || prev?.streamId || '',
    status: patch.status || prev?.status || 'unknown',
    lastEventType: patch.lastEventType ?? prev?.lastEventType,
    lastUpdatedAtMs: now,
    lastSeq: patch.lastSeq ?? prev?.lastSeq,
    lastCursor: patch.lastCursor ?? prev?.lastCursor,
    stage: patch.stage ?? prev?.stage,
    label: patch.label ?? prev?.label,
    errorMessage: patch.errorMessage ?? prev?.errorMessage,
  };
  snapshot = { ...snapshot, [actorKey]: { ...prevActor, [taskType]: next } };
  emit();
}

export function monitorTaskStreamStart(opts: {
  taskType: string;
  streamId: string;
  onboardingId?: string | null;
  userId?: string | null;
}) {
  upsertRow(makeActorKey(opts), opts.taskType, { streamId: opts.streamId, status: 'running', lastEventType: 'start' });
}

export function monitorTaskStreamEvent(opts: {
  taskType: string;
  streamId?: string;
  onboardingId?: string | null;
  userId?: string | null;
  event: any;
}) {
  const e = opts.event || {};
  upsertRow(makeActorKey(opts), opts.taskType, {
    streamId: opts.streamId || e.stream_id,
    status: 'running',
    lastEventType: String(e.type || 'event'),
    lastSeq: e.seq ? Number(e.seq) : undefined,
    lastCursor: e.cursor ? String(e.cursor) : undefined,
    stage: e.stage ? String(e.stage) : undefined,
    label: e.label ? String(e.label) : undefined,
  });
}

export function monitorTaskStreamDone(opts: {
  taskType: string;
  streamId?: string;
  onboardingId?: string | null;
  userId?: string | null;
  event?: any;
}) {
  const e = opts.event || {};
  upsertRow(makeActorKey(opts), opts.taskType, {
    streamId: opts.streamId || e.stream_id,
    status: 'done',
    lastEventType: 'done',
    lastSeq: e.seq ? Number(e.seq) : undefined,
    lastCursor: e.cursor ? String(e.cursor) : undefined,
  });
}

/** Extract a human-readable error string from any shape of error object/value */
export function extractErrorMessage(raw: unknown): string {
  if (!raw) return 'Unknown error';
  if (typeof raw === 'string') return raw || 'Unknown error';

  if (raw instanceof Error) return raw.message || 'Unknown error';

  if (typeof raw === 'object') {
    const r = raw as Record<string, unknown>;
    // Try common error shapes in order of specificity
    const candidates = [
      r['message'],
      r['error'],
      r['detail'],
      r['reason'],
      r['msg'],
      r['description'],
      (r['data'] as Record<string, unknown> | null)?.['message'],
      (r['data'] as Record<string, unknown> | null)?.['error'],
      (r['response'] as Record<string, unknown> | null)?.['message'],
    ];
    for (const c of candidates) {
      if (typeof c === 'string' && c.trim()) return c.trim();
      if (typeof c === 'object' && c !== null) {
        const inner = extractErrorMessage(c);
        if (inner && inner !== 'Unknown error') return inner;
      }
    }
    // Last resort: serialize the whole object (truncated)
    try {
      const json = JSON.stringify(raw);
      return json.length > 300 ? json.slice(0, 300) + '…' : json;
    } catch {
      return 'Unknown error';
    }
  }

  return String(raw) || 'Unknown error';
}

export function monitorTaskStreamError(opts: {
  taskType: string;
  streamId?: string;
  onboardingId?: string | null;
  userId?: string | null;
  event?: any;
}) {
  const e = opts.event || {};
  upsertRow(makeActorKey(opts), opts.taskType, {
    streamId: opts.streamId || e.stream_id,
    status: 'error',
    lastEventType: 'error',
    lastSeq: e.seq ? Number(e.seq) : undefined,
    lastCursor: e.cursor ? String(e.cursor) : undefined,
    errorMessage: extractErrorMessage(e),
  });
}
