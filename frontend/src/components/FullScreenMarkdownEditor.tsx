import React, { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type EditorMode = 'edit' | 'preview';

const mdComponents: React.ComponentProps<typeof ReactMarkdown>['components'] = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline text-violet-600">
      {children}
    </a>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-5 mb-2">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 mb-2">{children}</ol>,
  li: ({ children }) => <li className="mb-1">{children}</li>,
  h1: ({ children }) => <h1 className="text-xl font-bold text-slate-100 mt-4 mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-lg font-bold text-slate-100 mt-3 mb-2">{children}</h2>,
  h3: ({ children }) => <h3 className="text-base font-semibold text-violet-700 mt-3 mb-1">{children}</h3>,
  code: ({ children }) => (
    <code className="rounded px-1 text-xs font-mono bg-slate-800 text-violet-300">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-violet-400 pl-3 my-2 text-slate-300 italic">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-slate-700" />,
};

export function FullScreenMarkdownEditor({
  open,
  title,
  subtitle,
  value,
  placeholder,
  canEdit,
  saving,
  onChange,
  onSave,
  onClose,
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  value: string;
  placeholder?: string;
  canEdit: boolean;
  saving: boolean;
  onChange: (next: string) => void;
  onSave: () => Promise<void> | void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<EditorMode>('edit');

  // Cmd+S / Ctrl+S to save while open
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      const key = String(e.key || '').toLowerCase();
      if (key !== 's') return;
      if (!(e.metaKey || e.ctrlKey)) return;
      e.preventDefault();
      if (!canEdit || saving) return;
      void onSave();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, canEdit, saving, onSave]);

  const headerSubtitle = useMemo(() => subtitle?.trim() || '', [subtitle]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-stretch justify-center">
      <div className="w-full max-w-6xl bg-slate-900 border border-slate-700 flex flex-col">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">Full-screen editor</div>
            <div className="text-sm font-semibold text-slate-100 truncate">{title}</div>
            {headerSubtitle && <div className="text-xs text-slate-500 truncate">{headerSubtitle}</div>}
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-600 bg-slate-900 p-0.5">
              <button
                type="button"
                onClick={() => setMode('edit')}
                className={`px-3 py-1.5 text-xs font-semibold rounded-md ${
                  mode === 'edit' ? 'bg-violet-600 text-white' : 'text-slate-300 hover:bg-slate-800'
                }`}
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => setMode('preview')}
                className={`px-3 py-1.5 text-xs font-semibold rounded-md ${
                  mode === 'preview' ? 'bg-violet-600 text-white' : 'text-slate-300 hover:bg-slate-800'
                }`}
              >
                Preview
              </button>
            </div>
            <button
              type="button"
              onClick={() => void onSave()}
              disabled={saving || !canEdit}
              className="px-3 py-2 text-xs font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800"
            >
              Close
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden">
          {mode === 'edit' ? (
            <textarea
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder}
              className="w-full h-full resize-none font-mono text-xs p-4 outline-none bg-slate-800 text-slate-100"
              readOnly={!canEdit}
            />
          ) : (
            <div className="h-full overflow-y-auto p-6 bg-slate-900">
              <div className="max-w-none prose prose-sm prose-invert">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {value || ''}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>

        {!canEdit && (
          <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-400 bg-slate-800">
            Read-only.
          </div>
        )}
      </div>
    </div>
  );
}

