import { useEffect, useState } from 'react';
import { listWebsiteAuditLogs, getWebsiteAuditLogDetail } from '../api';
import type { AdminWebsiteAuditLog, AdminWebsiteAuditLogDetail } from '../api/types';

// ── Reusable JSON tree (same pattern as AdminSkillCallDetailPage) ──────────────

type JsonValue = string | number | boolean | null | JsonValue[] | { [k: string]: JsonValue };

function isCollapsible(v: JsonValue): boolean {
  return v !== null && typeof v === 'object' && (Array.isArray(v) ? v.length > 0 : Object.keys(v).length > 0);
}

function Scalar({ value }: { value: string | number | boolean | null }) {
  if (value === null) return <span className="text-slate-500">null</span>;
  if (typeof value === 'boolean') return <span className="text-violet-400">{String(value)}</span>;
  if (typeof value === 'number') return <span className="text-emerald-400">{value}</span>;
  return <span className="text-amber-300">"{String(value)}"</span>;
}

function CollapsedPreview({ value }: { value: JsonValue }) {
  if (Array.isArray(value)) return <span className="text-slate-500 text-xs">[{value.length} items]</span>;
  if (value !== null && typeof value === 'object') {
    const keys = Object.keys(value as object);
    return <span className="text-slate-500 text-xs">{'{'}{keys.slice(0, 3).join(', ')}{keys.length > 3 ? ', …' : ''}{'}'}</span>;
  }
  return null;
}

