import { useEffect, useMemo, useRef, useState } from 'react';
import { listSystemConfig, upsertSystemConfigEntry } from '../api';
import type { ConfigValueType, SystemConfigEntry } from '../api/types';
import FullScreenMarkdownEditor from '../components/FullScreenMarkdownEditor';

export default function AdminSystemConfigPage() {
  const [entries, setEntries] = useState<SystemConfigEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [filter, setFilter] = useState('');

  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return entries;
    return entries.filter((e) => e.key.toLowerCase().includes(f) || e.description.toLowerCase().includes(f));
  }, [entries, filter]);

  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [editType, setEditType] = useState<ConfigValueType>('string');
  const [editDescription, setEditDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [newType, setNewType] = useState<ConfigValueType>('string');
  const [newDescription, setNewDescription] = useState('');
  const [adding, setAdding] = useState(false);
  const [addErr, setAddErr] = useState<string | null>(null);

  const [markdownOpen, setMarkdownOpen] = useState(false);
  const [markdownMode, setMarkdownMode] = useState<'edit' | 'preview'>('edit');
  const [jsonArrayMode, setJsonArrayMode] = useState(true);
  const editorCardRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    listSystemConfig()
      .then((r) => setEntries(r.entries || []))
      .catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load config'))
      .finally(() => setLoading(false));
  }, []);

  function startEdit(e: SystemConfigEntry) {
    setEditingKey(e.key);
    setEditValue(e.value);
    setEditType((e.type || 'string') as ConfigValueType);
    setEditDescription(e.description);
    setSaveErr(null);
    setSaveOk(false);
    requestAnimationFrame(() => editorCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }

  function parseJsonArray(value: string): string[] {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map((x) => String(x));
      return [];
    } catch {
      return [];
    }
  }

  function setJsonArray(next: string[]) {
    setEditValue(JSON.stringify(next, null, 2));
  }

  function renderTypedEditor(isNew = false) {
    const type = isNew ? newType : editType;
    const value = isNew ? newValue : editValue;
    const setValue = isNew ? setNewValue : setEditValue;
    if (type === 'boolean') {
      const boolValue = ['true', '1', 'yes', 'on'].includes(String(value).trim().toLowerCase());
      return (
        <select
          value={boolValue ? 'true' : 'false'}
          onChange={(e) => setValue(e.target.value)}
          className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      );
    }
    if (type === 'number') {
      return (
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          type="number"
          className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
        />
      );
    }
    if (type === 'markdown') {
      return (
        <>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={7}
            className="mt-1 w-full resize-none rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
          />
          <button
            type="button"
            onClick={() => { setMarkdownMode('edit'); setMarkdownOpen(true); }}
            className="mt-2 px-3 py-2 text-xs font-semibold rounded-lg border border-slate-700 text-slate-200"
          >
            Open full-screen editor
          </button>
        </>
      );
    }
    if (type === 'json' && !isNew) {
      const arr = parseJsonArray(editValue);
      return (
        <>
          <div className="mt-1 flex items-center gap-2">
            <button type="button" onClick={() => setJsonArrayMode(true)} className={`px-3 py-1 rounded ${jsonArrayMode ? 'bg-violet-700 text-white' : 'bg-slate-800 text-slate-300'}`}>Array editor</button>
            <button type="button" onClick={() => setJsonArrayMode(false)} className={`px-3 py-1 rounded ${!jsonArrayMode ? 'bg-violet-700 text-white' : 'bg-slate-800 text-slate-300'}`}>Raw JSON</button>
          </div>
          {jsonArrayMode ? (
            <div className="mt-2 space-y-2">
              {arr.map((item, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    value={item}
                    onChange={(e) => {
                      const next = arr.slice();
                      next[idx] = e.target.value;
                      setJsonArray(next);
                    }}
                    className="w-full rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none"
                  />
                  <button type="button" onClick={() => setJsonArray(arr.filter((_, i) => i !== idx))} className="px-2 py-2 text-xs rounded bg-red-900/40 text-red-200">Remove</button>
                </div>
              ))}
              <button type="button" onClick={() => setJsonArray([...arr, ''])} className="px-3 py-2 text-xs rounded bg-slate-800 text-slate-100">+ Add item</button>
            </div>
          ) : (
            <textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              rows={7}
              className="mt-2 w-full resize-none rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
            />
          )}
        </>
      );
    }
    return (
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={7}
        className="mt-1 w-full resize-none rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
      />
    );
  }

  async function handleSave() {
    if (!editingKey) return;
    setSaving(true);
    setSaveErr(null);
    setSaveOk(false);
    try {
      const r = await upsertSystemConfigEntry(editingKey, {
        value: editValue,
        type: editType,
        description: editDescription,
      });
      const updated = r.entry;
      setEntries((prev) => {
        const idx = prev.findIndex((x) => x.key === updated.key);
        if (idx >= 0) {
          const copy = prev.slice();
          copy[idx] = updated;
          return copy;
        }
        return [...prev, updated].sort((a, b) => a.key.localeCompare(b.key));
      });
      setSaveOk(true);
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : 'Failed to save config');
    } finally {
      setSaving(false);
    }
  }

  async function handleAdd() {
    const k = newKey.trim();
    if (!k) return;
    setAdding(true);
    setAddErr(null);
    try {
      const r = await upsertSystemConfigEntry(k, { value: newValue, type: newType, description: newDescription });
      const created = r.entry;
      setEntries((prev) => [...prev, created].sort((a, b) => a.key.localeCompare(b.key)));
      setNewKey('');
      setNewValue('');
      setNewDescription('');
      setEditingKey(created.key);
      setEditValue(created.value);
      setEditType((created.type || 'string') as ConfigValueType);
      setEditDescription(created.description);
      setSaveErr(null);
      setSaveOk(true);
    } catch (e) {
      setAddErr(e instanceof Error ? e.message : 'Failed to add config key');
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-xl font-bold text-slate-100">System Config Manager</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage rows in the backend&apos;s `system_config` table. Changes take effect immediately for new requests.
        </p>

        <div className="mt-6 flex items-center gap-3">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by key or description…"
            className="w-full rounded-xl border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-100 outline-none"
          />
        </div>

        {loading ? (
          <div className="text-center py-16 text-slate-500">
            <div className="inline-block w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mb-3" />
            <p className="font-medium">Loading…</p>
          </div>
        ) : err ? (
          <div className="mt-5 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {err}
          </div>
        ) : (
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-6">
            <div className="rounded-xl border border-slate-800 overflow-hidden">
              <div className="bg-slate-900 px-4 py-3 text-sm font-semibold text-slate-200">
                Config entries ({filtered.length})
              </div>
              <div className="max-h-[70vh] overflow-y-auto divide-y divide-slate-800 bg-slate-950">
                {filtered.map((e) => (
                  <button
                    key={e.key}
                    type="button"
                    onClick={() => startEdit(e)}
                    className={`w-full text-left px-4 py-3 hover:bg-slate-900 transition-colors ${
                      editingKey === e.key ? 'bg-slate-900' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-mono text-sm text-slate-100">{e.key}</div>
                        <div className="text-[11px] text-violet-300 mt-1">type: {e.type || 'string'}</div>
                        <div className="text-xs text-slate-500 mt-1">{e.description || ''}</div>
                      </div>
                      <div className="text-[11px] text-slate-600">{e.updatedAt ? `Updated: ${e.updatedAt}` : ''}</div>
                    </div>
                  </button>
                ))}

                {filtered.length === 0 && (
                  <div className="px-4 py-6 text-sm text-slate-500">No matching entries.</div>
                )}
              </div>
            </div>

            <div ref={editorCardRef} className="rounded-xl border border-slate-800 p-4 bg-slate-950">
              <div className="text-sm font-semibold text-slate-200">Editor</div>
              <div className="text-xs text-slate-500 mt-1">
                Tip: edit `auth.super_admin_emails` (JSON array or comma-separated emails).
              </div>

              <div className="mt-4">
                <label className="text-xs text-slate-400">Key</label>
                <input
                  disabled
                  value={editingKey ?? ''}
                  className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-300 outline-none"
                />
              </div>

              <div className="mt-4">
                <label className="text-xs text-slate-400">Value</label>
                <div className={!editingKey ? 'pointer-events-none opacity-60' : ''}>
                  {renderTypedEditor(false)}
                </div>
              </div>

              <div className="mt-4">
                <label className="text-xs text-slate-400">Type</label>
                <select
                  disabled={!editingKey}
                  value={editType}
                  onChange={(e) => setEditType(e.target.value as ConfigValueType)}
                  className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                >
                  <option value="string">string</option>
                  <option value="number">number</option>
                  <option value="boolean">boolean</option>
                  <option value="json">json</option>
                  <option value="markdown">markdown</option>
                </select>
              </div>

              <div className="mt-4">
                <label className="text-xs text-slate-400">Description</label>
                <textarea
                  disabled={!editingKey}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={3}
                  className="mt-1 w-full resize-none rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                />
              </div>

              <div className="mt-4 flex items-center gap-3">
                <button
                  type="button"
                  disabled={!editingKey || saving}
                  onClick={handleSave}
                  className="flex items-center justify-center px-4 py-2 rounded-xl bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
                {saveOk && <div className="text-sm text-emerald-300 font-semibold">Saved.</div>}
              </div>

              {saveErr && (
                <div className="mt-3 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
                  {saveErr}
                </div>
              )}

              <div className="mt-6 border-t border-slate-800 pt-4">
                <div className="text-sm font-semibold text-slate-200">Add new key</div>
                <div className="text-xs text-slate-500 mt-1">Upsert creates the row if it doesn&apos;t exist.</div>

                <div className="mt-3">
                  <label className="text-xs text-slate-400">Key</label>
                  <input
                    value={newKey}
                    onChange={(e) => setNewKey(e.target.value)}
                    placeholder="e.g. auth.super_admin_emails"
                    className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                  />
                </div>

                <div className="mt-3">
                  <label className="text-xs text-slate-400">Value</label>
                  {renderTypedEditor(true)}
                </div>

                <div className="mt-3">
                  <label className="text-xs text-slate-400">Type</label>
                  <select
                    value={newType}
                    onChange={(e) => setNewType(e.target.value as ConfigValueType)}
                    className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                  >
                    <option value="string">string</option>
                    <option value="number">number</option>
                    <option value="boolean">boolean</option>
                    <option value="json">json</option>
                    <option value="markdown">markdown</option>
                  </select>
                </div>

                <div className="mt-3">
                  <label className="text-xs text-slate-400">Description</label>
                  <input
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="Optional description"
                    className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                  />
                </div>

                <div className="mt-3">
                  <button
                    type="button"
                    disabled={!newKey.trim() || adding}
                    onClick={handleAdd}
                    className="flex items-center justify-center w-full px-4 py-2 rounded-xl bg-slate-800 text-slate-100 text-sm font-semibold hover:bg-slate-700 disabled:opacity-50"
                  >
                    {adding ? 'Adding…' : 'Add / Upsert'}
                  </button>
                </div>

                {addErr && (
                  <div className="mt-3 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
                    {addErr}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
      <FullScreenMarkdownEditor
        open={markdownOpen}
        title={editingKey ? `Edit markdown: ${editingKey}` : 'Markdown editor'}
        value={editValue}
        mode={markdownMode}
        saving={saving}
        canEdit
        onChange={setEditValue}
        onModeChange={setMarkdownMode}
        onSave={handleSave}
        onClose={() => setMarkdownOpen(false)}
      />
    </div>
  );
}

