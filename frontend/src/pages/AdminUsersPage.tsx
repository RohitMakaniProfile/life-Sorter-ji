import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listAdminUsers, deleteAdminUser, listUserOnboardings } from '../api';
import type { AdminUser, AdminUserOnboarding } from '../api/types';

const PAGE_SIZE = 50;
const ONBOARDINGS_PAGE = 10;

// ── Playbook status badge ───────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const s = status || '';
  const cls =
    s === 'complete'
      ? 'bg-emerald-500/20 text-emerald-300'
      : s === 'error'
      ? 'bg-red-500/20 text-red-300'
      : s === 'generating'
      ? 'bg-blue-500/20 text-blue-300'
      : 'bg-amber-500/20 text-amber-300';
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {s ? s.toUpperCase() : 'NOT STARTED'}
    </span>
  );
}

// ── User onboardings panel ──────────────────────────────────────────────────

function UserOnboardingsPanel({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const navigate = useNavigate();
  const [onboardings, setOnboardings] = useState<AdminUserOnboarding[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async (off: number) => {
    setLoading(true);
    setErr(null);
    try {
      const res = await listUserOnboardings(user.id, ONBOARDINGS_PAGE, off);
      if (off === 0) {
        setOnboardings(res.onboardings);
      } else {
        setOnboardings((prev) => [...prev, ...res.onboardings]);
      }
      setTotal(res.total);
      setOffset(off + res.onboardings.length);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [user.id]);

  useEffect(() => {
    setOffset(0);
    setOnboardings([]);
    load(0);
  }, [load]);

  const hasMore = onboardings.length < total;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-slate-800 flex-shrink-0">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-100 truncate">
            {user.email || user.phone_number || 'User'}
          </p>
          <p className="text-xs text-slate-500 font-mono mt-0.5 truncate">{user.id}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-slate-400 hover:text-slate-100 flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-lg hover:bg-slate-800"
        >
          ✕
        </button>
      </div>

      <div className="px-4 py-2 border-b border-slate-800 flex-shrink-0">
        <p className="text-[11px] text-slate-500 uppercase tracking-widest font-semibold">
          Onboarding Sessions {total > 0 ? `(${total})` : ''}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {err && (
          <div className="m-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
            {err}
          </div>
        )}

        {!loading && onboardings.length === 0 && !err && (
          <div className="py-12 text-center text-slate-500 text-sm">No onboarding sessions found.</div>
        )}

        <div className="divide-y divide-slate-800">
          {onboardings.map((o) => (
            <button
              key={o.id}
              type="button"
              onClick={() => navigate(`/admin/onboarding/${o.id}/token-usage`)}
              className="w-full text-left px-4 py-3 hover:bg-slate-800/60 transition-colors"
            >
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <span className="text-xs font-semibold text-slate-100 truncate flex-1">
                  {o.task || o.domain || o.outcome || 'Onboarding'}
                </span>
                <StatusBadge status={o.playbookStatus} />
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
                <span title="Onboarding ID">ID: {o.id.slice(0, 12)}…</span>
                {o.outcome && <span>🎯 {o.outcome}</span>}
                {o.createdAt && <span>{new Date(o.createdAt).toLocaleDateString()}</span>}
              </div>
              {o.websiteUrl && (
                <p className="text-[10px] text-slate-600 truncate mt-1">🌐 {o.websiteUrl}</p>
              )}
            </button>
          ))}
        </div>

        <div className="px-4 py-3">
          {loading ? (
            <div className="flex justify-center py-4">
              <div className="w-4 h-4 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : hasMore ? (
            <button
              type="button"
              onClick={() => load(offset)}
              className="w-full py-2 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800"
            >
              Load more
            </button>
          ) : onboardings.length > 0 ? (
            <p className="text-center text-xs text-slate-600">All {total} sessions loaded</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

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

  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

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
      if (selectedUser?.id === deleteTarget.id) setSelectedUser(null);
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
    <div className="flex h-full overflow-hidden">
      {/* Main table */}
      <div className="flex-1 overflow-y-auto p-6 sm:p-8 min-w-0">
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
                      onClick={() => setSelectedUser((prev) => prev?.id === u.id ? null : u)}
                      className={`cursor-pointer transition-colors ${
                        selectedUser?.id === u.id
                          ? 'bg-violet-500/10 border-l-2 border-l-violet-500'
                          : 'hover:bg-slate-900/60'
                      }`}
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

      {/* Slide-in onboardings panel */}
      <div
        className={`flex-shrink-0 border-l border-slate-800 bg-slate-900 transition-all duration-300 overflow-hidden ${
          selectedUser ? 'w-96' : 'w-0'
        }`}
      >
        {selectedUser && (
          <UserOnboardingsPanel user={selectedUser} onClose={() => setSelectedUser(null)} />
        )}
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