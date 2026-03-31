import React, { useMemo, useRef, useEffect, useLayoutEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import VideoCard from './VideoCard';
import type { AgentId, PipelineStage } from '../../api/client';
import { downloadReportAsPdf } from '../../utils/downloadPdf';
import { downloadMarkdownAsFile } from '../../utils/downloadMarkdown';
import { getInsightFeedback, setInsightFeedback, getPhase2IsSuperAdmin } from '../../api/client';
import SidePanel from './SidePanel';
import type { PipelineState as SharedPipelineState } from '../../types';

export interface RichMessage {
  role: 'user' | 'assistant';
  content: string;
  createdAt?: string;
  agentId?: AgentId;
  pipeline?: SharedPipelineState;
  outputFile?: string;
  messageId?: string;
  /** Number of skill calls (from DB); details loaded on expand */
  skillsCount?: number;
  kind?: 'plan' | 'final';
  planId?: string;
  todoState?: 'draft' | 'started';
}

export interface ChatUIProps {
  messages: RichMessage[];
  onSend: (msg: string) => Promise<void>;
  onApprovePlan?: (planId: string, planMarkdown: string) => Promise<void>;
  loading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  title?: string;
  subtitle?: string;
  agentId?: AgentId;
  retryHandlers?: Array<
    ((fromStage: PipelineStage, stageOutputs: Record<string, string>) => void) | undefined
  >;
}

// NOTE: Skills + token usage UI moved to right-side Context panel.

// ─── Markdown renderer (shared) ───────────────────────────────────────────────

const mdComponents: React.ComponentProps<typeof ReactMarkdown>['components'] = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline text-violet-600">{children}</a>
  ),
  p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-1">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  code: ({ children }) => (
    <code className="rounded px-1 text-xs font-mono bg-slate-100 text-violet-700">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-slate-200 shadow-sm">
      <table className="min-w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-violet-50 text-violet-800">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-slate-100">{children}</tbody>,
  tr: ({ children }) => <tr className="hover:bg-slate-50 transition-colors">{children}</tr>,
  th: ({ children }) => (
    <th className="px-3 py-2 text-left font-semibold text-[11px] uppercase tracking-wide whitespace-nowrap border-b border-violet-100">{children}</th>
  ),
  td: ({ children }) => <td className="px-3 py-2 text-slate-700 align-top">{children}</td>,
  h1: ({ children }) => <h1 className="text-xl font-bold text-slate-900 mt-4 mb-2 pb-1 border-b border-slate-200">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-bold text-slate-800 mt-4 mb-1.5">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-violet-700 mt-3 mb-1">{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-violet-300 pl-3 my-2 text-slate-500 italic">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-slate-200" />,
};

const mdComponentsUser: React.ComponentProps<typeof ReactMarkdown>['components'] = {
  ...mdComponents,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline text-white/95">
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded px-1 text-xs font-mono bg-white/15 text-white">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="bg-white/10 text-white rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-white/40 pl-3 my-2 text-white/90 italic">{children}</blockquote>
  ),
  thead: ({ children }) => <thead className="bg-white/10 text-white">{children}</thead>,
  tbody: ({ children }) => <tbody className="text-white/95">{children}</tbody>,
};

// ─── AssistantMessage — accordion for long reports ────────────────────────────

const REPORT_THRESHOLD = 500; // chars — above this, show accordion
const PREVIEW_LINES = 6;      // lines visible when collapsed

function extractInsights(markdown: string): Array<{ index: number; title: string }> {
  const out: Array<{ index: number; title: string }> = [];
  const re = /^#{2,4}\s*Insight\s+(\d+)\s*:\s*(.+)\s*$/gim;
  let m: RegExpExecArray | null;
  while ((m = re.exec(markdown || ''))) {
    const idx = Number(m[1]);
    const title = String(m[2] || '').trim();
    if (!Number.isFinite(idx) || idx <= 0) continue;
    out.push({ index: idx, title: title || `Insight ${idx}` });
  }
  // de-dupe by index
  const seen = new Set<number>();
  return out.filter((x) => (seen.has(x.index) ? false : (seen.add(x.index), true)));
}

