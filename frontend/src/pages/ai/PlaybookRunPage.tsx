import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import PlaybookViewer from '../../components/PlaybookViewer';
import { getPlaybookRun } from '../../api';
import type { PlaybookRunDetail } from '../../api/types';

export default function PlaybookRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<PlaybookRunDetail | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!runId) return;
    let active = true;
    void getPlaybookRun(runId)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e: Error) => {
        if (active) setError(e?.message || 'Failed to load playbook');
      });
    return () => {
      active = false;
    };
  }, [runId]);

  if (!runId) {
    return (
      <div className="p-8 text-center text-slate-400">
        Missing playbook id.
        <button type="button" className="mt-4 block mx-auto text-violet-400" onClick={() => navigate('/')}>
          Home
        </button>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-center">
        <p className="text-red-400">{error}</p>
        <button type="button" className="mt-4 text-sm text-violet-400 hover:text-violet-300" onClick={() => navigate(-1)}>
          ← Back
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading playbook…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6">
      <div className="max-w-4xl mx-auto space-y-4">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-sm text-slate-400 hover:text-white transition-colors"
        >
          ← Back
        </button>
        <div>
          <h1 className="text-xl font-semibold text-slate-100">{data.title}</h1>
          {(data.domain || data.task) && (
            <p className="text-sm text-slate-500 mt-1">
              {[data.domain, data.task].filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
        <div className="rounded-2xl bg-[#f8f7ff] p-4">
          <PlaybookViewer playbookData={data.playbookData} />
        </div>
        {data.crossAgentActions && data.crossAgentActions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {data.crossAgentActions.map((action, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() =>
                  navigate('/new', {
                    state: {
                      agentId: action.agentId,
                      initialMessage: action.initialMessage,
                    },
                  })
                }
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-indigo-600 text-white hover:from-violet-700 hover:to-indigo-700 transition-all"
              >
                {action.icon && <span className="text-base">{action.icon}</span>}
                {action.label}
                <span className="text-white/60">→</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
