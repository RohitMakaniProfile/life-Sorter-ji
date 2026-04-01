import { clsx } from 'clsx';
import PlaybookViewer from '../../PlaybookViewer';

export default function PlaybookStage({
  showGapQuestions,
  gapQuestions,
  gapAnswers,
  setGapAnswers,
  onGapSubmit,
  playbookStreaming,
  playbookText,
  playbookDone,
  playbookResult,
  onDeepAnalysis,
}) {
  const gapComplete = gapQuestions.length === 0 || gapQuestions.every((_, i) => gapAnswers[i]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-8 py-6">
      <h1 className="m-0 mb-5 text-center text-[clamp(20px,2.5vw,32px)] font-extrabold text-white">
        {showGapQuestions ? 'A Few More Questions' : playbookDone ? 'Your Playbook' : 'Generating Your Playbook…'}
      </h1>

      {showGapQuestions && (
        <div className="mx-auto flex w-full max-w-[640px] flex-col gap-5">
          {gapQuestions.map((q, i) => {
            const qLabel = typeof q === 'string' ? q : q.question;
            const opts = typeof q === 'object' && Array.isArray(q.options) ? q.options : [];
            return (
              <div
                key={i}
                className="rounded-xl border border-white/12 bg-white/[0.03] px-5 py-4"
              >
                <p className="m-0 mb-3 text-sm font-semibold text-white/90">{qLabel}</p>
                {opts.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    {opts.map((opt, oi) => {
                      const optKey = opt.match(/^([A-E])\)/)?.[1] || String.fromCharCode(65 + oi);
                      const selected = gapAnswers[i] === optKey;
                      return (
                        <button
                          key={oi}
                          type="button"
                          onClick={() => setGapAnswers((prev) => ({ ...prev, [i]: optKey }))}
                          className={clsx(
                            'cursor-pointer rounded-lg border px-3.5 py-2.5 text-left text-[13px] transition-all',
                            selected
                              ? 'border-[1.5px] border-[#857BFF] bg-[rgba(133,123,255,0.18)] font-bold text-white'
                              : 'border border-white/12 bg-white/[0.04] font-normal text-white/75',
                          )}
                        >
                          {opt}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <textarea
                    rows={3}
                    placeholder="Your answer…"
                    value={gapAnswers[i] || ''}
                    onChange={(e) => setGapAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
                    className="box-border w-full resize-y rounded-lg border border-white/10 bg-white/[0.05] px-3.5 py-2.5 text-[13px] text-white outline-none"
                  />
                )}
              </div>
            );
          })}
          <button
            type="button"
            onClick={onGapSubmit}
            disabled={!gapComplete}
            className={clsx(
              'rounded-[10px] border-none py-3 text-sm font-extrabold text-white',
              gapComplete
                ? 'cursor-pointer bg-gradient-to-r from-[#857BFF] to-[#BF69A2]'
                : 'cursor-not-allowed opacity-50',
            )}
          >
            Generate Playbook
          </button>
        </div>
      )}

      {!showGapQuestions && (
        <div className="mx-auto w-full max-w-[800px] flex-1 overflow-auto">
          {playbookStreaming && !playbookText && (
            <div className="pt-10 text-center text-sm text-white/40">Thinking…</div>
          )}

          {playbookText && !playbookDone && (
            <pre className="m-0 whitespace-pre-wrap font-inherit text-sm leading-[1.8] text-white/85">
              {playbookText}
              <span className="opacity-50">▍</span>
            </pre>
          )}

          {playbookDone && (
            <>
              <div className="mb-4 rounded-2xl bg-[#f8f7ff] p-4">
                <PlaybookViewer
                  playbookData={{
                    playbook: playbookResult?.playbook || playbookText,
                    websiteAudit: playbookResult?.website_audit || '',
                    contextBrief: playbookResult?.context_brief || '',
                    icpCard: playbookResult?.icp_card || '',
                  }}
                />
              </div>
              <button
                type="button"
                onClick={onDeepAnalysis}
                className="mb-6 mt-2 w-full cursor-pointer rounded-[10px] border-none bg-gradient-to-br from-indigo-500 to-violet-500 py-3 px-8 text-[15px] font-bold text-white"
              >
                Do Deep Analysis →
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
