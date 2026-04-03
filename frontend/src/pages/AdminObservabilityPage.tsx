import { useEffect, useMemo, useState } from 'react';
import { getObservabilitySnapshot } from '../api';
import type { ObservabilitySnapshot } from '../api/types';

export default function AdminObservabilityPage() {
  const [data, setData] = useState<ObservabilitySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const servicesUp = useMemo(() => data?.services.filter((s) => s.ok).length ?? 0, [data]);
  const servicesTotal = useMemo(() => data?.services.length ?? 0, [data]);

  async function load(showRefreshState = false) {
    if (showRefreshState) setRefreshing(true);
    else setLoading(true);
    setErr(null);
    try {
      const r = await getObservabilitySnapshot();
      setData(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load observability snapshot');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void load(false);
  }, []);

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-slate-100">System Observability</h1>
            <p className="text-sm text-slate-500 mt-1">
              Service health, integration connectivity, and recent failure signals.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={refreshing}
            className="px-4 py-2 rounded-xl bg-slate-800 text-slate-100 text-sm font-semibold hover:bg-slate-700 disabled:opacity-60"
          >
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {loading ? (
          <div className="text-center py-16 text-slate-500">
            <div className="inline-block w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mb-3" />
            <p className="font-medium">Loading observability data…</p>
          </div>
        ) : err ? (
          <div className="mt-6 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {err}
          </div>
        ) : (
          <>
            <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                <div className="text-xs text-slate-500">Services Up</div>
                <div className="text-2xl font-bold text-slate-100 mt-1">
                  {servicesUp}/{servicesTotal}
                </div>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                <div className="text-xs text-slate-500">Snapshot Time (UTC)</div>
                <div className="text-sm font-semibold text-slate-100 mt-2 break-all">
                  {data?.snapshotAt || '-'}
                </div>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                <div className="text-xs text-slate-500">Recent Errors (shown)</div>
                <div className="text-2xl font-bold text-slate-100 mt-1">
                  {data?.recentErrors?.length ?? 0}
                </div>
              </div>
            </div>

            <div className="mt-6 rounded-xl border border-slate-800 overflow-hidden">
              <div className="px-4 py-3 bg-slate-900 text-sm font-semibold text-slate-200">Connected Services</div>
              <div className="divide-y divide-slate-800 bg-slate-950">
                {(data?.services || []).map((s) => (
                  <div key={s.name} className="px-4 py-3 flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-100">{s.name}</div>
                      <div className="text-xs text-slate-500 mt-1">{s.detail}</div>
                    </div>
                    <div
                      className={`text-xs px-2 py-1 rounded-full font-semibold ${
                        s.ok ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'
                      }`}
                    >
                      {s.ok ? 'UP / CONFIGURED' : 'DOWN / MISSING'}
                    </div>
                  </div>
                ))}
                {(data?.services || []).length === 0 && (
                  <div className="px-4 py-4 text-sm text-slate-500">No service data.</div>
                )}
              </div>
            </div>

            <div className="mt-6 rounded-xl border border-slate-800 overflow-hidden">
              <div className="px-4 py-3 bg-slate-900 text-sm font-semibold text-slate-200">Error Counters</div>
              <div className="bg-slate-950 p-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
                {Object.entries(data?.counters || {}).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-slate-800 p-3">
                    <div className="text-xs text-slate-500">{k}</div>
                    <div className="text-lg font-semibold text-slate-100 mt-1">{v}</div>
                  </div>
                ))}
                {Object.keys(data?.counters || {}).length === 0 && (
                  <div className="text-sm text-slate-500">No counters available.</div>
                )}
              </div>
            </div>

            <div className="mt-6 rounded-xl border border-slate-800 overflow-hidden">
              <div className="px-4 py-3 bg-slate-900 text-sm font-semibold text-slate-200">Recent Failed Errors</div>
              <div className="divide-y divide-slate-800 bg-slate-950">
                {(data?.recentErrors || []).map((e, idx) => (
                  <div key={`${e.source}-${e.at}-${idx}`} className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">{e.source}</span>
                      <span className="text-xs text-slate-500">{e.at || '-'}</span>
                    </div>
                    <div className="text-sm text-slate-100 mt-2">{e.message}</div>
                    {e.meta && (
                      <pre className="mt-2 rounded-lg border border-slate-800 bg-slate-900 p-2 text-xs text-slate-300 overflow-x-auto">
                        {JSON.stringify(e.meta, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
                {(data?.recentErrors || []).length === 0 && (
                  <div className="px-4 py-4 text-sm text-slate-500">No recent errors captured.</div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

