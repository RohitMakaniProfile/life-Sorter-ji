import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getSkillCallDetail } from '../api';
import type { AdminSkillCallDetail } from '../api/types';

// ── Interactive JSON viewer ──────────────────────────────────────────────────

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

// One row = one key (or array index). Clicking the row toggles children.
function JsonRow({
  label,
  value,
  isLast,
}: {
  label: string;
  value: JsonValue;
  isLast: boolean;
}) {
  const [open, setOpen] = useState(false);
  const collapsible = isCollapsible(value);

  return (
    <div>
      <div
        className={`flex items-baseline gap-1.5 py-0.5 px-2 rounded ${
          collapsible ? 'cursor-pointer hover:bg-slate-800/60 select-none' : ''
        }`}
        onClick={collapsible ? () => setOpen((v) => !v) : undefined}
      >
        {collapsible && (
          <span className="text-slate-500 text-[10px] w-3 flex-shrink-0">
            {open ? '▾' : '▸'}
          </span>
        )}
        {!collapsible && <span className="w-3 flex-shrink-0" />}
        <span className="text-sky-400 font-mono text-xs flex-shrink-0">{label}</span>
        <span className="text-slate-600 text-xs">:</span>
        {!collapsible && (
          <span className="text-xs font-mono">
            <Scalar value={value as string | number | boolean | null} />
          </span>
        )}
        {collapsible && !open && (
          <span className="text-xs font-mono">
            <CollapsedPreview value={value} />
          </span>
        )}
        {!isLast && <span className="text-slate-700 text-xs">,</span>}
      </div>

      {collapsible && open && (
        <div className="ml-6 border-l border-slate-700/60">
          <JsonTree value={value} />
        </div>
      )}
    </div>
  );
}

function JsonTree({ value }: { value: JsonValue }) {
  if (Array.isArray(value)) {
    return (
      <div>
        {value.map((item, i) => (
          <JsonRow key={i} label={String(i)} value={item as JsonValue} isLast={i === value.length - 1} />
        ))}
      </div>
    );
  }
  if (value !== null && typeof value === 'object') {
    const keys = Object.keys(value as object);
    return (
      <div>
        {keys.map((k, i) => (
          <JsonRow key={k} label={k} value={(value as Record<string, JsonValue>)[k]} isLast={i === keys.length - 1} />
        ))}
      </div>
    );
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
      <div className="px-4 py-2.5 bg-slate-900 text-xs font-semibold text-slate-300 uppercase tracking-wider">
        {label}
      </div>
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

// ── State badge ──────────────────────────────────────────────────────────────

function StateBadge({ state }: { state: string }) {
  const cls =
    state === 'done'
      ? 'bg-emerald-500/20 text-emerald-300'
      : state === 'error'
      ? 'bg-red-500/20 text-red-300'
      : 'bg-amber-500/20 text-amber-300';
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {state.toUpperCase()}
    </span>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AdminSkillCallDetailPage() {
  const { skillCallId } = useParams<{ skillCallId: string }>();
  const navigate = useNavigate();
  const [call, setCall] = useState<AdminSkillCallDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!skillCallId) return;
    setLoading(true);
    getSkillCallDetail(skillCallId)
      .then((res) => setCall(res.call))
      .catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [skillCallId]);

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="text-slate-400 hover:text-slate-100 text-sm px-3 py-1.5 rounded-lg border border-slate-700 hover:bg-slate-800"
          >
            ← Back
          </button>
          <h1 className="text-lg font-bold text-slate-100">Skill Call Detail</h1>
          {call && <StateBadge state={call.state} />}
        </div>

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {err && (
          <div className="px-4 py-3 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {err}
          </div>
        )}

        {call && (
          <div className="space-y-5">
            {/* Meta grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                { label: 'ID', value: call.id },
                { label: 'Skill', value: call.skill_id },
                { label: 'Conversation', value: call.conversation_id },
                { label: 'Message ID', value: call.message_id },
                { label: 'Run ID', value: call.run_id },
                { label: 'Duration', value: call.duration_ms != null ? `${call.duration_ms} ms` : '—' },
                {
                  label: 'Started',
                  value: call.started_at ? new Date(call.started_at).toLocaleString() : '—',
                },
                {
                  label: 'Ended',
                  value: call.ended_at ? new Date(call.ended_at).toLocaleString() : '—',
                },
              ].map(({ label, value }) => (
                <div key={label} className="rounded-xl border border-slate-800 bg-slate-950 px-4 py-3">
                  <p className="text-xs text-slate-500 mb-1">{label}</p>
                  <p className="text-sm text-slate-100 font-mono break-all">{value}</p>
                </div>
              ))}
            </div>

            {/* Error */}
            {call.error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3">
                <p className="text-xs text-red-400 mb-1 font-semibold">Error</p>
                <p className="text-sm text-red-300 font-mono break-all">{call.error}</p>
              </div>
            )}

            {/* Input JSON */}
            <JsonViewer data={call.input} label="Input" />

            {/* Output JSON */}
            <JsonViewer data={call.output} label="Output" />

            {/* Streamed text */}
            <div className="rounded-xl border border-slate-800 overflow-hidden">
              <div className="px-4 py-2.5 bg-slate-900 text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Streamed Text (raw)
              </div>
              <pre className="p-4 bg-slate-950 text-xs text-slate-300 whitespace-pre-wrap break-all overflow-x-auto max-h-[500px] overflow-y-auto leading-relaxed">
                {call.streamed_text || <span className="text-slate-600">(empty)</span>}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}