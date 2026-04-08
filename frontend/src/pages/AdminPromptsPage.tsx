import React, { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { listPrompts, getPrompt, upsertPrompt, deletePrompt } from '../api/services/admin';
import type { PromptEntry } from '../api/types';

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

export default function AdminPromptsPage() {
  const [prompts, setPrompts] = useState<PromptEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);

  // Editor state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<EditorMode>('edit');
  const [editingPrompt, setEditingPrompt] = useState<PromptEntry | null>(null);
  const [formSlug, setFormSlug] = useState('');
  const [formName, setFormName] = useState('');
  const [formContent, setFormContent] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formCategory, setFormCategory] = useState('general');
  const [saving, setSaving] = useState(false);

  const categories = Array.from(new Set(prompts.map((p) => p.category))).sort();

  const loadPrompts = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const { prompts: list } = await listPrompts();
      setPrompts(list);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load prompts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  const handleEdit = async (slug: string) => {
    try {
      const { prompt } = await getPrompt(slug);
      setEditingPrompt(prompt);
      setFormSlug(prompt.slug);
      setFormName(prompt.name);
      setFormContent(prompt.content);
      setFormDescription(prompt.description);
      setFormCategory(prompt.category);
      setShowNewForm(false);
      setEditorOpen(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load prompt');
    }
  };

  const handleNew = () => {
    setEditingPrompt(null);
    setFormSlug('');
    setFormName('');
    setFormContent('');
    setFormDescription('');
    setFormCategory('general');
    setShowNewForm(true);
    setEditorOpen(true);
  };

  const handleSave = async () => {
    if (!formSlug.trim() || !formName.trim()) {
      setErr('Slug and name are required');
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await upsertPrompt(formSlug.trim(), {
        name: formName.trim(),
        content: formContent,
        description: formDescription.trim(),
        category: formCategory.trim() || 'general',
      });
      setEditorOpen(false);
      setShowNewForm(false);
      setEditingPrompt(null);
      await loadPrompts();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save prompt');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (slug: string) => {
    if (!confirm(`Delete prompt "${slug}"? This cannot be undone.`)) return;
    setErr(null);
    try {
      await deletePrompt(slug);
      await loadPrompts();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to delete prompt');
    }
  };

  // Cmd+S / Ctrl+S in full-screen editor
  useEffect(() => {
    if (!editorOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      const key = String(e.key || '').toLowerCase();
      if (key !== 's') return;
      if (!(e.metaKey || e.ctrlKey)) return;
      e.preventDefault();
      if (saving) return;
      void handleSave();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [editorOpen, saving, formSlug, formName, formContent, formDescription, formCategory]);

  const groupedPrompts = prompts.reduce<Record<string, PromptEntry[]>>((acc, p) => {
    if (!acc[p.category]) acc[p.category] = [];
    acc[p.category].push(p);
    return acc;
  }, {});

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-500 font-semibold">Admin</p>
          <h1 className="text-xl font-bold text-slate-100">Prompts</h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage system prompts used across backend services
          </p>
        </div>
        <button
          type="button"
          onClick={handleNew}
          className="px-4 py-2 text-sm font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700"
        >
          + New Prompt
        </button>
      </div>

      {err && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/15 px-3 py-2 text-sm text-red-300">
          {err}
          <button onClick={() => setErr(null)} className="ml-2 text-red-400 hover:text-red-200">×</button>
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-slate-700 bg-slate-900 p-6 text-center">
          <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-slate-400 mt-2">Loading prompts…</p>
        </div>
      ) : prompts.length === 0 ? (
        <div className="rounded-xl border border-slate-700 bg-slate-900 p-6 text-center">
          <p className="text-slate-400">No prompts found.</p>
          <button
            type="button"
            onClick={handleNew}
            className="mt-3 px-4 py-2 text-sm font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700"
          >
            Create your first prompt
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(groupedPrompts).map(([category, categoryPrompts]) => (
            <div key={category} className="rounded-xl border border-slate-700 bg-slate-900 overflow-hidden">
              <div className="px-4 py-3 bg-slate-800 border-b border-slate-700">
                <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">
                  📁 {category}
                </h2>
              </div>
              <div className="divide-y divide-slate-800">
                {categoryPrompts.map((prompt) => (
                  <div
                    key={prompt.slug}
                    className="px-4 py-3 hover:bg-slate-800/50 cursor-pointer flex items-center justify-between gap-4"
                    onClick={() => handleEdit(prompt.slug)}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-100">{prompt.name}</span>
                        <code className="text-xs bg-slate-800 px-1.5 py-0.5 rounded text-violet-300">
                          {prompt.slug}
                        </code>
                      </div>
                      {prompt.description && (
                        <p className="text-xs text-slate-400 mt-1 truncate">{prompt.description}</p>
                      )}
                      <p className="text-xs text-slate-500 mt-1">
                        {prompt.content.length.toLocaleString()} chars • Updated {new Date(prompt.updatedAt).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEdit(prompt.slug);
                        }}
                        className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(prompt.slug);
                        }}
                        className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-red-600/50 text-red-400 hover:bg-red-900/30"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Full-screen editor modal */}
      {editorOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-stretch justify-center">
          <div className="w-full max-w-6xl bg-slate-900 border border-slate-700 flex flex-col">
            <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">
                  {editingPrompt ? 'Edit Prompt' : 'New Prompt'}
                </div>
                <div className="flex items-center gap-3 mt-1">
                  {showNewForm && !editingPrompt ? (
                    <input
                      type="text"
                      value={formSlug}
                      onChange={(e) => setFormSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))}
                      placeholder="prompt-slug"
                      className="w-40 px-2 py-1 text-sm rounded border border-slate-600 bg-slate-800 text-slate-100 outline-none focus:ring-2 focus:ring-violet-500"
                    />
                  ) : (
                    <code className="text-sm bg-slate-800 px-2 py-1 rounded text-violet-300">{formSlug}</code>
                  )}
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="Prompt Name"
                    className="flex-1 px-2 py-1 text-sm rounded border border-slate-600 bg-slate-800 text-slate-100 outline-none focus:ring-2 focus:ring-violet-500"
                  />
                  <input
                    type="text"
                    value={formCategory}
                    onChange={(e) => setFormCategory(e.target.value)}
                    placeholder="category"
                    list="category-list"
                    className="w-32 px-2 py-1 text-sm rounded border border-slate-600 bg-slate-800 text-slate-100 outline-none focus:ring-2 focus:ring-violet-500"
                  />
                  <datalist id="category-list">
                    {categories.map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="inline-flex rounded-lg border border-slate-600 bg-slate-900 p-0.5">
                  <button
                    type="button"
                    onClick={() => setEditorMode('edit')}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md ${
                      editorMode === 'edit' ? 'bg-violet-600 text-white' : 'text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditorMode('preview')}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md ${
                      editorMode === 'preview' ? 'bg-violet-600 text-white' : 'text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    Preview
                  </button>
                </div>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="px-3 py-2 text-xs font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditorOpen(false);
                    setShowNewForm(false);
                    setEditingPrompt(null);
                  }}
                  className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800"
                >
                  Close
                </button>
              </div>
            </div>

            {/* Description input */}
            <div className="px-4 py-2 border-b border-slate-700 bg-slate-800/50">
              <input
                type="text"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                placeholder="Description (optional)"
                className="w-full px-2 py-1 text-sm rounded border border-slate-600 bg-slate-800 text-slate-100 outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>

            <div className="flex-1 overflow-hidden">
              {editorMode === 'edit' ? (
                <textarea
                  value={formContent}
                  onChange={(e) => setFormContent(e.target.value)}
                  placeholder="Enter your prompt content here (supports markdown)..."
                  className="w-full h-full resize-none font-mono text-xs p-4 outline-none bg-slate-800 text-slate-100"
                />
              ) : (
                <div className="h-full overflow-y-auto p-6 bg-slate-900">
                  <div className="max-w-none prose prose-sm prose-invert">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {formContent || '*No content yet*'}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>

            <div className="px-4 py-2 border-t border-slate-700 bg-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                Press Cmd/Ctrl+S to save
              </span>
              <span className="text-xs text-slate-500">
                {formContent.length.toLocaleString()} characters
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

