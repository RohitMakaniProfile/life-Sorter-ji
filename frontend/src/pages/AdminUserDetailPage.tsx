import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { listUserOnboardings, listUserSkillCalls, getUserCrawlPages } from '../api';
import type { AdminUser, AdminUserOnboarding, AdminSkillCallSummary, AdminCrawlPage } from '../api/types';

const ONBOARDINGS_PAGE = 10;
const SKILL_CALLS_PAGE = 20;

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const s = status || '';
  const cls =
    s === 'complete' || s === 'done'
      ? 'bg-emerald-500/20 text-emerald-300'
      : s === 'error'
      ? 'bg-red-500/20 text-red-300'
      : s === 'generating' || s === 'running'
      ? 'bg-blue-500/20 text-blue-300'
      : 'bg-amber-500/20 text-amber-300';
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {s ? s.toUpperCase() : 'NOT STARTED'}
    </span>
  );
}

// ── Onboarding Tab ───────────────────────────────────────────────────────────

function OnboardingTab({ userId }: { userId: string }) {
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
      const res = await listUserOnboardings(userId, ONBOARDINGS_PAGE, off);
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
  }, [userId]);

  useEffect(() => {
    setOffset(0);
    setOnboardings([]);
    load(0);
  }, [load]);

  const hasMore = onboardings.length < total;

  return (
    <div>
      <p className="text-[11px] text-slate-500 uppercase tracking-widest font-semibold mb-4">
        Onboarding Sessions {total > 0 ? `(${total})` : ''}
      </p>

      {err && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
          {err}
        </div>
      )}

      {!loading && onboardings.length === 0 && !err && (
        <div className="py-12 text-center text-slate-500 text-sm">No onboarding sessions found.</div>
      )}

      <div className="divide-y divide-slate-800 rounded-xl border border-slate-800 overflow-hidden">
        {onboardings.map((o) => (
          <button
            key={o.id}
            type="button"
            onClick={() => navigate(`/admin/onboarding/${o.id}/token-usage`)}
            className="w-full text-left px-4 py-3 hover:bg-slate-800/60 transition-colors bg-slate-950"
          >
            <div className="flex items-start justify-between gap-2 mb-1.5">
              <span className="text-xs font-semibold text-slate-100 truncate flex-1">
                {o.task || o.domain || o.outcome || 'Onboarding'}
              </span>
              <StatusBadge status={o.playbook_status} />
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
              <span title="Onboarding ID">ID: {o.id.slice(0, 12)}…</span>
              {o.outcome && <span>🎯 {o.outcome}</span>}
              {o.created_at && <span>{new Date(o.created_at).toLocaleDateString()}</span>}
            </div>
            {o.website_url && (
              <p className="text-[10px] text-slate-600 truncate mt-1">🌐 {o.website_url}</p>
            )}
          </button>
        ))}
      </div>

      <div className="mt-3">
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
  );
}

// ── Messages Tab ─────────────────────────────────────────────────────────────

interface MessageGroup {
  messageId: string;
  conversationId: string;
  calls: AdminSkillCallSummary[];
  startedAt: string;
}