function JsonRow({ label, value, isLast }: { label: string; value: JsonValue; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const collapsible = isCollapsible(value);
  return (
    <div>
      <div
        className={`flex items-baseline gap-1.5 py-0.5 px-2 rounded ${collapsible ? 'cursor-pointer hover:bg-slate-800/60 select-none' : ''}`}
        onClick={collapsible ? () => setOpen((v) => !v) : undefined}
      >
        {collapsible && <span className="text-slate-500 text-[10px] w-3 flex-shrink-0">{open ? '▾' : '▸'}</span>}
        {!collapsible && <span className="w-3 flex-shrink-0" />}
        <span className="text-sky-400 font-mono text-xs flex-shrink-0">{label}</span>
        <span className="text-slate-600 text-xs">:</span>
        {!collapsible && <span className="text-xs font-mono"><Scalar value={value as string | number | boolean | null} /></span>}
        {collapsible && !open && <span className="text-xs font-mono"><CollapsedPreview value={value} /></span>}
        {!isLast && <span className="text-slate-700 text-xs">,</span>}
      </div>
      {collapsible && open && (
        <div className="ml-6 border-l border-slate-700/60"><JsonTree value={value} /></div>
      )}
    </div>
  );
}

function JsonTree({ value }: { value: JsonValue }) {
  if (Array.isArray(value)) {
    return <div>{value.map((item, i) => <JsonRow key={i} label={String(i)} value={item as JsonValue} isLast={i === value.length - 1} />)}</div>;
  }
  if (value !== null && typeof value === 'object') {
    const keys = Object.keys(value as object);
    return <div>{keys.map((k, i) => <JsonRow key={k} label={k} value={(value as Record<string, JsonValue>)[k]} isLast={i === keys.length - 1} />)}</div>;
  }
  return null;
}

function JsonViewer({ data, label }: { data: unknown; label: string }) {
  let parsed = data;
  if (typeof parsed === 'string') {
    try { parsed = JSON.parse(parsed); } catch { /* leave as string */ }
  }
  return (
    <div className="rounded-xl border border-slate-800 overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-900 text-xs font-semibold text-slate-300 uppercase tracking-wider">{label}</div>
      <div className="py-2 bg-slate-950 font-mono text-xs leading-relaxed overflow-x-auto">
        {parsed === null || parsed === undefined ? (
          <span className="px-4 text-slate-500">null</span>
        ) : typeof parsed === 'object' ? (
          <JsonTree value={parsed as JsonValue} />
        ) : (
          <span className="px-4"><Scalar value={parsed as string | number | boolean | null} /></span>
        )}
      </div>
    </div>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ success }: { success: boolean }) {
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${success ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'}`}>
      {success ? 'OK' : 'FAILED'}
    </span>
  );
}

// ── Detail drawer ─────────────────────────────────────────────────────────────

function DetailDrawer({ logId, onClose }: { logId: number; onClose: () => void }) {
  const [log, setLog] = useState<AdminWebsiteAuditLogDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    getWebsiteAuditLogDetail(logId)
      .then((r) => setLog(r.log))
      .catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [logId]);

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Overlay */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Panel */}
      <div className="relative ml-auto w-full max-w-3xl h-full bg-slate-950 border-l border-slate-800 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 flex-shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-bold text-slate-100">Audit Log #{logId}</h2>
            {log && <StatusBadge success={log.success} />}
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-100 text-sm px-3 py-1.5 rounded-lg border border-slate-700 hover:bg-slate-800">
            Close
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && (
            <div className="flex items-center justify-center py-20">
              <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {err && (
            <div className="px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">{err}</div>
          )}

          {log && (
            <>
              {/* Meta */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {[
                  { label: 'ID', value: String(log.id) },
                  { label: 'Onboarding', value: log.onboarding_id || '—' },
                  { label: 'Model', value: log.model || '—' },
                  { label: 'Input tokens', value: String(log.input_tokens) },
                  { label: 'Output tokens', value: String(log.output_tokens) },
                  { label: 'Latency', value: `${log.latency_ms} ms` },
                  { label: 'Created', value: log.created_at ? new Date(log.created_at).toLocaleString() : '—' },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-3">
                    <p className="text-xs text-slate-500 mb-1">{label}</p>
                    <p className="text-sm text-slate-100 font-mono break-all">{value}</p>
                  </div>
                ))}
              </div>

              {/* Error */}
              {log.error_msg && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3">
                  <p className="text-xs text-red-400 mb-1 font-semibold">Error</p>
                  <p className="text-sm text-red-300 font-mono break-all">{log.error_msg}</p>
                </div>
              )}

              {/* System prompt */}
              {log.input_payload?.system_prompt && (
                <div className="rounded-xl border border-slate-800 overflow-hidden">
                  <div className="px-4 py-2.5 bg-slate-900 text-xs font-semibold text-slate-300 uppercase tracking-wider">System Prompt</div>
                  <pre className="p-4 bg-slate-950 text-xs text-slate-300 whitespace-pre-wrap break-all overflow-x-auto max-h-80 overflow-y-auto leading-relaxed">
                    {log.input_payload.system_prompt}
                  </pre>
                </div>
              )}

              {/* User payload */}
              <JsonViewer data={log.input_payload?.user_payload} label="User Payload (Input)" />

              {/* Output */}
              <div className="rounded-xl border border-slate-800 overflow-hidden">
                <div className="px-4 py-2.5 bg-slate-900 text-xs font-semibold text-slate-300 uppercase tracking-wider">Output</div>
                <pre className="p-4 bg-slate-950 text-xs text-slate-300 whitespace-pre-wrap break-all overflow-x-auto max-h-[500px] overflow-y-auto leading-relaxed">
                  {log.output || <span className="text-slate-600">(empty)</span>}
                </pre>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

export default function AdminWebsiteAuditLogsPage() {
  const [logs, setLogs] = useState<AdminWebsiteAuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filterOnboarding, setFilterOnboarding] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  async function load(oid: string, off: number) {
    setLoading(true);
    setErr(null);
    try {
      const r = await listWebsiteAuditLogs(oid || null, PAGE_SIZE, off);
      setLogs(r.logs);
      setTotal(r.total);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(filterOnboarding, offset);
  }, []);

  function applyFilter() {
    setOffset(0);
    void load(filterOnboarding, 0);
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-xl font-bold text-slate-100">Website Audit Logs</h1>
            <p className="text-sm text-slate-500 mt-1">Every LLM call made by generate_website_audit — input, output, success/failure.</p>
          </div>
          <button
            type="button"
            onClick={() => void load(filterOnboarding, offset)}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-slate-800 text-slate-100 text-sm font-semibold hover:bg-slate-700 disabled:opacity-60"
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        {/* Filter bar */}
        <div className="flex gap-2 mb-4">
          <input
            type="text"
            placeholder="Filter by onboarding_id (UUID)"
            value={filterOnboarding}
            onChange={(e) => setFilterOnboarding(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && applyFilter()}
            className="flex-1 max-w-sm px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-violet-500"
          />
          <button
            type="button"
            onClick={applyFilter}
            className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-500"
          >
            Filter
          </button>
          {filterOnboarding && (
            <button
              type="button"
              onClick={() => { setFilterOnboarding(''); setOffset(0); void load('', 0); }}
              className="px-4 py-2 rounded-lg bg-slate-700 text-slate-300 text-sm hover:bg-slate-600"
            >
              Clear
            </button>
          )}
        </div>

        {err && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">{err}</div>
        )}

        {/* Stats strip */}
        <div className="mb-3 text-xs text-slate-500">
          {total} total log{total !== 1 ? 's' : ''}{filterOnboarding ? ` for onboarding ${filterOnboarding}` : ''}
          {totalPages > 1 ? ` — page ${currentPage} / ${totalPages}` : ''}
        </div>

        {/* Table */}
        <div className="rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-900 text-xs text-slate-400 uppercase tracking-wider">
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Onboarding</th>
                <th className="px-4 py-3 text-left">Model</th>
                <th className="px-4 py-3 text-right">In Tok</th>
                <th className="px-4 py-3 text-right">Out Tok</th>
                <th className="px-4 py-3 text-right">Latency</th>
                <th className="px-4 py-3 text-left">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {loading && logs.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-slate-500">
                    <div className="inline-block w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mr-2 align-middle" />
                    Loading…
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-slate-500">No logs found.</td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr
                    key={log.id}
                    className="bg-slate-950 hover:bg-slate-900 cursor-pointer transition-colors"
                    onClick={() => setSelectedId(log.id)}
                  >
                    <td className="px-4 py-3 font-mono text-slate-400">{log.id}</td>
                    <td className="px-4 py-3"><StatusBadge success={log.success} /></td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-400 max-w-[160px] truncate">
                      {log.onboarding_id ? log.onboarding_id.slice(0, 8) + '…' : '—'}
                    </td>
                    <td className="px-4 py-3 text-slate-300 text-xs">{log.model || '—'}</td>
                    <td className="px-4 py-3 text-right text-slate-300">{log.input_tokens}</td>
                    <td className="px-4 py-3 text-right text-slate-300">{log.output_tokens}</td>
                    <td className="px-4 py-3 text-right text-slate-400 text-xs">{log.latency_ms} ms</td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                      {log.created_at ? new Date(log.created_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <button
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => { const o = Math.max(0, offset - PAGE_SIZE); setOffset(o); void load(filterOnboarding, o); }}
              className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-sm disabled:opacity-40 hover:bg-slate-700"
            >
              ← Prev
            </button>
            <span className="text-xs text-slate-500">Page {currentPage} of {totalPages}</span>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= total || loading}
              onClick={() => { const o = offset + PAGE_SIZE; setOffset(o); void load(filterOnboarding, o); }}
              className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-sm disabled:opacity-40 hover:bg-slate-700"
            >
              Next →
            </button>
          </div>
        )}
      </div>

      {/* Detail drawer */}
      {selectedId !== null && (
        <DetailDrawer logId={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  );
}
