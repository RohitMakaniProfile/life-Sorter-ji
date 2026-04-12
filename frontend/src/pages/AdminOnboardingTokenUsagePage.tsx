import { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getOnboardingTokenUsage } from '../api';
import type { AdminOnboardingTokenUsageCall, AdminOnboardingTokenUsageSummary, AdminOnboardingInfo } from '../api/types';

const PAGE_SIZE = 100;

function formatCurrency(value: number | undefined | null, currency: 'USD' | 'INR'): string {
  const v = Number(value) || 0;
  if (currency === 'USD') return `$${v.toFixed(4)}`;
  return `₹${v.toFixed(2)}`;
}

function StageBadge({ stage }: { stage: string }) {
  const s = stage || 'unknown';
  const colors: Record<string, string> = {
    rca_questions: 'bg-blue-500/20 text-blue-300',
    precision_questions: 'bg-purple-500/20 text-purple-300',
    gap_questions: 'bg-amber-500/20 text-amber-300',
    business_profile: 'bg-emerald-500/20 text-emerald-300',
    playbook_stream: 'bg-pink-500/20 text-pink-300',
  };
  const cls = colors[s] || 'bg-slate-500/20 text-slate-300';
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {s.replace(/_/g, ' ').toUpperCase()}
    </span>
  );
}

export default function AdminOnboardingTokenUsagePage() {
  const { onboardingId } = useParams<{ onboardingId: string }>();
  const navigate = useNavigate();

  const [onboarding, setOnboarding] = useState<AdminOnboardingInfo | null>(null);
  const [summary, setSummary] = useState<AdminOnboardingTokenUsageSummary | null>(null);
  const [calls, setCalls] = useState<AdminOnboardingTokenUsageCall[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async (off: number) => {
    if (!onboardingId) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await getOnboardingTokenUsage(onboardingId, PAGE_SIZE, off);
      setOnboarding(res.onboarding);
      setSummary(res.summary);
      if (off === 0) {
        setCalls(res.calls);
      } else {
        setCalls((prev) => [...prev, ...res.calls]);
      }
      setTotal(res.total);
      setOffset(off + res.calls.length);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load token usage');
    } finally {
      setLoading(false);
    }
  }, [onboardingId]);

  useEffect(() => {
    setOffset(0);
    setCalls([]);
    load(0);
  }, [load]);

  const hasMore = calls.length < total;

  return (
    <div className="min-h-screen bg-slate-950 p-6 sm:p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="w-9 h-9 rounded-lg border border-slate-700 flex items-center justify-center text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          >
            ←
          </button>
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold text-slate-100">Onboarding Token Usage</h1>
            <p className="text-sm text-slate-500 font-mono truncate mt-0.5">{onboardingId}</p>
          </div>
        </div>

        {/* Error */}
        {err && (
          <div className="mb-6 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {err}
          </div>
        )}

        {/* Onboarding Info Card */}
        {onboarding && (
          <div className="mb-6 p-4 rounded-xl border border-slate-800 bg-slate-900">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-slate-500 mb-1">Outcome</p>
                <p className="text-sm text-slate-100 font-medium">{onboarding.outcome || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">Domain</p>
                <p className="text-sm text-slate-100 font-medium">{onboarding.domain || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">Task</p>
                <p className="text-sm text-slate-100 font-medium">{onboarding.task || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">Website</p>
                <p className="text-sm text-slate-100 font-medium truncate" title={onboarding.website_url}>
                  {onboarding.website_url || '—'}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Summary Cards */}
        {summary && (
          <div className="mb-6 grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900">
              <p className="text-xs text-slate-500 mb-1">Total LLM Calls</p>
              <p className="text-2xl font-bold text-slate-100">{Number(summary.calls_count) || 0}</p>
            </div>
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900">
              <p className="text-xs text-slate-500 mb-1">Input Tokens</p>
              <p className="text-2xl font-bold text-blue-400">{(Number(summary.input_tokens) || 0).toLocaleString()}</p>
            </div>
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900">
              <p className="text-xs text-slate-500 mb-1">Output Tokens</p>
              <p className="text-2xl font-bold text-emerald-400">{(Number(summary.output_tokens) || 0).toLocaleString()}</p>
            </div>
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900">
              <p className="text-xs text-slate-500 mb-1">Cost (USD)</p>
              <p className="text-2xl font-bold text-amber-400">{formatCurrency(summary.cost_usd, 'USD')}</p>
            </div>
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900">
              <p className="text-xs text-slate-500 mb-1">Cost (INR)</p>
              <p className="text-2xl font-bold text-pink-400">{formatCurrency(summary.cost_inr, 'INR')}</p>
            </div>
          </div>
        )}

        {/* Calls Table */}
        <div className="rounded-xl border border-slate-800 overflow-hidden">
          <div className="px-4 py-3 bg-slate-900 border-b border-slate-800">
            <h2 className="text-sm font-semibold text-slate-100">
              LLM Calls {total > 0 ? `(${total})` : ''}
            </h2>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/50">
                <tr>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Stage</th>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Model</th>
                  <th className="text-right px-4 py-3 text-slate-400 font-medium">Input</th>
                  <th className="text-right px-4 py-3 text-slate-400 font-medium">Output</th>
                  <th className="text-right px-4 py-3 text-slate-400 font-medium">Cost</th>
                  <th className="text-left px-4 py-3 text-slate-400 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950">
                {!loading && calls.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-500">
                      No token usage records found for this onboarding.
                    </td>
                  </tr>
                ) : (
                  calls.map((call, idx) => (
                    <tr key={`${call.message_id}-${idx}`} className="hover:bg-slate-900/40">
                      <td className="px-4 py-3">
                        <StageBadge stage={call.stage} />
                      </td>
                      <td className="px-4 py-3">
                        <div>
                          <p className="text-slate-100 font-mono text-xs truncate max-w-50" title={call.model_name}>
                            {call.model_name || '—'}
                          </p>
                          <p className="text-[10px] text-slate-500">{call.provider || '—'}</p>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right text-blue-400 font-mono">
                        {(Number(call.input_tokens) || 0).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right text-emerald-400 font-mono">
                        {(Number(call.output_tokens) || 0).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="text-amber-400 font-mono text-xs">
                          {formatCurrency(call.cost_usd, 'USD')}
                        </div>
                        <div className="text-pink-400/70 font-mono text-[10px]">
                          {formatCurrency(call.cost_inr, 'INR')}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                        {call.created_at ? new Date(call.created_at).toLocaleString() : '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Load more */}
          <div className="px-4 py-3 border-t border-slate-800 bg-slate-900/50">
            {loading ? (
              <div className="flex justify-center py-2">
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
              <p className="text-center text-xs text-slate-600">All {total} records loaded</p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