function groupByMessage(calls: AdminSkillCallSummary[]): MessageGroup[] {
  const map = new Map<string, MessageGroup>();
  for (const call of calls) {
    const key = call.message_id || call.id;
    if (!map.has(key)) {
      map.set(key, {
        messageId: call.message_id,
        conversationId: call.conversation_id,
        calls: [],
        startedAt: call.started_at,
      });
    }
    map.get(key)!.calls.push(call);
  }
  return Array.from(map.values()).sort(
    (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime(),
  );
}

function MessagesTab({ userId }: { userId: string }) {
  const navigate = useNavigate();
  const [calls, setCalls] = useState<AdminSkillCallSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const load = useCallback(async (off: number) => {
    setLoading(true);
    setErr(null);
    try {
      const res = await listUserSkillCalls(userId, SKILL_CALLS_PAGE, off);
      if (off === 0) {
        setCalls(res.calls);
      } else {
        setCalls((prev) => [...prev, ...res.calls]);
      }
      setTotal(res.total);
      setOffset(off + res.calls.length);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    setOffset(0);
    setCalls([]);
    load(0);
  }, [load]);

  const groups = groupByMessage(calls);
  const hasMore = calls.length < total;

  const toggleGroup = (messageId: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  return (
    <div>
      <p className="text-[11px] text-slate-500 uppercase tracking-widest font-semibold mb-4">
        Messages & Skill Calls {total > 0 ? `(${total} skill calls)` : ''}
      </p>

      {err && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30">
          {err}
        </div>
      )}

      {!loading && groups.length === 0 && !err && (
        <div className="py-12 text-center text-slate-500 text-sm">No messages found.</div>
      )}

      <div className="space-y-3">
        {groups.map((group) => {
          const isExpanded = expandedGroups.has(group.messageId);
          const overallState = group.calls.some((c) => c.state === 'error')
            ? 'error'
            : group.calls.some((c) => c.state === 'running')
            ? 'running'
            : 'done';

          return (
            <div key={group.messageId} className="rounded-xl border border-slate-800 overflow-hidden">
              {/* Message group header */}
              <button
                type="button"
                onClick={() => toggleGroup(group.messageId)}
                className="w-full text-left px-4 py-3 bg-slate-900 hover:bg-slate-800/70 transition-colors flex items-center justify-between gap-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <StatusBadge status={overallState} />
                    <span className="text-xs text-slate-400">
                      {group.calls.length} skill call{group.calls.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 font-mono truncate">
                    msg: {group.messageId ? group.messageId.slice(0, 20) + '…' : 'unknown'}
                  </p>
                  {group.conversationId && (
                    <p className="text-[10px] text-slate-600 font-mono truncate">
                      conv: {group.conversationId.slice(0, 20)}…
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {group.startedAt && (
                    <span className="text-[11px] text-slate-500 whitespace-nowrap">
                      {new Date(group.startedAt).toLocaleString()}
                    </span>
                  )}
                  <span className="text-slate-500 text-xs">{isExpanded ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Expanded skill calls */}
              {isExpanded && (
                <div className="divide-y divide-slate-800 bg-slate-950">
                  {group.calls.map((call) => (
                    <button
                      key={call.id}
                      type="button"
                      onClick={() => navigate(`/admin/skill-calls/${call.id}`)}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-800/40 transition-colors flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-mono text-violet-300 truncate">
                            {call.skill_id}
                          </span>
                          <StatusBadge status={call.state} />
                        </div>
                        <p className="text-[10px] text-slate-600 font-mono">
                          ID: {String(call.id).slice(0, 8)}…
                        </p>
                      </div>
                      <div className="flex-shrink-0 text-right">
                        {call.duration_ms != null && (
                          <p className="text-[11px] text-slate-500">{call.duration_ms}ms</p>
                        )}
                        {call.started_at && (
                          <p className="text-[10px] text-slate-600">
                            {new Date(call.started_at).toLocaleTimeString()}
                          </p>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-3">
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
        ) : calls.length > 0 ? (
          <p className="text-center text-xs text-slate-600">All {total} skill calls loaded</p>
        ) : null}
      </div>
    </div>
  );
}

// ── Crawl Data Tab ───────────────────────────────────────────────────────────

const CRAWL_PAGES_PAGE = 20;

function CrawlStatusBadge({ status }: { status: string }) {
  const s = status || '';
  const cls =
    s === 'done'
      ? 'bg-emerald-500/20 text-emerald-300'
      : s === 'error'
      ? 'bg-red-500/20 text-red-300'
      : s === 'skipped'
      ? 'bg-slate-500/20 text-slate-400'
      : 'bg-amber-500/20 text-amber-300';
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {s ? s.toUpperCase() : 'UNKNOWN'}
    </span>
  );
}

function CrawlDataTab({ userId }: { userId: string }) {
  const [pages, setPages] = useState<AdminCrawlPage[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [expandedPage, setExpandedPage] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<Record<string, 'markdown' | 'raw'>>({});

  const load = useCallback(async (off: number) => {
    setLoading(true);
    setErr(null);
    try {
      const res = await getUserCrawlPages(userId, CRAWL_PAGES_PAGE, off);
      if (off === 0) {
        setPages(res.pages);
      } else {
        setPages((prev) => [...prev, ...res.pages]);
      }
      setTotal(res.total);
      setOffset(off + res.pages.length);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load crawl data');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    setOffset(0);
    setPages([]);
    load(0);
  }, [load]);

  const hasMore = pages.length < total;

  const togglePage = (id: string) => {
    setExpandedPage((prev) => (prev === id ? null : id));
  };

  const getView = (id: string) => activeView[id] || 'markdown';
  const setView = (id: string, v: 'markdown' | 'raw') =>
    setActiveView((prev) => ({ ...prev, [id]: v }));

  return (
    <div>
      <p className="text-[11px] text-slate-500 uppercase tracking-widest font-semibold mb-4">
        Crawled Pages {total > 0 ? `(${total})` : ''}
      </p>

      {err && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/15 text-red-300 text-xs border border-red-500/30 font-mono whitespace-pre-wrap">
          {err}
        </div>
      )}

      {!loading && pages.length === 0 && !err && (
        <div className="py-12 text-center text-slate-500 text-sm">No crawled pages found for this user.</div>
      )}

      <div className="space-y-2">
        {pages.map((page) => {
          const isExpanded = expandedPage === page.id;
          const view = getView(page.id);
          const hasContent = !!(page.markdown || page.raw_html);

          return (
            <div key={page.id} className="rounded-xl border border-slate-800 overflow-hidden">
              <button
                type="button"
                onClick={() => hasContent && togglePage(page.id)}
                className={`w-full text-left px-4 py-3 bg-slate-900 transition-colors flex items-start justify-between gap-3 ${hasContent ? 'hover:bg-slate-800/70 cursor-pointer' : 'cursor-default'}`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <CrawlStatusBadge status={page.status} />
                    <span className="text-[10px] text-slate-500 font-mono">
                      {page.onboarding_id?.slice(0, 10)}…
                    </span>
                  </div>
                  <p className="text-xs text-slate-300 font-mono truncate" title={page.url}>
                    {page.url}
                  </p>
                  {page.error && (
                    <p className="text-[11px] text-red-400 mt-1 truncate font-mono" title={page.error}>
                      Error: {page.error}
                    </p>
                  )}
                </div>
                <div className="flex-shrink-0 text-right">
                  {page.crawled_at && (
                    <p className="text-[10px] text-slate-600 whitespace-nowrap">
                      {new Date(page.crawled_at).toLocaleString()}
                    </p>
                  )}
                  {hasContent && (
                    <span className="text-slate-500 text-xs ml-2">{isExpanded ? '▲' : '▼'}</span>
                  )}
                </div>
              </button>

              {isExpanded && hasContent && (
                <div className="bg-slate-950 border-t border-slate-800">
                  {/* View toggle */}
                  <div className="flex gap-1 px-4 pt-3 pb-2">
                    {page.markdown && (
                      <button
                        type="button"
                        onClick={() => setView(page.id, 'markdown')}
                        className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${view === 'markdown' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}
                      >
                        Markdown
                      </button>
                    )}
                    {page.raw_html && (
                      <button
                        type="button"
                        onClick={() => setView(page.id, 'raw')}
                        className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${view === 'raw' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}
                      >
                        Raw HTML
                      </button>
                    )}
                  </div>
                  <pre className="px-4 pb-4 text-[11px] text-slate-300 font-mono overflow-x-auto max-h-96 overflow-y-auto whitespace-pre-wrap break-words leading-relaxed">
                    {view === 'markdown' ? (page.markdown || '') : (page.raw_html || '')}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-3">
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
        ) : pages.length > 0 ? (
          <p className="text-center text-xs text-slate-600">All {total} pages loaded</p>
        ) : null}
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

type Tab = 'onboarding' | 'messages' | 'crawl';

export default function AdminUserDetailPage() {
  const { userId } = useParams<{ userId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('onboarding');
  const TAB_LABELS: Record<Tab, string> = { onboarding: 'Onboarding', messages: 'Messages', crawl: 'Crawl Data' };

  const user = (location.state as { user?: AdminUser } | null)?.user;

  if (!userId) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        User ID not found.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 sm:p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <button
            type="button"
            onClick={() => navigate('/admin/users')}
            className="text-slate-400 hover:text-slate-100 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-800 transition-colors text-lg"
          >
            ←
          </button>
          <div>
            <h1 className="text-xl font-bold text-slate-100">
              {user?.email || user?.phone_number || userId}
            </h1>
            {user?.name && <p className="text-sm text-slate-400">{user.name}</p>}
            <p className="text-xs text-slate-600 font-mono mt-0.5">{userId}</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b border-slate-800">
          {(['onboarding', 'messages', 'crawl'] as Tab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
                activeTab === tab
                  ? 'border-violet-500 text-violet-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'onboarding' ? (
          <OnboardingTab userId={userId} />
        ) : activeTab === 'messages' ? (
          <MessagesTab userId={userId} />
        ) : (
          <CrawlDataTab userId={userId} />
        )}
      </div>
    </div>
  );
}