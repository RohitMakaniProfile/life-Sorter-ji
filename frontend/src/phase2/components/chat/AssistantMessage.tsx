import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RichMessage } from '../../types';
import React, { useEffect, useState } from 'react';

const REPORT_THRESHOLD = 500;

export default function AssistantMessage({
  message,
  isLast,
  loading,
  onOpenContext,
  onApprovePlan,
}: {
  message: RichMessage;
  isLast: boolean;
  loading: boolean;
  onOpenContext?: (messageId: string) => void;
  onApprovePlan?: (planId: string, planMarkdown: string) => Promise<void>;
}) {
  const isEmpty = !message.content?.trim();

  // ==============================
  // 🤖 THINKING STATE
  // ==============================
  if (isEmpty && loading && isLast) {
    return (
      <div className="bg-white border rounded-xl p-4 max-w-[70%] flex items-center gap-2">
        <span className="text-sm text-slate-500">Thinking</span>

        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    );
  }

  // ==============================
  // ❌ SKIP EMPTY MESSAGE
  // ==============================
  if (isEmpty) return null;

  // ==============================
  // NORMAL MESSAGE
  // ==============================
  if (message.kind === 'plan' && message.planId) {
    const [draft, setDraft] = useState(message.content);
    const [saving, setSaving] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [editing, setEditing] = useState(false);

    useEffect(() => {
      setDraft(message.content);
    }, [message.content]);

    return (
      <div className="bg-white border rounded-xl p-4 max-w-[70%] w-full">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="text-sm font-semibold text-slate-800">Todo (edit then start working)</div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="shrink-0 text-[11px] font-semibold text-violet-600 hover:text-violet-700"
            >
              {expanded ? 'Collapse' : 'Expand'}
            </button>
            {message.messageId && onOpenContext && (
              <button
                type="button"
                onClick={() => onOpenContext(message.messageId!)}
                className="shrink-0 text-[11px] font-semibold text-violet-600 hover:text-violet-700"
              >
                Context
              </button>
            )}
          </div>
        </div>

        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={expanded ? 16 : 10}
            className="w-full resize-y rounded-lg border border-slate-200 p-3 text-sm font-mono bg-slate-50 text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
        ) : (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {expanded ? draft : draft.slice(0, 700)}
            </ReactMarkdown>
          </div>
        )}

        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-semibold text-violet-600 hover:text-violet-700"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        </div>

        <div className="flex items-center justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="px-3 py-2 rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            {editing ? 'Done editing' : 'Edit todo'}
          </button>
          <button
            type="button"
            disabled={!onApprovePlan || saving}
            onClick={async () => {
              if (!onApprovePlan) return;
              setSaving(true);
              try {
                await onApprovePlan(message.planId!, draft);
              } finally {
                setSaving(false);
              }
            }}
            className="px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
          >
            {saving ? 'Starting…' : 'Start working'}
          </button>
        </div>
      </div>
    );
  }

  const isReport = message.content.length > REPORT_THRESHOLD;
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (isLast) setExpanded(loading);
  }, [loading, isLast]);

  return (
    <div className="bg-white border rounded-xl p-4 max-w-[70%]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1" />
        {message.messageId && onOpenContext && (
          <button
            type="button"
            onClick={() => onOpenContext(message.messageId!)}
            className="shrink-0 text-[11px] font-semibold text-violet-600 hover:text-violet-700"
            title="Open context panel for this message"
          >
            Context
          </button>
        )}
      </div>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {expanded || !isReport
          ? message.content
          : message.content.slice(0, 500)}
      </ReactMarkdown>

      {isReport && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-violet-600 mt-2"
        >
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      )}
    </div>
  );
}