import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { PipelineState, TokenUsage } from '../../types';
import { getSkillCalls, getTokenUsage, type SkillCallFull } from '../../../api';
import TokenUsagePanel from './TokenUsagePanel';

type LiveSkillCard = {
  skillId: string;
  status: 'running' | 'done' | 'error' | 'unknown';
  args?: unknown;
  outputSummary?: string;
  latestMeta?: unknown;
  latestMessage?: string;
};

export default function SidePanel({
  open,
  title,
  pipeline,
  messageId,
  onClose,
}: {
  open: boolean;
  title?: string;
  pipeline: PipelineState | null;
  messageId?: string;
  onClose: () => void;
}) {
  if (!open) return null;

  const MIN_W = 320;
  const MAX_W = 720;
  const DEFAULT_W = 420;
  const storageKey = 'ikshan:contextPanelWidth';

  const [width, setWidth] = useState<number>(() => {
    const raw = typeof window !== 'undefined' ? window.localStorage.getItem(storageKey) : null;
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? Math.min(Math.max(n, MIN_W), MAX_W) : DEFAULT_W;
  });
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const [skillCalls, setSkillCalls] = useState<SkillCallFull[] | null>(null);
  const [callsLoading, setCallsLoading] = useState(false);
  const [tokenUsage, setTokenUsageState] = useState<TokenUsage | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'structured' | 'context'>('structured');

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, String(width));
    } catch {
      // ignore
    }
  }, [width]);

  useEffect(() => {
    const onMove = (ev: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = d.startX - ev.clientX; // dragging left increases width
      const next = Math.min(Math.max(d.startW + dx, MIN_W), MAX_W);
      setWidth(next);
    };
    const onUp = () => {
      dragRef.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  // When viewing a persisted message context, load from DB.
  useEffect(() => {
    if (!messageId) {
      setSkillCalls(null);
      setTokenUsageState(null);
      return;
    }

    setCallsLoading(true);
    getSkillCalls(messageId)
      .then((r) => setSkillCalls(r.skillCalls ?? []))
      .catch(() => setSkillCalls([]))
      .finally(() => setCallsLoading(false));

    setUsageLoading(true);
    getTokenUsage(messageId)
      .then((u) => setTokenUsageState(u))
      .catch(() => setTokenUsageState(null))
      .finally(() => setUsageLoading(false));
  }, [messageId]);

  const liveSkillCards = useMemo<LiveSkillCard[]>(() => {
    const evs = pipeline?.progressEvents ?? [];

    const inferSkillIdFromMessage = (msg: string): string | null => {
      const m1 = msg.match(/^Running\s+skill:\s+([a-z0-9-_.]+)$/i);
      if (m1?.[1]) return m1[1];
      const m2 = msg.match(/^Running\s+([a-z0-9-_.]+)$/i);
      if (m2?.[1]) return m2[1];
      const m3 = msg.match(/^Skill\s+([a-z0-9-_.]+)\s+(completed|failed)/i);
      if (m3?.[1]) return m3[1];
      return null;
    };

    const cards: Record<string, LiveSkillCard> = {};

    for (const e of evs as any[]) {
      const meta = (e?.meta ?? {}) as any;
      const msg = String(e?.message ?? '');

      const skillId =
        (typeof meta?.skillId === 'string' && meta.skillId) ||
        inferSkillIdFromMessage(msg) ||
        null;
      if (!skillId) continue;

      const existing = cards[skillId] ?? { skillId, status: 'unknown' as const };

      // Status
      const statusFromMeta = meta?.status;
      let status: LiveSkillCard['status'] = existing.status;
      if (statusFromMeta === 'running' || statusFromMeta === 'done' || statusFromMeta === 'error') {
        status = statusFromMeta;
      } else if (/failed/i.test(msg)) {
        status = 'error';
      } else if (/completed/i.test(msg)) {
        status = 'done';
      } else if (/running|starting|started/i.test(msg)) {
        status = existing.status === 'unknown' ? 'running' : existing.status;
      }

      // Args (if present)
      const args = meta?.input?.args ?? existing.args;

      // Output summary (if present on completion event)
      const outputSummary =
        typeof meta?.outputSummary === 'string'
          ? meta.outputSummary
          : existing.outputSummary;

      cards[skillId] = {
        skillId,
        status,
        args,
        outputSummary,
        latestMeta: meta && Object.keys(meta).length > 0 ? meta : existing.latestMeta,
        latestMessage: msg || existing.latestMessage,
      };
    }

    return Object.values(cards);
  }, [pipeline]);

  const liveTokenEstimate = useMemo(() => {
    const evs = pipeline?.progressEvents ?? [];
    let outputChars = 0;
    let outputTokensEstimated = 0;
    for (const e of evs as any[]) {
      const meta = (e?.meta ?? {}) as any;
      if (meta?.kind !== 'token-usage') continue;
      if (typeof meta.outputChars === 'number') outputChars = Math.max(outputChars, meta.outputChars);
      if (typeof meta.outputTokensEstimated === 'number') {
        outputTokensEstimated = Math.max(outputTokensEstimated, meta.outputTokensEstimated);
      }
    }
    if (outputChars <= 0 && outputTokensEstimated <= 0) return null;
    return { outputChars, outputTokensEstimated };
  }, [pipeline]);

  return (
    <div className="border-l bg-white flex flex-col relative" style={{ width }}>
      {/* Drag handle */}
      <div
        role="separator"
        aria-orientation="vertical"
        title="Drag to resize"
        onMouseDown={(ev) => {
          dragRef.current = { startX: ev.clientX, startW: width };
          document.body.style.cursor = 'col-resize';
          document.body.style.userSelect = 'none';
        }}
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize bg-transparent hover:bg-violet-200/60"
      />
      <div className="p-4 border-b font-semibold flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate">{title ?? 'Execution details'}</div>
          <div className="text-[11px] font-normal text-slate-500">
            {messageId ? 'Persisted message context' : 'Live run (streaming)'}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            <button
              type="button"
              onClick={() => setViewMode('structured')}
              className={`px-2 py-1 text-[11px] font-semibold rounded-md ${
                viewMode === 'structured' ? 'bg-violet-600 text-white' : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              Structured
            </button>
            <button
              type="button"
              onClick={() => setViewMode('context')}
              className={`px-2 py-1 text-[11px] font-semibold rounded-md ${
                viewMode === 'context' ? 'bg-violet-600 text-white' : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              Context
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-slate-400 hover:text-slate-600"
            aria-label="Close panel"
          >
            ✕
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Skills */}
        <div>
          <h3 className="text-sm font-semibold mb-2">Skills</h3>
          {viewMode === 'context' ? (
            <div className="border rounded-lg bg-white overflow-hidden">
              <div className="px-3 py-2 border-b text-[11px] font-semibold text-slate-700 flex items-center justify-between">
                <span>Skill context (summaries)</span>
                <button
                  type="button"
                  onClick={() => {
                    const text = (() => {
                      if (messageId) {
                        const calls = skillCalls ?? [];
                        return calls
                          .map((c) => {
                            const last = c.output?.filter((e) => e.type === 'result').pop();
                            const t = (last as any)?.text as string | undefined;
                            return `### ${c.skillId}\n\n${(t ?? '').trim() || '_No summarized output._'}`;
                          })
                          .join('\n\n---\n\n');
                      }
                      const cards = liveSkillCards;
                      return cards
                        .map((c) => `### ${c.skillId}\n\n${(c.outputSummary ?? '').trim() || (c.status === 'running' ? '_Processing…_' : '_No summarized output._')}`)
                        .join('\n\n---\n\n');
                    })();
                    void navigator.clipboard?.writeText(text);
                  }}
                  className="text-[11px] font-semibold text-violet-600 hover:text-violet-700"
                >
                  Copy
                </button>
              </div>
              <div className="px-3 py-2 max-h-[60vh] overflow-y-auto">
                {messageId && callsLoading ? (
                  <p className="text-xs text-slate-500">Loading skills…</p>
                ) : (
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {messageId
                        ? (skillCalls ?? [])
                            .map((c) => {
                              const last = c.output?.filter((e) => e.type === 'result').pop();
                              const t = (last as any)?.text as string | undefined;
                              return `### ${c.skillId}\n\n${(t ?? '').trim() || '_No summarized output._'}`;
                            })
                            .join('\n\n---\n\n')
                        : liveSkillCards
                            .map(
                              (c) =>
                                `### ${c.skillId}\n\n${(c.outputSummary ?? '').trim() || (c.status === 'running' ? '_Processing…_' : '_No summarized output._')}`
                            )
                            .join('\n\n---\n\n')}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ) : messageId ? (
            callsLoading ? (
              <p className="text-xs text-slate-500">Loading skills…</p>
            ) : (skillCalls?.length ?? 0) === 0 ? (
              <p className="text-xs text-slate-500">No skills recorded.</p>
            ) : (
              <div className="space-y-2">
                {skillCalls!.map((c) => (
                  <details key={c.id} className="border rounded-lg overflow-hidden">
                    <summary className="cursor-pointer px-3 py-2 text-xs font-semibold flex items-center justify-between">
                      <span className="truncate">{c.skillId}</span>
                      <span className="text-[10px] text-slate-500">{c.state}</span>
                    </summary>
                    <div className="px-3 pb-3 pt-2 border-t text-xs space-y-2">
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Input</div>
                        <pre className="bg-slate-900 text-slate-100 rounded p-2 overflow-x-auto max-h-40">
                          {JSON.stringify(c.input ?? {}, null, 2)}
                        </pre>
                      </div>
                      {(() => {
                        const last = c.output?.filter((e) => e.type === 'result').pop();
                        const txt = (last as any)?.text as string | undefined;
                        return txt ? (
                          <div>
                            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Output summary</div>
                            <pre className="bg-slate-50 text-slate-800 rounded p-2 overflow-x-auto whitespace-pre-wrap max-h-56 overflow-y-auto">
                              {txt}
                            </pre>
                          </div>
                        ) : null;
                      })()}
                    </div>
                  </details>
                ))}
              </div>
            )
          ) : liveSkillCards.length === 0 ? (
            <p className="text-xs text-slate-500">No skills yet.</p>
          ) : (
            <div className="space-y-2">
              {liveSkillCards.map((c) => (
                <details key={c.skillId} className="border rounded-lg overflow-hidden bg-white">
                  <summary className="cursor-pointer px-3 py-2 text-xs font-semibold flex items-center justify-between gap-2">
                    <span className="truncate">{c.skillId}</span>
                    <span className="shrink-0 text-[10px] text-slate-500">
                      {c.status}
                    </span>
                  </summary>
                  <div className="px-3 pb-3 pt-2 border-t text-xs space-y-2">
                    {c.args != null && (
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Args</div>
                        <pre className="bg-slate-900 text-slate-100 rounded p-2 overflow-x-auto max-h-40">
                          {JSON.stringify(c.args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {c.status === 'done' && c.outputSummary && (
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Final output summary</div>
                        <pre className="bg-slate-50 text-slate-800 rounded p-2 whitespace-pre-wrap max-h-56 overflow-y-auto">
                          {c.outputSummary}
                        </pre>
                      </div>
                    )}

                    {c.latestMeta != null && (
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Latest output/progress data</div>
                        <pre className="bg-slate-900 text-slate-100 rounded p-2 overflow-x-auto max-h-56 overflow-y-auto">
                          {JSON.stringify(c.latestMeta, null, 2)}
                        </pre>
                      </div>
                    )}

                    {c.latestMessage && (
                      <div className="text-[11px] text-slate-600">
                        {c.latestMessage}
                      </div>
                    )}
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>

        <TokenUsagePanel
          messageId={messageId}
          tokenUsage={tokenUsage}
          usageLoading={usageLoading}
          liveTokenEstimate={liveTokenEstimate}
        />
      </div>
    </div>
  );
}