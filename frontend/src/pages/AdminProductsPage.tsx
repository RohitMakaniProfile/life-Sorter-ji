import { useEffect, useMemo, useState } from 'react';
import type { Product } from '../api/types';
import {
  createAdminProduct,
  deleteAdminProduct,
  listAdminProducts,
  updateAdminProduct,
} from '../api/services/admin';

const EMPTY_PRODUCT: Product = {
  id: '',
  name: '',
  emoji: '🧩',
  description: '',
  color: '#857BFF',
  outcome: '',
  domain: '',
  task: '',
  isActive: true,
  sortOrder: 0,
};

export default function AdminProductsPage() {
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<Product>(EMPTY_PRODUCT);

  const sortedProducts = useMemo(
    () => [...products].sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0)),
    [products],
  );

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await listAdminProducts();
      setProducts(Array.isArray(res.products) ? res.products : []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load products');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const patchLocal = (id: string, patch: Partial<Product>) => {
    setProducts((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  };

  const savePatch = async (id: string, patch: Partial<Product>) => {
    setSavingId(id);
    setError('');
    try {
      const res = await updateAdminProduct(id, patch);
      patchLocal(id, res.product);
    } catch (e: any) {
      setError(e?.message || 'Failed to update product');
      await load();
    } finally {
      setSavingId(null);
    }
  };

  const createProduct = async () => {
    if (!draft.id || !draft.name || !draft.outcome || !draft.domain || !draft.task) {
      setError('id, name, outcome, domain, and task are required');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const res = await createAdminProduct(draft);
      setProducts((prev) => [res.product, ...prev]);
      setDraft(EMPTY_PRODUCT);
    } catch (e: any) {
      setError(e?.message || 'Failed to create product');
    } finally {
      setCreating(false);
    }
  };

  const removeProduct = async (id: string) => {
    if (!window.confirm(`Delete product ${id}?`)) return;
    setSavingId(id);
    setError('');
    try {
      await deleteAdminProduct(id);
      setProducts((prev) => prev.filter((p) => p.id !== id));
    } catch (e: any) {
      setError(e?.message || 'Failed to delete product');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="mx-auto max-w-6xl space-y-5">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Products</h1>
          <p className="mt-1 text-sm text-slate-400">
            Manage onboarding product cards. Each product maps to `outcome`, `domain`, and `task`.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">Create product</div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-5">
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="id" value={draft.id} onChange={(e) => setDraft((d) => ({ ...d, id: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="name" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="emoji" value={draft.emoji} onChange={(e) => setDraft((d) => ({ ...d, emoji: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="color (#857BFF)" value={draft.color} onChange={(e) => setDraft((d) => ({ ...d, color: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="sort order" type="number" value={draft.sortOrder ?? 0} onChange={(e) => setDraft((d) => ({ ...d, sortOrder: Number(e.target.value) || 0 }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:col-span-2" placeholder="outcome (e.g. lead-generation)" value={draft.outcome} onChange={(e) => setDraft((d) => ({ ...d, outcome: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:col-span-3" placeholder="domain" value={draft.domain} onChange={(e) => setDraft((d) => ({ ...d, domain: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:col-span-5" placeholder="task" value={draft.task} onChange={(e) => setDraft((d) => ({ ...d, task: e.target.value }))} />
            <input className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:col-span-4" placeholder="description" value={draft.description} onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
            <button
              type="button"
              disabled={creating}
              onClick={() => void createProduct()}
              className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-60"
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-700 bg-slate-900">
          {loading ? (
            <div className="p-5 text-sm text-slate-400">Loading products...</div>
          ) : (
            <table className="min-w-full text-sm">
              <thead className="bg-slate-800 text-slate-300">
                <tr>
                  <th className="px-3 py-2 text-left">ID</th>
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Mapping</th>
                  <th className="px-3 py-2 text-left">Active</th>
                  <th className="px-3 py-2 text-left">Order</th>
                  <th className="px-3 py-2 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-200">
                {sortedProducts.map((p) => (
                  <tr key={p.id}>
                    <td className="px-3 py-2 font-mono text-xs">{p.id}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span>{p.emoji || '🧩'}</span>
                        <input
                          className="w-44 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm"
                          value={p.name}
                          onChange={(e) => patchLocal(p.id, { name: e.target.value })}
                          onBlur={() => void savePatch(p.id, { name: p.name })}
                        />
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="space-y-1">
                        <input className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" value={p.outcome} onChange={(e) => patchLocal(p.id, { outcome: e.target.value })} onBlur={() => void savePatch(p.id, { outcome: p.outcome })} />
                        <input className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" value={p.domain} onChange={(e) => patchLocal(p.id, { domain: e.target.value })} onBlur={() => void savePatch(p.id, { domain: p.domain })} />
                        <input className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" value={p.task} onChange={(e) => patchLocal(p.id, { task: e.target.value })} onBlur={() => void savePatch(p.id, { task: p.task })} />
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => void savePatch(p.id, { isActive: !p.isActive })}
                        className={`rounded px-2 py-1 text-xs font-semibold ${p.isActive ? 'bg-emerald-600/20 text-emerald-300' : 'bg-slate-700 text-slate-300'}`}
                      >
                        {p.isActive ? 'Active' : 'Inactive'}
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1"
                        value={p.sortOrder ?? 0}
                        onChange={(e) => patchLocal(p.id, { sortOrder: Number(e.target.value) || 0 })}
                        onBlur={() => void savePatch(p.id, { sortOrder: p.sortOrder ?? 0 })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        disabled={savingId === p.id}
                        onClick={() => void removeProduct(p.id)}
                        className="rounded border border-red-500/40 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

