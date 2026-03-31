import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import type { AgentId, UiAgent } from '../api/client';
import { getAgent, getPhase2IsAdmin, getPhase2IsSuperAdmin, getPhase2UserId, updateAgent } from '../api/client';
import { phase2Path } from '../constants';

type TabId = 'selector' | 'final';
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
  h1: ({ children }) => <h1 className="text-xl font-bold text-slate-900 mt-4 mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-lg font-bold text-slate-800 mt-3 mb-2">{children}</h2>,
  h3: ({ children }) => <h3 className="text-base font-semibold text-violet-700 mt-3 mb-1">{children}</h3>,
  code: ({ children }) => (
    <code className="rounded px-1 text-xs font-mono bg-slate-100 text-violet-700">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-violet-300 pl-3 my-2 text-slate-600 italic">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-slate-200" />,
};

export default function AgentContextsPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const id = (agentId ?? '') as AgentId;
  const isSuperAdmin = getPhase2IsSuperAdmin();
  const isAdmin = getPhase2IsAdmin();
  const currentUserId = getPhase2UserId();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [agent, setAgent] = useState<UiAgent | null>(null);

  const [tab, setTab] = useState<TabId>('selector');
  const [skillSelectorContext, setSkillSelectorContext] = useState('');
  const [finalOutputFormattingContext, setFinalOutputFormattingContext] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<EditorMode>('edit');

  const createdBy = agent?.createdByUserId ?? null;
  const isSystem = createdBy == null;
  const canEdit =
    !agent
      ? false
      : !isSystem
        ? (!!currentUserId && String(createdBy) === String(currentUserId))
        : (agent.isLocked ? !!isSuperAdmin : (!!isSuperAdmin || !!isAdmin));

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setErr(null);
    getAgent(id)
      .then(({ agent: a }) => {
        setAgent(a);
        setSkillSelectorContext(a.skillSelectorContext ?? '');
        setFinalOutputFormattingContext(a.finalOutputFormattingContext ?? '');
      })
      .catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load agent'))
      .finally(() => setLoading(false));
  }, [id]);

  const tabs = useMemo(
    () =>
      [
        { id: 'selector' as const, label: 'Skill selector context' },
        { id: 'final' as const, label: 'Final output formatting context' },
      ] as const,
    []
  );

  const current = tab === 'selector'
    ? { value: skillSelectorContext, setValue: setSkillSelectorContext }
    : { value: finalOutputFormattingContext, setValue: setFinalOutputFormattingContext };

  const placeholder =
    tab === 'selector'
      ? 'Used when selecting which skill to run next.\n\nExample:\n- Prefer scrape-playwright for JS-heavy sites.\n- Never call scrape-agentbrowser.\n- Always include the current user goal.'
      : 'Used to generate the final response from all gathered raw context.\n\nTip: if you want raw output, say: "Return the gathered context verbatim."';

  const handleSave = useCallback(async () => {
    if (!id) return;
    if (!canEdit) return;
    setSaving(true);
    setErr(null);
    try {
      const { agent: updated } = await updateAgent(id, {
        skillSelectorContext,
        finalOutputFormattingContext,
      });
      setAgent(updated);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }, [id, canEdit, skillSelectorContext, finalOutputFormattingContext]);

  // Cmd+S / Ctrl+S in full-screen editor
  useEffect(() => {
    if (!editorOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      const key = String(e.key || '').toLowerCase();
      if (key !== 's') return;
      if (!(e.metaKey || e.ctrlKey)) return;
      e.preventDefault(); // block browser "Save page"
      if (!canEdit) return;
      if (saving || loading) return;
      void handleSave();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [editorOpen, canEdit, saving, loading, handleSave]);

  if (!id) {
    return (
      <div className="p-6">
        <p className="text-sm text-slate-600">Missing agent id.</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-widest text-slate-400 font-semibold">Agent contexts</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xl">{agent?.emoji ?? '🤖'}</span>
            <h1 className="text-lg font-semibold text-slate-900 truncate">
              {agent?.name ?? id}
            </h1>
            <span className="text-xs text-slate-400 font-mono truncate">{id}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <NavLink
            to={phase2Path('agents')}
            className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
          >
            Back
          </NavLink>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || loading || !canEdit}
            className="px-3 py-2 text-xs font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
          Loading…
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
          <div className="flex items-center gap-1 border-b border-slate-200 bg-slate-50 px-2 py-2 overflow-x-auto">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap ${
                  tab === t.id
                    ? 'bg-white border border-slate-200 text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:bg-white/70'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="p-4 space-y-3">
            <p className="text-xs text-slate-500">
              This text is loaded from the database per agent. It will be used automatically when you chat with this agent id.
            </p>
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => {
                  setEditorMode('edit');
                  setEditorOpen(true);
                }}
                className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
              >
                Open full-screen editor
              </button>
              <span className="text-xs text-slate-400">
                {canEdit ? 'Editable' : 'Read-only'}
              </span>
            </div>
            <textarea
              value={current.value}
              onChange={(e) => current.setValue(e.target.value)}
              placeholder={placeholder}
              className="w-full min-h-[320px] font-mono text-xs rounded-xl border border-slate-200 bg-slate-50 p-3 outline-none focus:ring-2 focus:ring-violet-200"
              readOnly={!canEdit}
            />
            {!canEdit && !loading && (
              <p className="text-xs text-slate-500">
                Read-only: only the agent creator can edit. System agents follow admin/super-admin rules.
              </p>
            )}
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={async () => {
                  // Save current contexts, then go back to Agents list
                  await handleSave();
                  navigate('/agents');
                }}
                disabled={saving}
                className="text-xs text-slate-500 hover:text-slate-800 disabled:opacity-60"
              >
                Done
              </button>
              <span className="text-xs text-slate-400">
                {current.value.length.toLocaleString()} chars
              </span>
            </div>
          </div>
        </div>
      )}

      {editorOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-stretch justify-center">
          <div className="w-full max-w-6xl bg-white flex flex-col">
            <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">
                  Full-screen context editor
                </div>
                <div className="text-sm font-semibold text-slate-900 truncate">
                  {tab === 'selector' ? 'Skill selector context' : 'Final output formatting context'}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
                  <button
                    type="button"
                    onClick={() => setEditorMode('edit')}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md ${
                      editorMode === 'edit' ? 'bg-violet-600 text-white' : 'text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditorMode('preview')}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md ${
                      editorMode === 'preview' ? 'bg-violet-600 text-white' : 'text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    Preview
                  </button>
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    await handleSave();
                    setEditorOpen(false);
                  }}
                  disabled={saving || loading || !canEdit}
                  className="px-3 py-2 text-xs font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button
                  type="button"
                  onClick={() => setEditorOpen(false)}
                  className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
                >
                  Close
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-hidden">
              {editorMode === 'edit' ? (
                <textarea
                  value={current.value}
                  onChange={(e) => current.setValue(e.target.value)}
                  placeholder={placeholder}
                  className="w-full h-full resize-none font-mono text-xs p-4 outline-none bg-slate-50"
                  readOnly={!canEdit}
                />
              ) : (
                <div className="h-full overflow-y-auto p-6 bg-white">
                  <div className="max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {current.value || ''}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>

            {!canEdit && (
              <div className="px-4 py-2 border-t border-slate-200 text-xs text-slate-500 bg-slate-50">
                Read-only: only the agent creator can edit. System agents follow admin/super-admin rules.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

