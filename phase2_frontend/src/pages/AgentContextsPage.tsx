import { useEffect, useMemo, useState } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import type { AgentId, UiAgent } from '../api/client';
import { getAgent, updateAgent } from '../api/client';

type TabId = 'selector' | 'final';

export default function AgentContextsPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const id = (agentId ?? '') as AgentId;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [agent, setAgent] = useState<UiAgent | null>(null);

  const [tab, setTab] = useState<TabId>('selector');
  const [skillSelectorContext, setSkillSelectorContext] = useState('');
  const [finalOutputFormattingContext, setFinalOutputFormattingContext] = useState('');

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setErr(null);
    getAgent(id)
      .then(({ agent: a }) => {
        setAgent(a);
        setSkillSelectorContext(a.skillSelectorContext ?? '');
        setFinalOutputFormattingContext(a.finalOutputFormattingContext ?? '');
      })
      .catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load agent'))
      .finally(() => setLoading(false));
  }, [id]);

  const tabs = useMemo(
    () =>
      [
        { id: 'selector' as const, label: 'Skill selector context' },
        { id: 'final' as const, label: 'Final output formatting context' },
      ] as const,
    []
  );

  const current = tab === 'selector'
    ? { value: skillSelectorContext, setValue: setSkillSelectorContext }
    : { value: finalOutputFormattingContext, setValue: setFinalOutputFormattingContext };

  const placeholder =
    tab === 'selector'
      ? 'Used when selecting which skill to run next.\n\nExample:\n- Prefer scrape-playwright for JS-heavy sites.\n- Never call scrape-agentbrowser.\n- Always include the current user goal.'
      : 'Used to generate the final response from all gathered raw context.\n\nTip: if you want raw output, say: "Return the gathered context verbatim."';

  const handleSave = async () => {
    if (!id) return;
    setSaving(true);
    setErr(null);
    try {
      const { agent: updated } = await updateAgent(id, {
        skillSelectorContext,
        finalOutputFormattingContext,
      });
      setAgent(updated);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!id) {
    return (
      <div className="p-6">
        <p className="text-sm text-slate-600">Missing agent id.</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-widest text-slate-400 font-semibold">Agent contexts</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xl">{agent?.emoji ?? '🤖'}</span>
            <h1 className="text-lg font-semibold text-slate-900 truncate">
              {agent?.name ?? id}
            </h1>
            <span className="text-xs text-slate-400 font-mono truncate">{id}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <NavLink
            to="/agents"
            className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
          >
            Back
          </NavLink>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || loading}
            className="px-3 py-2 text-xs font-semibold rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {err && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
          Loading…
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
          <div className="flex items-center gap-1 border-b border-slate-200 bg-slate-50 px-2 py-2 overflow-x-auto">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap ${
                  tab === t.id
                    ? 'bg-white border border-slate-200 text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:bg-white/70'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="p-4 space-y-3">
            <p className="text-xs text-slate-500">
              This text is loaded from the database per agent. It will be used automatically when you chat with this agent id.
            </p>
            <textarea
              value={current.value}
              onChange={(e) => current.setValue(e.target.value)}
              placeholder={placeholder}
              className="w-full min-h-[320px] font-mono text-xs rounded-xl border border-slate-200 bg-slate-50 p-3 outline-none focus:ring-2 focus:ring-violet-200"
            />
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={async () => {
                  // Save current contexts, then go back to Agents list
                  await handleSave();
                  navigate('/agents');
                }}
                disabled={saving}
                className="text-xs text-slate-500 hover:text-slate-800 disabled:opacity-60"
              >
                Done
              </button>
              <span className="text-xs text-slate-400">
                {current.value.length.toLocaleString()} chars
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