function PlanMessage({
  message,
  onOpenContext,
  onApprovePlan,
  canEdit,
}: {
  message: RichMessage;
  onOpenContext: (messageId: string) => void;
  onApprovePlan?: (planId: string, planMarkdown: string) => Promise<void>;
  canEdit: boolean;
}) {
  const [draft, setDraft] = useState(message.content);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const started = message.todoState === 'started';

  useEffect(() => {
    setDraft(message.content);
  }, [message.content]);

  useEffect(() => {
    if (started) setEditing(false);
  }, [started]);

  return (
    <div className="bg-white text-slate-800 border border-slate-200 rounded-2xl rounded-tl-none shadow-sm overflow-hidden w-full">
      <div className="px-5 pt-3.5 pb-2 flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-slate-800">Todo (edit then start working)</div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] font-semibold text-violet-600 hover:text-violet-700"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
          {message.messageId && (
            <button
              type="button"
              onClick={() => onOpenContext(message.messageId!)}
              className="text-[11px] font-semibold text-violet-600 hover:text-violet-700"
            >
              Context
            </button>
          )}
        </div>
      </div>

      <div className="px-5 pb-4">
        {/* Markdown preview (default, full width) */}
        <div className="rounded-xl border border-slate-200 bg-white p-3 overflow-y-auto">
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {expanded ? draft : draft.slice(0, 700)}
            </ReactMarkdown>
          </div>
        </div>
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-semibold text-violet-600 hover:text-violet-700"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        </div>

        {/* Editor (optional) */}
        {editing && canEdit && !started && (
          <div className="mt-3">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-2">
              Editor
            </div>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={14}
              className="w-full resize-y rounded-xl border border-slate-200 p-3 text-sm font-mono bg-slate-50 text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
          </div>
        )}
        <div className="flex justify-end gap-2 mt-3">
          {canEdit && !started && (
            <button
              type="button"
              onClick={() => setEditing((v) => !v)}
              className="px-3 py-2 rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              {editing ? 'Done editing' : 'Edit todo'}
            </button>
          )}
          {canEdit && !started && (
            <button
              type="button"
              disabled={!onApprovePlan || saving}
              onClick={async () => {
                if (!onApprovePlan || !message.planId) return;
                setSaving(true);
                try {
                  await onApprovePlan(message.planId, draft);
                } finally {
                  setSaving(false);
                }
              }}
              className="px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
            >
              {saving ? 'Starting…' : 'Start working'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function AssistantMessage({
  message: m,
  loading,
  isLast,
  onOpenContext,
  onOpenLiveContext,
  onApprovePlan,
}: {
  message: RichMessage;
  loading: boolean;
  isLast: boolean;
  onOpenContext: (messageId: string) => void;
  onOpenLiveContext: () => void;
  onApprovePlan?: (planId: string, planMarkdown: string) => Promise<void>;
}) {
  // Plan approval UI
  if (m.role === 'assistant' && m.kind === 'plan' && m.planId) {
    return (
      <PlanMessage
        message={m}
        onOpenContext={onOpenContext}
        onApprovePlan={onApprovePlan}
        canEdit={isLast && m.todoState !== 'started'}
      />
    );
  }

  // Determine if this is a long report that needs the accordion.
  // We check content length only — agent selection must never affect this.
  // Any assistant message > REPORT_THRESHOLD chars gets the accordion + download.
  const isReport = m.role === 'assistant' && m.content.length > REPORT_THRESHOLD;

  // Start expanded while streaming; collapse once done and not loading
  const [expanded, setExpanded] = useState(!isReport);

  // Auto-expand while streaming tokens are coming in
  useEffect(() => {
    if (loading && isReport && isLast) setExpanded(true);
  }, [loading, isReport, isLast]);

  const previewContent = isReport
    ? m.content.split('\n').slice(0, PREVIEW_LINES).join('\n')
    : m.content;

  const [insightFeedback, setInsightFeedbackState] = useState<Record<number, 1 | -1>>({});
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const insights = useMemo(() => (isReport ? extractInsights(m.content) : []), [isReport, m.content]);

  useEffect(() => {
    if (!m.messageId) return;
    if (!isReport) return;
    if (!insights.length) return;
    setFeedbackLoading(true);
    setFeedbackError(null);
    getInsightFeedback(m.messageId)
      .then((r) => {
        const map: Record<number, 1 | -1> = {};
        for (const it of r.feedback || []) {
          const idx = Number((it as any).insightIndex);
          const rating = Number((it as any).rating);
          if (Number.isFinite(idx) && (rating === 1 || rating === -1)) {
            map[idx] = rating as 1 | -1;
          }
        }
        setInsightFeedbackState(map);
      })
      .catch((e) => setFeedbackError(e instanceof Error ? e.message : 'Failed to load feedback'))
      .finally(() => setFeedbackLoading(false));
  }, [m.messageId, isReport, insights.length]);

  return (
    <div
      className={
        m.role === 'assistant'
          ? 'bg-white text-slate-800 border border-slate-200 rounded-2xl rounded-tl-none shadow-sm overflow-hidden'
          : ''
      }
    >
      {/* Typing indicator — only for the last assistant message */}
      {m.role === 'assistant' && !m.content && isLast && (
        <div className="flex items-center justify-between gap-3 px-5 py-3.5">
          <div className="min-w-0">
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
              <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
              <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-bounce" />
            </div>
            {(() => {
              const latest = m.pipeline?.progressEvents?.[m.pipeline.progressEvents.length - 1]?.message;
              if (!latest) return null;
              return (
                <div className="mt-1 text-[11px] text-slate-500 truncate max-w-[420px]">
                  {latest}
                </div>
              );
            })()}
          </div>
          <button
            type="button"
            onClick={onOpenLiveContext}
            className="text-[11px] font-semibold text-violet-600 hover:text-violet-700"
            title="Open context panel (skills + token usage)"
          >
            Context
          </button>
        </div>
      )}

      {m.content && (
        <>
          {/* Top bar: Context button */}
          <div className="px-5 pt-3.5 pb-0.5 flex items-start justify-end">
            {m.messageId && (
              <button
                type="button"
                onClick={() => onOpenContext(m.messageId!)}
                className="text-[11px] font-semibold text-violet-600 hover:text-violet-700"
                title="Open context (skills + token usage)"
              >
                Context
              </button>
            )}
          </div>

          {/* Content area */}
          <div className="relative px-5 pt-1.5">
            <div className="text-sm sm:text-[15px] leading-relaxed prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {expanded ? m.content : previewContent}
              </ReactMarkdown>
            </div>

            {/* Fade-out gradient when collapsed */}
            {isReport && !expanded && (
              <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-white to-transparent pointer-events-none" />
            )}
          </div>

          {/* ── Accordion toggle + Download bar — sticky at bottom edge ── */}
          {isReport && (
            <div className="sticky bottom-0 z-10 bg-white border-t border-slate-100">
              {/* Expand / collapse toggle */}
              <button
                onClick={() => setExpanded((v) => !v)}
                className="w-full flex items-center justify-center gap-2 px-5 py-2.5 text-xs font-medium text-violet-600 hover:bg-violet-50 transition-colors"
              >
                {expanded ? (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
                    </svg>
                    Collapse report
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                    Expand full report
                    <span className="ml-1 text-slate-400 font-normal">
                      ({Math.round(m.content.length / 1000)}k chars)
                    </span>
                  </>
                )}
              </button>

              {/* Download PDF — always visible, never gated on expanded/agent */}
              <div className="flex items-center justify-between gap-3 px-5 py-2.5 border-t border-slate-100">
                <span className="text-[11px] text-slate-400 font-medium">
                  {loading ? 'Generating…' : 'Report ready'}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={loading}
                    onClick={() => downloadMarkdownAsFile(m.content, m.agentId ? String(m.agentId) : 'ikshan-report')}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 hover:bg-slate-50 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed text-slate-700 text-xs font-semibold rounded-lg transition-all"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Download MD
                  </button>
                  <button
                    disabled={loading}
                    onClick={() => downloadReportAsPdf(m.content)}
                    className="flex items-center gap-1.5 px-4 py-1.5 bg-violet-600 hover:bg-violet-700 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg transition-all shadow-sm"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Download PDF
                  </button>
                </div>
              </div>

              {/* Insight feedback */}
              {m.messageId && insights.length > 0 && (
                <div className="px-5 py-3 border-t border-slate-100">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="text-[11px] font-semibold text-slate-600">Insight feedback</div>
                    <div className="text-[11px] text-slate-400">
                      {feedbackLoading ? 'Loading…' : 'Thumbs up/down per insight'}
                    </div>
                  </div>
                  {feedbackError && (
                    <div className="mb-2 text-[11px] text-red-600">
                      {feedbackError}
                    </div>
                  )}
                  <div className="max-h-[180px] overflow-y-auto pr-1 space-y-1">
                    {insights.map((it) => {
                      const rating = insightFeedback[it.index];
                      const upOn = rating === 1;
                      const downOn = rating === -1;
                      return (
                        <div key={it.index} className="flex items-center gap-2 py-1">
                          <div className="min-w-0 flex-1">
                            <div className="text-[11px] text-slate-700 truncate">
                              <span className="font-mono text-slate-400 mr-2">#{it.index}</span>
                              {it.title}
                            </div>
                          </div>
                          <button
                            type="button"
                            disabled={feedbackLoading}
                            onClick={async () => {
                              if (!m.messageId) return;
                              setFeedbackLoading(true);
                              setFeedbackError(null);
                              try {
                                const next: 1 | -1 = 1;
                                await setInsightFeedback({ messageId: m.messageId, insightIndex: it.index, rating: next });
                                setInsightFeedbackState((prev) => ({ ...prev, [it.index]: next }));
                              } catch (e) {
                                setFeedbackError(e instanceof Error ? e.message : 'Failed to save feedback');
                              } finally {
                                setFeedbackLoading(false);
                              }
                            }}
                            className={`px-2 py-1 rounded-md text-[11px] font-semibold border transition-colors ${
                              upOn ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                            }`}
                            title="Thumbs up"
                          >
                            👍
                          </button>
                          <button
                            type="button"
                            disabled={feedbackLoading}
                            onClick={async () => {
                              if (!m.messageId) return;
                              setFeedbackLoading(true);
                              setFeedbackError(null);
                              try {
                                const next: 1 | -1 = -1;
                                await setInsightFeedback({ messageId: m.messageId, insightIndex: it.index, rating: next });
                                setInsightFeedbackState((prev) => ({ ...prev, [it.index]: next }));
                              } catch (e) {
                                setFeedbackError(e instanceof Error ? e.message : 'Failed to save feedback');
                              } finally {
                                setFeedbackLoading(false);
                              }
                            }}
                            className={`px-2 py-1 rounded-md text-[11px] font-semibold border transition-colors ${
                              downOn ? 'bg-red-50 border-red-200 text-red-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                            }`}
                            title="Thumbs down"
                          >
                            👎
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Non-report assistant messages: no accordion, just bottom padding */}
          {!isReport && m.role === 'assistant' && (
            <div className="px-5 pb-3.5" />
          )}
        </>
      )}
    </div>
  );
}

export default function ChatUI({
  messages,
  onSend,
  onApprovePlan,
  loading = false,
  disabled = false,
  placeholder,
  title,
  subtitle = 'Powered by Ikshan',
  agentId = 'amazon-video',
  retryHandlers: _retryHandlers = [],
}: ChatUIProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [contextMessageId, setContextMessageId] = useState<string | undefined>(undefined);
  const canUseContextPanel = getPhase2IsSuperAdmin();

  const resolvedTitle = title ?? 'Chat';
  const resolvedPlaceholder = placeholder ?? 'Ask me anything…';

  // Scroll to bottom so latest message is visible (no CSS-only way for initial position).
  useLayoutEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  // Never auto-open the context panel.

  // When the run finishes and the last assistant message has a messageId,
  // switch the panel to persisted mode so skill states don't get stuck at "running".
  useEffect(() => {
    if (loading) return;
    if (!contextOpen) return;
    if (contextMessageId) return; // user is already viewing some message context
    const last = messages[messages.length - 1];
    if (last?.role === 'assistant' && last.messageId) {
      setContextMessageId(last.messageId);
    }
  }, [loading, contextOpen, contextMessageId, messages]);

  const livePipeline = (() => {
    const last = messages[messages.length - 1];
    return last?.role === 'assistant' ? (last.pipeline ?? null) : null;
  })();

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const raw = inputRef.current?.value?.trim();
    if (!raw || disabled || loading) return;
    inputRef.current!.value = '';
    inputRef.current!.style.height = 'auto';
    await onSend(raw);
  };

  const emptyStateSuggestions =
    agentId === 'business-research'
      ? [
          { icon: '📊', text: 'Business strategy for https://example.com' },
          { icon: '🔍', text: 'Analyze competitors for a SaaS startup' },
          { icon: '🎯', text: 'What are the best growth tactics for B2B?' },
          { icon: '📈', text: 'SEO keywords for an ed-tech company' },
        ]
      : [
          { icon: '🛒', text: 'Generate a product video from Amazon URL' },
          { icon: '📝', text: 'Write a video script for my product' },
          { icon: '🎙️', text: 'Create a voiceover for this script' },
          { icon: '🎥', text: 'Generate a 5-second promo clip' },
        ];

  return (
    <div className="flex h-full w-full bg-white overflow-hidden">
      {/* Main chat */}
      <div className="flex flex-col h-full flex-1 overflow-hidden">
      {/* Header */}
      <header className="px-6 py-4 border-b border-gray-100 bg-white flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-lg font-bold text-gray-800 tracking-tight">
            {resolvedTitle}
          </h1>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            <span className="text-xs text-gray-400 font-medium">{subtitle}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canUseContextPanel && (
            <button
              type="button"
              onClick={() => setContextOpen((v) => !v)}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
              title="Toggle context panel"
            >
              {contextOpen ? 'Hide panel' : 'Show panel'}
            </button>
          )}
        </div>
      </header>

      {/* Messages — normal order (oldest top, newest bottom); scroll to bottom via useLayoutEffect */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-slate-50/30 p-4 sm:p-8 flex flex-col min-h-0"
      >
        <div className={`flex flex-col space-y-6 ${messages.length === 0 ? 'min-h-full justify-center' : ''}`}>
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center min-h-[200px] text-center space-y-4 opacity-70">
            <div className="w-20 h-20 bg-gradient-to-br from-violet-100 to-indigo-100 text-violet-600 rounded-2xl flex items-center justify-center text-3xl shadow-sm border border-violet-200">
              🤖
            </div>
            <div className="space-y-2">
              <p className="text-slate-700 font-semibold text-lg">AI Agent</p>
              <p className="text-slate-400 text-sm max-w-sm">
                Ask a question or paste a URL to get started.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2 max-w-lg w-full">
              {emptyStateSuggestions.map((s) => (
                <button
                  key={s.text}
                  onClick={() => {
                    if (inputRef.current) {
                      inputRef.current.value = s.text;
                      inputRef.current.dispatchEvent(new Event('input', { bubbles: true }));
                      inputRef.current.focus();
                    }
                  }}
                  className="flex items-center gap-2 px-4 py-3 bg-white border border-slate-200 rounded-xl text-sm text-slate-600 hover:border-violet-300 hover:bg-violet-50 hover:text-violet-700 transition-all text-left cursor-pointer"
                >
                  <span className="text-base">{s.icon}</span>
                  <span>{s.text}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          // Hide older assistant messages that never produced any content
          // (we only show the typing indicator for the latest one).
          (m.role === 'assistant' && !m.content && i !== messages.length - 1)
            ? null
            : (
          <div key={m.messageId ?? `${m.role}-${m.createdAt ?? ''}-${i}`} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {m.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-sm mr-3 flex-shrink-0 mt-1">
                🤖
              </div>
            )}
            <div
              className={`max-w-[85%] sm:max-w-[75%] ${
                m.role === 'user'
                  ? 'px-5 py-3.5 bg-violet-600 text-white rounded-2xl rounded-tr-none shadow-sm'
                  : (m.pipeline || (m.role === 'assistant' && m.kind === 'plan'))
                  ? 'w-full'
                  : ''
              }`}
            >
              {/* User message — Markdown */}
              {m.role === 'user' && (
                <div className="text-sm sm:text-[15px] leading-relaxed prose prose-sm max-w-none prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponentsUser}>
                    {m.content}
                  </ReactMarkdown>
                </div>
              )}

              {/* Assistant message — accordion for long reports */}
              {m.role === 'assistant' && (
                <AssistantMessage
                  message={m}
                  loading={loading}
                  isLast={i === messages.length - 1}
                  onApprovePlan={onApprovePlan}
                  onOpenLiveContext={() => {
                    if (!canUseContextPanel) return;
                    setContextMessageId(undefined);
                    setContextOpen(true);
                  }}
                  onOpenContext={(messageId) => {
                    if (!canUseContextPanel) return;
                    setContextMessageId(messageId);
                    setContextOpen(true);
                  }}
                />
              )}

              {/* Skills + token usage are shown in the SidePanel via the Context button */}

              {m.role === 'assistant' && (() => {
                const file = m.pipeline?.outputFile ?? m.outputFile;
                return file ? <VideoCard outputFile={file} /> : null;
              })()}
            </div>
          </div>
        )))}

        {loading && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className="flex justify-start">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-sm mr-3 flex-shrink-0">
              🤖
            </div>
            <div className="px-5 py-4 bg-white border border-slate-200 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-1">
              <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
              <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
              <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-bounce" />
            </div>
          </div>
        )}
        </div>
      </div>

      {/* Input */}
      <div className="p-4 sm:p-6 bg-white border-t border-gray-100 flex-shrink-0">
        <form onSubmit={handleSubmit} className="relative max-w-5xl mx-auto flex items-end gap-3">
          <textarea
            ref={inputRef}
            rows={1}
            placeholder={resolvedPlaceholder}
            disabled={disabled || loading}
            onInput={(e) => {
              const t = e.target as HTMLTextAreaElement;
              t.style.height = 'auto';
              t.style.height = `${Math.min(t.scrollHeight, 200)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void handleSubmit();
              }
            }}
            className="w-full resize-none bg-slate-100 focus:bg-white border-none focus:ring-2 focus:ring-violet-500 rounded-2xl px-5 py-3.5 pr-14 text-slate-900 transition-all placeholder:text-slate-400 shadow-inner outline-none"
          />
          <button
            type="submit"
            disabled={disabled || loading}
            className="flex-shrink-0 p-3.5 rounded-xl transition-all shadow-md active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: disabled || loading ? '#e2e8f0' : '#7c3aed',
              border: 'none',
              cursor: disabled || loading ? 'not-allowed' : 'pointer',
              color: 'white',
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
              <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
            </svg>
          </button>
        </form>
        <p className="text-[10px] text-center text-slate-400 mt-3 font-medium uppercase tracking-wider">
          Powered by Ikshan AI
        </p>
      </div>
      </div>

      {/* Context side panel (super admin only) */}
      {canUseContextPanel && (
        <SidePanel
          open={contextOpen}
          title={contextMessageId ? 'Context' : 'Live run'}
          pipeline={contextMessageId ? null : livePipeline}
          messageId={contextMessageId}
          onClose={() => setContextOpen(false)}
        />
      )}
    </div>
  );
}
