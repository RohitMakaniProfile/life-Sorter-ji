import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listAdminUsers, deleteAdminUser } from '../api';
import type { AdminUser } from '../api/types';

const PAGE_SIZE = 50;

// ── Main page ────────────────────────────────────────────────────────────────

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const load = useCallback(async (q: string, off: number) => {
    setLoading(true);
    setErr(null);
    try {
      const res = await listAdminUsers(q || undefined, PAGE_SIZE, off);
      setUsers(res.users);
      setTotal(res.total);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(debouncedQuery, offset);
  }, [load, debouncedQuery, offset]);

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setOffset(0);
      setDebouncedQuery(value);
    }, 350);
  };

  const openDeleteModal = (e: React.MouseEvent, user: AdminUser) => {
    e.stopPropagation();
    setDeleteTarget(user);
    setDeleteConfirmText('');
    setDeleteErr(null);
  };

  const closeDeleteModal = () => {
    if (deleting) return;
    setDeleteTarget(null);
    setDeleteConfirmText('');
    setDeleteErr(null);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteErr(null);
    try {
      await deleteAdminUser(deleteTarget.id);
      setDeleteTarget(null);
      setDeleteConfirmText('');
      await load(debouncedQuery, offset);
    } catch (e) {
      setDeleteErr(e instanceof Error ? e.message : 'Failed to delete user');
    } finally {
      setDeleting(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const deleteLabel = deleteTarget?.email || deleteTarget?.phone_number || deleteTarget?.id || '';
  const deleteConfirmReady = deleteConfirmText.trim() === 'DELETE';

  return (
    <div className="h-full overflow-hidden">
      <div className="overflow-y-auto h-full p-6 sm:p-8">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-xl font-bold text-slate-100">Users</h1>
              <p className="text-sm text-slate-500 mt-1">
                All registered users &mdash; {total.toLocaleString()} total
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm">🔍</span>
                <input
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  placeholder="Search by email, phone, or name..."
                  className="pl-9 pr-4 py-2 rounded-xl border border-slate-700 bg-slate-900 text-sm text-slate-100 outline-none focus:border-violet-500 w-72"
                />
              </div>
              {loading && (
                <div className="w-4 h-4 border-2 border-violet-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
              )}
            </div>
          </div>

          {err && (
            <div className="mt-4 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
              {err}
            </div>
          )}

          <div className="mt-6 overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-900">
                <tr>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">User</th>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Phone</th>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Provider</th>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Joined</th>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Last Login</th>
                  <th className="text-right px-4 py-3 text-slate-400 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950">
                {!loading && users.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-500">
                      {debouncedQuery ? 'No users match your search.' : 'No users found.'}
                    </td>
                  </tr>
                ) : (
                  users.map((u) => (
                    <tr
                      key={u.id}
                      onClick={() => navigate(`/admin/users/${u.id}`, { state: { user: u } })}
                      className="cursor-pointer transition-colors hover:bg-slate-900/60"
                    >
                      <td className="px-4 py-3">
                        <div>
                          <p className="text-slate-100 font-medium">
                            {u.email || u.phone_number || 'Unknown'}
                          </p>
                          {u.name && <p className="text-xs text-slate-400">{u.name}</p>}
                          <p className="text-xs text-slate-600 font-mono mt-0.5">{u.id.slice(0, 8)}…</p>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {u.phone_number || <span className="text-slate-600">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded font-mono">
                          {u.auth_provider || '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                        {u.last_login_at
                          ? new Date(u.last_login_at).toLocaleString()
                          : <span className="text-slate-600">Never</span>}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={(e) => openDeleteModal(e, u)}
                          className="px-3 py-1.5 rounded-lg bg-red-500/15 text-red-400 text-xs font-medium hover:bg-red-500/25 transition-colors"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
              <span>Page {currentPage} of {totalPages} &middot; {total.toLocaleString()} users</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={closeDeleteModal}
        >
          <div
            className="relative w-full max-w-md mx-4 rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3 mb-5">
              <div className="w-10 h-10 rounded-xl bg-red-500/20 flex items-center justify-center flex-shrink-0 text-xl">
                ⚠️
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-100">Delete User — Irreversible</h2>
                <p className="text-xs text-slate-400 mt-1">
                  Permanently deletes the user and all their data: conversations, messages,
                  onboarding, plan grants, and payment records.
                </p>
              </div>
            </div>

            <div className="rounded-lg bg-slate-800 px-4 py-3 mb-5 text-sm">
              <p className="text-slate-400 text-xs mb-1">User to be deleted</p>
              <p className="text-slate-100 font-semibold">{deleteLabel}</p>
              <p className="text-xs text-slate-500 font-mono mt-0.5">{deleteTarget.id}</p>
            </div>

            <div className="mb-5">
              <label className="text-xs text-slate-400 mb-1.5 block">
                Type <span className="font-bold text-slate-200">DELETE</span> to confirm
              </label>
              <input
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder="DELETE"
                autoFocus
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-2.5 text-sm text-slate-100 outline-none focus:border-red-500 font-mono"
              />
            </div>

            {deleteErr && (
              <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
                {deleteErr}
              </div>
            )}

            <div className="flex gap-3">
              <button
                type="button"
                onClick={closeDeleteModal}
                disabled={deleting}
                className="flex-1 px-4 py-2.5 rounded-xl border border-slate-700 text-slate-300 text-sm font-medium hover:bg-slate-800 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!deleteConfirmReady || deleting}
                onClick={handleDelete}
                className="flex-1 px-4 py-2.5 rounded-xl bg-red-600 text-white text-sm font-semibold hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {deleting ? 'Deleting…' : 'Delete User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}