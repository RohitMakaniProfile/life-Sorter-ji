import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { getTaskStreamMonitorSnapshot, subscribeTaskStreamMonitor, makeActorKey } from '../../../api/services/taskStreamMonitor';

function isDevEnv() {
  try {
    // Vite
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV) return true;
  } catch {
    // ignore
  }
  try {
    const host = window.location.hostname;
    return host === 'localhost' || host === '127.0.0.1';
  } catch {
    return false;
  }
}

export default function DeveloperTaskStreamsPanel({ sessionId, userId = null, taskTypes = [] }) {
  const [open, setOpen] = useState(false);
  const enabled = isDevEnv();

  const actorKey = useMemo(() => makeActorKey({ sessionId: sessionId || null, userId: userId || null }), [sessionId, userId]);
  const [, forceRender] = useState(0);

  useEffect(() => {
    if (!enabled || !open) return;
    return subscribeTaskStreamMonitor(() => forceRender((n) => (n + 1) % 1000000));
  }, [enabled, open]);

  if (!enabled) return null;

  const snap = getTaskStreamMonitorSnapshot();
  const actorRows = snap[actorKey] || {};
  const rows = taskTypes.map((t) => actorRows[t]).filter(Boolean);

  return (
    <div className="fixed left-4 bottom-4 z-[250] w-[360px] max-w-[92vw]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full cursor-pointer rounded-xl border border-white/15 bg-black/60 px-4 py-2.5 text-left text-[12px] font-semibold text-white/80 backdrop-blur-md transition-colors hover:bg-black/70"
      >
        Background Tasks {open ? '▾' : '▸'}
        <span className="ml-2 text-[11px] font-normal text-white/40">{sessionId ? `sid: ${String(sessionId).slice(0, 8)}…` : 'no sid'}</span>
      </button>

      {open && (
        <div className="mt-2 overflow-hidden rounded-xl border border-white/12 bg-black/60 backdrop-blur-md">
          {rows.length === 0 ? (
            <div className="px-4 py-3 text-[12px] text-white/50">No stored streams for this actor.</div>
          ) : (
            <div className="divide-y divide-white/10">
              {rows.map((r) => {
                const status = String(r?.status || '');
                return (
                  <div key={`${r.taskType}-${r.streamId}`} className="px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-[12px] font-semibold text-white/85">{r.taskType}</div>
                        <div className="truncate text-[11px] text-white/40">stream: {r.streamId}</div>
                      </div>
                      <span
                        className={clsx(
                          'shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider',
                          status === 'running'
                            ? 'bg-indigo-500/20 text-indigo-200'
                            : status === 'done'
                              ? 'bg-emerald-500/20 text-emerald-200'
                              : status === 'error'
                                ? 'bg-rose-500/20 text-rose-200'
                                : 'bg-white/10 text-white/60',
                        )}
                      >
                        {status || 'unknown'}
                      </span>
                    </div>
                    {r.errorMessage && <div className="mt-2 text-[11px] text-rose-200/80">{r.errorMessage}</div>}
                    {r.lastSeq && (
                      <div className="mt-1 text-[11px] text-white/40">
                        last_seq: {String(r.lastSeq)} {r.lastCursor ? `• cursor: ${String(r.lastCursor)}` : ''}
                      </div>
                    )}
                    {r.stage || r.label ? (
                      <div className="mt-1 text-[11px] text-white/40">
                        {r.stage ? `stage: ${r.stage}` : ''} {r.label ? `• ${r.label}` : ''}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

