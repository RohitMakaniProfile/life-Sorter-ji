import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getAdminTokenUsageSummary,
  listAdminTokenUsageUsers,
  listAdminTokenUsageUserConversations,
  listAdminTokenUsageConversationCalls,
} from '../api';
import type {
  AdminTokenUsageCallRow,
  AdminTokenUsageConversationRow,
  AdminTokenUsageSummary,
  AdminTokenUsageUserRow,
} from '../api/types';

const USERS_PAGE_SIZE = 50;
const CONV_PAGE_SIZE = 50;
const CALLS_PAGE_SIZE = 80;

function formatInr(v: number): string {
  const n = Number(v || 0);
  return `₹${n.toFixed(2)}`;
}

function small(dtIso: string): string {
  if (!dtIso) return '';
  try {
    return new Date(dtIso).toLocaleString();
  } catch {
    return dtIso;
  }
}

export default function AdminTokenUsagePage() {
  const [summary, setSummary] = useState<AdminTokenUsageSummary | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [errSummary, setErrSummary] = useState<string | null>(null);

  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [users, setUsers] = useState<AdminTokenUsageUserRow[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersOffset, setUsersOffset] = useState(0);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [errUsers, setErrUsers] = useState<string | null>(null);

  const [selectedUser, setSelectedUser] = useState<AdminTokenUsageUserRow | null>(null);

  const [convs, setConvs] = useState<AdminTokenUsageConversationRow[]>([]);
  const [convsTotal, setConvsTotal] = useState(0);
  const [convsOffset, setConvsOffset] = useState(0);
  const [loadingConvs, setLoadingConvs] = useState(false);
  const [errConvs, setErrConvs] = useState<string | null>(null);

  const [selectedConv, setSelectedConv] = useState<AdminTokenUsageConversationRow | null>(null);

  const [calls, setCalls] = useState<AdminTokenUsageCallRow[]>([]);
  const [callsTotal, setCallsTotal] = useState(0);
  const [callsOffset, setCallsOffset] = useState(0);
  const [loadingCalls, setLoadingCalls] = useState(false);
  const [errCalls, setErrCalls] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    setErrSummary(null);
    try {
      const s = await getAdminTokenUsageSummary();
      setSummary(s);
    } catch (e) {
      setErrSummary(e instanceof Error ? e.message : 'Failed to load summary');
    } finally {
      setLoadingSummary(false);
    }
  }, []);

  const loadUsers = useCallback(async (off: number, query: string) => {
    setLoadingUsers(true);
    setErrUsers(null);
    try {
      const res = await listAdminTokenUsageUsers({ q: query || undefined, limit: USERS_PAGE_SIZE, offset: off });
      setUsers(res.users ?? []);
      setUsersTotal(res.total ?? 0);
      setUsersOffset(off);
    } catch (e) {
      setErrUsers(e instanceof Error ? e.message : 'Failed to load users');
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  const loadConvs = useCallback(async (off: number, userId: string) => {
    setLoadingConvs(true);
    setErrConvs(null);
    try {
      const res = await listAdminTokenUsageUserConversations({
        userId,
        limit: CONV_PAGE_SIZE,
        offset: off,
      });
      if (off === 0) setConvs(res.conversations ?? []);
      else setConvs((prev) => [...prev, ...(res.conversations ?? [])]);
      setConvsTotal(res.total ?? 0);
      setConvsOffset(off + (res.conversations?.length ?? 0));
    } catch (e) {
      setErrConvs(e instanceof Error ? e.message : 'Failed to load conversations');
    } finally {
      setLoadingConvs(false);
    }
  }, []);

  const loadCalls = useCallback(async (off: number, conversationId: string) => {
    setLoadingCalls(true);
    setErrCalls(null);
    try {
      const res = await listAdminTokenUsageConversationCalls({
        conversationId,
        limit: CALLS_PAGE_SIZE,
        offset: off,
      });
      if (off === 0) setCalls(res.calls ?? []);
      else setCalls((prev) => [...prev, ...(res.calls ?? [])]);
      setCallsTotal(res.total ?? 0);
      setCallsOffset(off + (res.calls?.length ?? 0));
    } catch (e) {
      setErrCalls(e instanceof Error ? e.message : 'Failed to load calls');
    } finally {
      setLoadingCalls(false);
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [q]);

  useEffect(() => {
    void loadUsers(0, debouncedQ);
    setSelectedUser(null);
    setSelectedConv(null);
    setConvs([]);
    setCalls([]);
  }, [debouncedQ, loadUsers]);

  useEffect(() => {
    if (!selectedUser) return;
    setSelectedConv(null);
    setCalls([]);
    setConvs([]);
    setConvsOffset(0);
    void loadConvs(0, selectedUser.user_id);
  }, [selectedUser, loadConvs]);

  useEffect(() => {
    if (!selectedConv) return;
    setCalls([]);
    setCallsOffset(0);
    void loadCalls(0, selectedConv.conversation_id);
  }, [selectedConv, loadCalls]);

  const usersPage = useMemo(() => Math.floor(usersOffset / USERS_PAGE_SIZE) + 1, [usersOffset]);
  const usersPages = useMemo(() => Math.max(1, Math.ceil(usersTotal / USERS_PAGE_SIZE)), [usersTotal]);
  const usersHasPrev = usersOffset > 0;
  const usersHasNext = usersOffset + USERS_PAGE_SIZE < usersTotal;

  const selectedUserLabel = selectedUser?.email || selectedUser?.phone_number || selectedUser?.user_id || '';

  const convsHasMore = convs.length < convsTotal;
  const callsHasMore = calls.length < callsTotal;

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-slate-100">Token Usage</h1>
            <p className="text-sm text-slate-500 mt-1">Spend + token analytics (priced spend excludes unknown models).</p>
          </div>
          <button
            type="button"
            onClick={() => void loadSummary()}
            disabled={loadingSummary}
            className="px-4 py-2 rounded-xl bg-slate-800 text-slate-100 text-sm font-semibold hover:bg-slate-700 disabled:opacity-60"
          >
            {loadingSummary ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {errSummary && (
          <div className="mt-4 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {errSummary}
          </div>
        )}

        <div className="mt-6 grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="text-xs text-slate-500">Spend (priced, INR)</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">
              {summary ? formatInr(summary.spendInrPriced) : '—'}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="text-xs text-slate-500">Tokens</div>
            <div className="text-sm font-semibold text-slate-100 mt-2">
              {summary ? `${summary.inputTokens.toLocaleString()} in / ${summary.outputTokens.toLocaleString()} out` : '—'}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="text-xs text-slate-500">Users</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">{summary ? summary.users : '—'}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="text-xs text-slate-500">Unknown-priced calls</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">{summary ? summary.unknownPricingCalls : '—'}</div>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1.05fr_0.95fr] gap-6">
          {/* Users list */}
          <div className="rounded-xl border border-slate-800 overflow-hidden">
            <div className="bg-slate-900 px-4 py-3 flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-slate-200">Users</div>
              <div className="flex items-center gap-2">
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search email / phone / name…"
                  className="w-72 max-w-[55vw] rounded-xl border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-100 outline-none"
                />
              </div>
            </div>
            <div className="bg-slate-950 border-t border-slate-800 px-4 py-2 flex items-center justify-between">
              <div className="text-xs text-slate-500">
                {usersTotal.toLocaleString()} total • page {usersPage}/{usersPages}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!usersHasPrev || loadingUsers}
                  onClick={() => void loadUsers(Math.max(0, usersOffset - USERS_PAGE_SIZE), debouncedQ)}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                >
                  Prev
                </button>
                <button
                  type="button"
                  disabled={!usersHasNext || loadingUsers}
                  onClick={() => void loadUsers(usersOffset + USERS_PAGE_SIZE, debouncedQ)}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>

            {errUsers && (
              <div className="m-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
                {errUsers}
              </div>
            )}
            {loadingUsers ? (
              <div className="text-center py-12 text-slate-500">
                <div className="inline-block w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mb-3" />
                <p className="font-medium">Loading users…</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-800 bg-slate-950 max-h-[68vh] overflow-y-auto">
                {users.map((u) => (
                  <button
                    key={u.user_id}
                    type="button"
                    onClick={() => setSelectedUser(u)}
                    className={`w-full text-left px-4 py-3 hover:bg-slate-900 transition-colors ${
                      selectedUser?.user_id === u.user_id ? 'bg-slate-900' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-100 truncate">
                          {u.email || u.phone_number || u.user_id}
                        </div>
                        <div className="text-[11px] text-slate-500 mt-0.5 truncate">
                          {u.name ? `${u.name} • ` : ''}
                          {formatInr(u.spendInrPriced)} • {u.inputTokens.toLocaleString()} in / {u.outputTokens.toLocaleString()} out
                          {u.unknownPricingCalls ? ` • unknown: ${u.unknownPricingCalls}` : ''}
                        </div>
                      </div>
                      <div className="text-[10px] text-slate-600">{small(u.lastAt)}</div>
                    </div>
                  </button>
                ))}
                {users.length === 0 && (
                  <div className="px-4 py-8 text-sm text-slate-500">No users found for this window/query.</div>
                )}
              </div>
            )}
          </div>

          {/* Drilldown */}
          <div className="rounded-xl border border-slate-800 bg-slate-950 overflow-hidden flex flex-col min-h-[420px]">
            <div className="bg-slate-900 px-4 py-3">
              <div className="text-sm font-semibold text-slate-200">Detail</div>
              <div className="text-xs text-slate-500 mt-1 truncate">
                {selectedUser ? `User: ${selectedUserLabel}` : 'Select a user to drill down'}
              </div>
            </div>

            {!selectedUser ? (
              <div className="p-6 text-sm text-slate-500">Pick a user from the left.</div>
            ) : (
              <div className="flex-1 overflow-y-auto">
                <div className="px-4 py-3 border-b border-slate-800">
                  <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">
                    Conversations ({convsTotal})
                  </div>
                </div>

                {errConvs && (
                  <div className="m-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
                    {errConvs}
                  </div>
                )}

                <div className="divide-y divide-slate-800">
                  {convs.map((c) => (
                    <button
                      key={c.conversation_id}
                      type="button"
                      onClick={() => setSelectedConv(c)}
                      className={`w-full text-left px-4 py-3 hover:bg-slate-900 transition-colors ${
                        selectedConv?.conversation_id === c.conversation_id ? 'bg-slate-900' : ''
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-slate-100 truncate">{c.title}</div>
                          <div className="text-[11px] text-slate-500 mt-0.5 truncate">
                            {formatInr(c.spendInrPriced)} • {c.inputTokens.toLocaleString()} in / {c.outputTokens.toLocaleString()} out
                            {c.unknownPricingCalls ? ` • unknown: ${c.unknownPricingCalls}` : ''}
                          </div>
                        </div>
                        <div className="text-[10px] text-slate-600">{small(c.lastAt)}</div>
                      </div>
                    </button>
                  ))}
                  {!loadingConvs && convs.length === 0 && (
                    <div className="px-4 py-8 text-sm text-slate-500">No conversations found.</div>
                  )}
                </div>

                <div className="px-4 py-3 border-t border-slate-800">
                  {loadingConvs ? (
                    <div className="flex justify-center py-3">
                      <div className="w-4 h-4 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : convsHasMore ? (
                    <button
                      type="button"
                      onClick={() => void loadConvs(convsOffset, selectedUser.user_id)}
                      className="w-full py-2 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800"
                    >
                      Load more conversations
                    </button>
                  ) : null}
                </div>

                {selectedConv && (
                  <>
                    <div className="px-4 py-3 border-t border-slate-800">
                      <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">
                        LLM calls ({callsTotal}) — {selectedConv.title}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">
                        Unknown pricing calls are excluded from spend totals.
                      </div>
                    </div>

                    {errCalls && (
                      <div className="m-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
                        {errCalls}
                      </div>
                    )}

                    <div className="overflow-x-auto px-4">
                      <table className="w-full text-[11px] border-collapse my-3">
                        <thead className="bg-slate-900 text-slate-200">
                          <tr>
                            <th className="text-left px-2 py-1 border border-slate-800">At</th>
                            <th className="text-left px-2 py-1 border border-slate-800">Stage</th>
                            <th className="text-left px-2 py-1 border border-slate-800">Provider</th>
                            <th className="text-left px-2 py-1 border border-slate-800">Model</th>
                            <th className="text-right px-2 py-1 border border-slate-800">In</th>
                            <th className="text-right px-2 py-1 border border-slate-800">Out</th>
                            <th className="text-right px-2 py-1 border border-slate-800">INR</th>
                          </tr>
                        </thead>
                        <tbody>
                          {calls.map((r, i) => (
                            <tr key={`${r.message_id}-${r.createdAt}-${i}`} className="text-slate-100 hover:bg-slate-900/60">
                              <td className="px-2 py-1 border border-slate-800 whitespace-nowrap">{small(r.createdAt)}</td>
                              <td className="px-2 py-1 border border-slate-800">{r.stage || '—'}</td>
                              <td className="px-2 py-1 border border-slate-800">{r.provider || '—'}</td>
                              <td className="px-2 py-1 border border-slate-800 font-mono text-[10px]">{r.model || '—'}</td>
                              <td className="px-2 py-1 border border-slate-800 text-right">{r.inputTokens.toLocaleString()}</td>
                              <td className="px-2 py-1 border border-slate-800 text-right">{r.outputTokens.toLocaleString()}</td>
                              <td className="px-2 py-1 border border-slate-800 text-right">
                                {r.costInr == null ? '—' : formatInr(r.costInr)}
                              </td>
                            </tr>
                          ))}
                          {!loadingCalls && calls.length === 0 && (
                            <tr>
                              <td colSpan={7} className="px-2 py-6 text-center text-slate-500 border border-slate-800">
                                No calls found.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>

                    <div className="px-4 pb-4">
                      {loadingCalls ? (
                        <div className="flex justify-center py-3">
                          <div className="w-4 h-4 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
                        </div>
                      ) : callsHasMore ? (
                        <button
                          type="button"
                          onClick={() => void loadCalls(callsOffset, selectedConv.conversation_id)}
                          className="w-full py-2 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800"
                        >
                          Load more calls
                        </button>
                      ) : null}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

