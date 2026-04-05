import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  listAdminSubscriptionGrants,
  getAdminSubscriptionGrantAuditLog,
  searchUsersForGrant,
  grantAdminSubscription,
  revokeAdminSubscription,
} from '../api';
import type {
  AdminSubscriptionGrant,
  AdminSubscriptionGrantAuditLog,
  AdminSubscriptionUserSearchResult,
} from '../api/types';

export default function AdminSubscriptionGrantsPage() {
  const [grants, setGrants] = useState<AdminSubscriptionGrant[]>([]);
  const [auditLogs, setAuditLogs] = useState<AdminSubscriptionGrantAuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<AdminSubscriptionUserSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Grant/Revoke state
  const [selectedUser, setSelectedUser] = useState<AdminSubscriptionUserSearchResult | null>(null);
  const [reason, setReason] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<'active' | 'all' | 'audit'>('active');

  const loadData = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [grantsRes, logsRes] = await Promise.all([
        listAdminSubscriptionGrants(),
        getAdminSubscriptionGrantAuditLog(),
      ]);
      setGrants(grantsRes.grants || []);
      setAuditLogs(logsRes.logs || []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Debounced search
  useEffect(() => {
    const q = searchQuery.trim();
    if (q.length < 2) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await searchUsersForGrant(q);
        setSearchResults(res.users || []);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleGrant = async () => {
    if (!selectedUser) return;
    setActionLoading(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      await grantAdminSubscription(selectedUser.id, reason);
      setActionSuccess(`Subscription granted to ${selectedUser.email || selectedUser.phone_number}`);
      setSelectedUser(null);
      setReason('');
      setSearchQuery('');
      setSearchResults([]);
      await loadData();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to grant subscription');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRevoke = async (userId: string, userEmail: string) => {
    if (!confirm(`Are you sure you want to revoke subscription for ${userEmail}?`)) return;
    setActionLoading(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      await revokeAdminSubscription(userId, 'Revoked via admin panel');
      setActionSuccess(`Subscription revoked for ${userEmail}`);
      await loadData();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to revoke subscription');
    } finally {
      setActionLoading(false);
    }
  };

  const activeGrants = useMemo(() => grants.filter((g) => g.is_active), [grants]);

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-xl font-bold text-slate-100">Subscription Grants</h1>
        <p className="text-sm text-slate-500 mt-1">
          Grant full subscription access to team members. All actions are logged with your admin ID for audit purposes.
        </p>

        {/* Action feedback */}
        {actionSuccess && (
          <div className="mt-4 px-4 py-3 rounded-lg bg-emerald-500/15 text-emerald-300 text-sm border border-emerald-500/30">
            ✓ {actionSuccess}
          </div>
        )}
        {actionError && (
          <div className="mt-4 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            ✗ {actionError}
          </div>
        )}

        {/* Grant new subscription section */}
        <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950 p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-3">Grant New Subscription</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Search user by email or phone</label>
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Type at least 2 characters..."
                className="w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2.5 text-sm text-slate-100 outline-none focus:border-violet-500"
              />
              {searching && (
                <p className="text-xs text-slate-500 mt-1">Searching...</p>
              )}
              {searchResults.length > 0 && (
                <div className="mt-2 rounded-lg border border-slate-700 bg-slate-900 max-h-48 overflow-y-auto">
                  {searchResults.map((user) => (
                    <button
                      key={user.id}
                      type="button"
                      onClick={() => {
                        setSelectedUser(user);
                        setSearchQuery('');
                        setSearchResults([]);
                      }}
                      className={`w-full text-left px-3 py-2 hover:bg-slate-800 border-b border-slate-800 last:border-b-0 ${
                        user.has_admin_grant ? 'opacity-50' : ''
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm text-slate-100">{user.email || user.phone_number}</p>
                          {user.email && user.phone_number && (
                            <p className="text-xs text-slate-500">{user.phone_number}</p>
                          )}
                        </div>
                        {user.has_admin_grant && (
                          <span className="text-xs bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded">
                            Already granted
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Reason (optional)</label>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g., Team member, Testing, Beta access..."
                className="w-full rounded-xl border border-slate-800 bg-slate-900 px-4 py-2.5 text-sm text-slate-100 outline-none focus:border-violet-500"
              />
            </div>
          </div>

          {selectedUser && (
            <div className="mt-4 p-3 rounded-lg bg-violet-500/10 border border-violet-500/30">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-100">
                    <strong>Selected:</strong> {selectedUser.email || selectedUser.phone_number}
                  </p>
                  {selectedUser.has_admin_grant && (
                    <p className="text-xs text-amber-400 mt-1">⚠ This user already has an admin grant. Granting again will update the grant info.</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedUser(null)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  ✕
                </button>
              </div>
            </div>
          )}

          <div className="mt-4">
            <button
              type="button"
              disabled={!selectedUser || actionLoading}
              onClick={handleGrant}
              className="px-5 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {actionLoading ? 'Granting...' : 'Grant Full Subscription Access'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="mt-8 flex gap-1 border-b border-slate-800">
          <button
            type="button"
            onClick={() => setActiveTab('active')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'active'
                ? 'border-violet-500 text-violet-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Active Grants ({activeGrants.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('all')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'all'
                ? 'border-violet-500 text-violet-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            All Grants ({grants.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('audit')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'audit'
                ? 'border-violet-500 text-violet-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Audit Log ({auditLogs.length})
          </button>
        </div>

        {loading ? (
          <div className="text-center py-16 text-slate-500">
            <div className="inline-block w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mb-3" />
            <p className="font-medium">Loading...</p>
          </div>
        ) : err ? (
          <div className="mt-5 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {err}
          </div>
        ) : (
          <div className="mt-4">
            {activeTab === 'active' && (
              <GrantsTable
                grants={activeGrants}
                onRevoke={handleRevoke}
                actionLoading={actionLoading}
              />
            )}
            {activeTab === 'all' && (
              <GrantsTable
                grants={grants}
                onRevoke={handleRevoke}
                actionLoading={actionLoading}
                showRevoked
              />
            )}
            {activeTab === 'audit' && <AuditLogTable logs={auditLogs} />}
          </div>
        )}
      </div>
    </div>
  );
}

function GrantsTable({
  grants,
  onRevoke,
  actionLoading,
  showRevoked = false,
}: {
  grants: AdminSubscriptionGrant[];
  onRevoke: (userId: string, userEmail: string) => void;
  actionLoading: boolean;
  showRevoked?: boolean;
}) {
  if (grants.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        <p>No grants found.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-900">
          <tr>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">User</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Granted By</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Reason</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Granted At</th>
            {showRevoked && (
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Status</th>
            )}
            <th className="text-right px-4 py-3 text-slate-400 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800 bg-slate-950">
          {grants.map((g) => (
            <tr key={g.id} className={!g.is_active ? 'opacity-50' : ''}>
              <td className="px-4 py-3">
                <div>
                  <p className="text-slate-100">{g.user_email || g.user_phone || 'Unknown'}</p>
                  {g.user_email && g.user_phone && (
                    <p className="text-xs text-slate-500">{g.user_phone}</p>
                  )}
                  <p className="text-xs text-slate-600 font-mono">{g.user_id.slice(0, 8)}...</p>
                </div>
              </td>
              <td className="px-4 py-3 text-slate-300">{g.granted_by_email || 'N/A'}</td>
              <td className="px-4 py-3 text-slate-400 max-w-[200px] truncate">
                {g.reason || '—'}
              </td>
              <td className="px-4 py-3 text-slate-400">
                {g.granted_at ? new Date(g.granted_at).toLocaleString() : '—'}
              </td>
              {showRevoked && (
                <td className="px-4 py-3">
                  {g.is_active ? (
                    <span className="text-xs bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded">
                      Active
                    </span>
                  ) : (
                    <span className="text-xs bg-red-500/20 text-red-300 px-2 py-0.5 rounded">
                      Revoked
                    </span>
                  )}
                </td>
              )}
              <td className="px-4 py-3 text-right">
                {g.is_active && (
                  <button
                    type="button"
                    disabled={actionLoading}
                    onClick={() => onRevoke(g.user_id, g.user_email || g.user_phone)}
                    className="px-3 py-1.5 rounded-lg bg-red-500/20 text-red-300 text-xs font-medium hover:bg-red-500/30 disabled:opacity-50"
                  >
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditLogTable({ logs }: { logs: AdminSubscriptionGrantAuditLog[] }) {
  if (logs.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        <p>No audit logs yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-900">
          <tr>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Action</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Target User</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Admin</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Reason</th>
            <th className="text-left px-4 py-3 text-slate-400 font-medium">Timestamp</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800 bg-slate-950">
          {logs.map((log) => (
            <tr key={log.id}>
              <td className="px-4 py-3">
                {log.action === 'grant' ? (
                  <span className="text-xs bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded">
                    GRANT
                  </span>
                ) : (
                  <span className="text-xs bg-red-500/20 text-red-300 px-2 py-0.5 rounded">
                    REVOKE
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-slate-100">{log.target_email || log.target_user_id}</td>
              <td className="px-4 py-3 text-slate-300">{log.admin_email || 'N/A'}</td>
              <td className="px-4 py-3 text-slate-400 max-w-[200px] truncate">
                {log.reason || '—'}
              </td>
              <td className="px-4 py-3 text-slate-400">
                {log.created_at ? new Date(log.created_at).toLocaleString() : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

