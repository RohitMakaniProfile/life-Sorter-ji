import { useEffect, useRef, useState } from 'react';
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
  showRetry,
  onRetry,
  retryLabel = 'Retry',
  onCancel,
  onRetryPlaybook,
}) {
  const gapComplete = gapQuestions.length === 0 || gapQuestions.every((_, i) => gapAnswers[i]);
  const streamContainerRef = useRef(null);
  const [showCancelModal, setShowCancelModal] = useState(false);

  useEffect(() => {
    if (!playbookStreaming || !playbookText || playbookDone) return;
    const el = streamContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [playbookText, playbookStreaming, playbookDone]);

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

      {/* Cancel confirmation modal */}
      {showCancelModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-[#1a1030] p-6 shadow-2xl">
            <h3 className="m-0 mb-2 text-lg font-bold text-white">Cancel Playbook?</h3>
            <p className="m-0 mb-6 text-sm text-white/50">
              Your playbook is being generated. What would you like to do?
            </p>
            <div className="flex flex-col gap-3">
              <button
                type="button"
                onClick={() => { setShowCancelModal(false); if (onRetryPlaybook) onRetryPlaybook(); }}
                className="w-full cursor-pointer rounded-xl border-none bg-gradient-to-r from-[#857BFF] to-[#BF69A2] py-3 text-sm font-bold text-white"
              >
                Retry — Generate Again
              </button>
              <button
                type="button"
                onClick={() => { setShowCancelModal(false); if (onCancel) onCancel(); }}
                className="w-full cursor-pointer rounded-xl border border-white/15 bg-white/[0.05] py-3 text-sm font-semibold text-white/70 transition hover:bg-white/[0.10] hover:text-white"
              >
                Return to Homepage
              </button>
              <button
                type="button"
                onClick={() => setShowCancelModal(false)}
                className="w-full cursor-pointer rounded-xl border-none bg-transparent py-2 text-sm text-white/30 transition hover:text-white/50"
              >
                Keep Waiting
              </button>
            </div>
          </div>
        </div>
      )}

      {!showGapQuestions && (
        <div ref={streamContainerRef} className="mx-auto w-full max-w-[800px] flex-1 overflow-auto">
          {playbookStreaming && !playbookText && (
            <div className="pt-10 text-center text-sm text-white/40">Thinking…</div>
          )}

          {!playbookDone && !playbookText && (
            <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-20">
              <button
                type="button"
                onClick={() => setShowCancelModal(true)}
                className="cursor-pointer rounded-lg border border-white/15 bg-[#0d0d0d]/80 backdrop-blur-sm px-6 py-2.5 text-sm text-white/50 transition hover:bg-white/[0.08] hover:text-white/80"
              >
                Cancel
              </button>
            </div>
          )}

          {!playbookStreaming && !playbookDone && !playbookText && showRetry && (
            <div className="pt-10 text-center">
              <p className="m-0 text-sm text-white/50">
                No active playbook run found. Please click retry to start again.
              </p>
              <button
                type="button"
                onClick={onRetry}
                className="mt-4 cursor-pointer rounded-[10px] border-none bg-gradient-to-r from-[#857BFF] to-[#BF69A2] px-6 py-3 text-sm font-extrabold text-white"
              >
                {retryLabel}
              </button>
            </div>
          )}

          {playbookText && !playbookDone && (
            <>
              <div className="mb-4 rounded-2xl bg-[#f8f7ff] p-4">
                <PlaybookViewer
                  playbookData={{
                    playbook: `${playbookText}\n\n▍`,
                    websiteAudit: playbookResult?.website_audit || '',
                    contextBrief: playbookResult?.context_brief || '',
                    icpCard: playbookResult?.icp_card || '',
                  }}
                />
              </div>
              <div className="mb-6 flex justify-center">
                <button
                  type="button"
                  onClick={() => setShowCancelModal(true)}
                  className="cursor-pointer rounded-lg border border-white/15 bg-white/[0.05] px-6 py-2.5 text-sm text-white/50 transition hover:bg-white/[0.10] hover:text-white/80"
                >
                  Cancel
                </button>
              </div>
            </>
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
