import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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

  const title = data?.task ? `Playbook: ${data.task}` : 'Your Playbook';
  const playbookContent = data?.playbookData?.playbook || '';

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

      <h1 className="m-0 mb-5 text-center text-[clamp(18px,2vw,26px)] font-bold text-white">
        {loading ? 'Loading…' : title}
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
          <button type="button" onClick={onBack} className="text-sm text-violet-400 hover:text-violet-300">
            ← Back to history
          </button>
        </div>
      )}

      {data && (
        <div className="mx-auto w-full max-w-[720px] flex-1 overflow-auto">
          <div className="rounded-xl border border-white/10 bg-[#161616] p-5">
            <div className="playbook-markdown text-sm leading-relaxed text-white/85">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{playbookContent}</ReactMarkdown>
            </div>
          </div>
          <div className="mt-5 flex flex-row gap-4">
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
