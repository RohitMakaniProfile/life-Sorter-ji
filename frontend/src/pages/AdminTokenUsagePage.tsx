import { useEffect, useState } from 'react';
import {
  getTokenUsageConversationCalls,
  getTokenUsageSummary,
  getTokenUsageUserConversations,
  getTokenUsageUsers,
} from '../api';
import type {
  AdminTokenUsageCall,
  AdminTokenUsageConversation,
  AdminTokenUsageSummary,
  AdminTokenUsageUser,
} from '../api/types';

export default function AdminTokenUsagePage() {
  const [summary, setSummary] = useState<AdminTokenUsageSummary | null>(null);
  const [users, setUsers] = useState<AdminTokenUsageUser[]>([]);
  const [conversations, setConversations] = useState<AdminTokenUsageConversation[]>([]);
  const [calls, setCalls] = useState<AdminTokenUsageCall[]>([]);
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);

  useEffect(() => {
    getTokenUsageSummary().then(setSummary).catch(() => {});
    getTokenUsageUsers('', 50, 0).then((r) => setUsers(r.users || [])).catch(() => {});
  }, []);

  async function openUser(userId: string) {
    setSelectedUser(userId);
    setSelectedConversation(null);
    setCalls([]);
    const res = await getTokenUsageUserConversations(userId, 50, 0);
    setConversations(res.conversations || []);
  }

  async function openConversation(conversationId: string) {
    setSelectedConversation(conversationId);
    const res = await getTokenUsageConversationCalls(conversationId, 100, 0);
    setCalls(res.calls || []);
  }

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <h1 className="text-xl font-bold text-slate-100">Token Usage</h1>
        {summary && (
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
            <Card label="Spend (Linked INR)" value={`₹${summary.spendInr.toFixed(2)}`} />
            <Card label="Spend (Overall INR)" value={`₹${summary.overallSpendInr.toFixed(2)}`} />
            <Card label="Unlinked spend (INR)" value={`₹${summary.unlinkedSpendInr.toFixed(2)}`} />
            <Card label="Input tokens" value={String(summary.inputTokens)} />
            <Card label="Output tokens" value={String(summary.outputTokens)} />
            <Card label="Calls" value={String(summary.callsCount)} />
            <Card label="Overall calls" value={String(summary.overallCallsCount)} />
            <Card label="Unlinked calls" value={String(summary.unlinkedCallsCount)} />
            <Card label="Users" value={String(summary.usersCount)} />
            <Card label="Unknown priced" value={String(summary.unknownPricedCalls)} />
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
            <div className="text-sm font-semibold text-slate-200 mb-2">Users</div>
            <div className="space-y-2 max-h-[60vh] overflow-y-auto">
              {users.map((u) => (
                <button key={u.userId} type="button" onClick={() => void openUser(u.userId)} className={`w-full text-left rounded-lg p-2 ${selectedUser === u.userId ? 'bg-slate-800' : 'bg-slate-900'}`}>
                  <div className="text-xs text-slate-200">{u.email || u.phoneNumber || u.userId}</div>
                  <div className="text-[11px] text-slate-500">₹{u.spendInr.toFixed(2)} • {u.callsCount} calls</div>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
            <div className="text-sm font-semibold text-slate-200 mb-2">Conversations</div>
            <div className="space-y-2 max-h-[60vh] overflow-y-auto">
              {conversations.map((c) => (
                <button key={c.conversationId} type="button" onClick={() => void openConversation(c.conversationId)} className={`w-full text-left rounded-lg p-2 ${selectedConversation === c.conversationId ? 'bg-slate-800' : 'bg-slate-900'}`}>
                  <div className="text-xs text-slate-200 font-mono">{c.conversationId}</div>
                  <div className="text-[11px] text-slate-500">₹{c.spendInr.toFixed(2)} • {c.callsCount} calls</div>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
            <div className="text-sm font-semibold text-slate-200 mb-2">LLM Calls</div>
            <div className="space-y-2 max-h-[60vh] overflow-y-auto">
              {calls.map((call) => (
                <div key={`${call.messageId}-${call.createdAt}`} className="rounded-lg bg-slate-900 p-2">
                  <div className="text-xs text-slate-200">{call.model}</div>
                  <div className="text-[11px] text-slate-500">{call.stage} • {call.provider}</div>
                  <div className="text-[11px] text-slate-400">in {call.inputTokens} / out {call.outputTokens} • {call.costInr == null ? '—' : `₹${call.costInr.toFixed(2)}`}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}
