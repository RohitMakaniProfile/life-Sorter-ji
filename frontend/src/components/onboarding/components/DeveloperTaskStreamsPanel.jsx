import { useEffect, useMemo, useState, useRef, useCallback } from 'react';
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

export default function DeveloperTaskStreamsPanel({ onboardingId, userId = null, taskTypes = [] }) {
  const [open, setOpen] = useState(false);
  const enabled = isDevEnv();

  // Drag state
  const [position, setPosition] = useState({ x: 16, y: null }); // x from left, y from bottom (null = default 16)
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, startX: 0, startY: 0 });
  const panelRef = useRef(null);

  const actorKey = useMemo(() => makeActorKey({ onboardingId: onboardingId || null, userId: userId || null }), [onboardingId, userId]);
  const [, forceRender] = useState(0);

  useEffect(() => {
    if (!enabled || !open) return;
    return subscribeTaskStreamMonitor(() => forceRender((n) => (n + 1) % 1000000));
  }, [enabled, open]);

  // Handle mouse drag
  const handleMouseDown = useCallback((e) => {
    // Only allow drag from the header button
    if (e.target.closest('[data-no-drag]')) return;
    e.preventDefault();
    setIsDragging(true);
    const rect = panelRef.current?.getBoundingClientRect();
    if (rect) {
      dragStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        startX: rect.left,
        startY: rect.top,
      };
    }
  }, []);

  const handleMouseMove = useCallback((e) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStartRef.current.x;
    const dy = e.clientY - dragStartRef.current.y;
    const newX = dragStartRef.current.startX + dx;
    const newY = dragStartRef.current.startY + dy;
    // Clamp to viewport
    const maxX = window.innerWidth - (panelRef.current?.offsetWidth || 360);
    const maxY = window.innerHeight - (panelRef.current?.offsetHeight || 60);
    setPosition({
      x: Math.max(0, Math.min(maxX, newX)),
      y: Math.max(0, Math.min(maxY, newY)),
      fromTop: true, // Switch to top-based positioning when dragged
    });
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      return () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [isDragging, handleMouseMove, handleMouseUp]);

  if (!enabled) return null;

  const snap = getTaskStreamMonitorSnapshot();
  const actorRows = snap[actorKey] || {};
  const rows = taskTypes.map((t) => actorRows[t]).filter(Boolean);

  // Position styles
  const positionStyle = position.fromTop
    ? { left: position.x, top: position.y }
    : { left: position.x, bottom: position.y ?? 16 };

  return (
    <div
      ref={panelRef}
      className={clsx(
        'fixed z-[250] w-[360px] max-w-[92vw]',
        isDragging && 'select-none'
      )}
      style={positionStyle}
    >
      <div
        className={clsx(
          'rounded-xl border border-white/15 bg-black/60 backdrop-blur-md transition-colors',
          isDragging && 'ring-2 ring-violet-500/50'
        )}
      >
        {/* Header with drag handle */}
        <div className="flex items-center">
          {/* Drag handle */}
          <div
            onMouseDown={handleMouseDown}
            className="cursor-move px-3 py-2.5 text-white/40 hover:text-white/60 transition-colors"
            title="Drag to move"
          >
            <svg width="12" height="16" viewBox="0 0 12 16" fill="currentColor">
              <circle cx="3" cy="3" r="1.5" />
              <circle cx="9" cy="3" r="1.5" />
              <circle cx="3" cy="8" r="1.5" />
              <circle cx="9" cy="8" r="1.5" />
              <circle cx="3" cy="13" r="1.5" />
              <circle cx="9" cy="13" r="1.5" />
            </svg>
          </div>
          {/* Toggle button */}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex-1 cursor-pointer py-2.5 pr-4 text-left text-[12px] font-semibold text-white/80 hover:text-white transition-colors"
          >
            Background Tasks {open ? '▾' : '▸'}
            <span className="ml-2 text-[11px] font-normal text-white/40">{onboardingId ? `oid: ${String(onboardingId).slice(0, 8)}…` : 'no oid'}</span>
          </button>
        </div>

        {open && (
          <div className="overflow-hidden border-t border-white/12">
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
    </div>
  );
}
