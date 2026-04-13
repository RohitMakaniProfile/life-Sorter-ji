import { useEffect, useState } from 'react';
import PlaybookViewer from '../../PlaybookViewer';
import { getPlaybookRun } from '../../../api';

export default function HistoryPlaybookStage({ runId, onBack, onDeepAnalysis, onStartNewJourney }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    setLoading(true);
    setData(null);
    setError(null);
    getPlaybookRun(runId)
      .then((d) => { if (active) { setData(d); setLoading(false); } })
      .catch((e) => { if (active) { setError(e?.message || 'Failed to load playbook'); setLoading(false); } });
    return () => { active = false; };
  }, [runId]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-8 py-6">
      <div className="mb-2 flex items-center">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-white/50 transition-colors hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back to history
        </button>
      </div>

      <h1 className="m-0 mb-5 text-center text-[clamp(20px,2.5vw,32px)] font-extrabold text-white">
        Your Playbook
      </h1>

      {loading && (
        <div className="flex flex-1 items-center justify-center">
          <div className="flex items-center gap-3 text-slate-400">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" />
            <span className="text-sm">Loading playbook…</span>
          </div>
        </div>
      )}

      {error && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <p className="text-sm text-red-400">{error}</p>
          <button
            type="button"
            onClick={onBack}
            className="text-sm text-violet-400 hover:text-violet-300"
          >
            ← Back to history
          </button>
        </div>
      )}

      {data && (
        <div className="mx-auto w-full max-w-[800px] flex-1 overflow-auto">
          <div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-4 shadow-sm">
            <PlaybookViewer
              initialPhase="playbook"
              themeMode="dark"
              playbookData={data.playbookData}
            />
          </div>
          <div className="flex flex-row gap-4">
            <button
              type="button"
              onClick={onDeepAnalysis}
              className="w-full cursor-pointer rounded-[10px] border-none bg-gradient-to-br from-indigo-500 to-violet-500 py-3 px-8 text-[15px] font-bold text-white"
            >
              Do Deep Analysis →
            </button>
            <button
              type="button"
              onClick={onStartNewJourney}
              className="w-full cursor-pointer rounded-[10px] border border-white/15 bg-transparent py-2.5 px-8 text-[14px] font-semibold text-white/50 transition hover:text-white/80"
            >
              Start New Journey
            </button>
          </div>
        </div>
      )}
    </div>
  );
}