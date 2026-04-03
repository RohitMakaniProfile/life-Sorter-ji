import { useEffect, useMemo, useState } from 'react';
import { listSystemConfig, upsertSystemConfigEntry } from '../api';
import type { SystemConfigEntry } from '../api/types';

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
  const [editDescription, setEditDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [adding, setAdding] = useState(false);
  const [addErr, setAddErr] = useState<string | null>(null);

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
    setEditDescription(e.description);
    setSaveErr(null);
    setSaveOk(false);
  }

  async function handleSave() {
    if (!editingKey) return;
    setSaving(true);
    setSaveErr(null);
    setSaveOk(false);
    try {
      const r = await upsertSystemConfigEntry(editingKey, {
        value: editValue,
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
      const r = await upsertSystemConfigEntry(k, { value: newValue, description: newDescription });
      const created = r.entry;
      setEntries((prev) => [...prev, created].sort((a, b) => a.key.localeCompare(b.key)));
      setNewKey('');
      setNewValue('');
      setNewDescription('');
      setEditingKey(created.key);
      setEditValue(created.value);
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

            <div className="rounded-xl border border-slate-800 p-4 bg-slate-950">
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
                <textarea
                  disabled={!editingKey}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  rows={7}
                  className="mt-1 w-full resize-none rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                />
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
                  <textarea
                    value={newValue}
                    onChange={(e) => setNewValue(e.target.value)}
                    rows={5}
                    className="mt-1 w-full resize-none rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-sm text-slate-100 outline-none"
                  />
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
    </div>
  );
}

