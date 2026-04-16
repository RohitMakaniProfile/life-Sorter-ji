import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const PLAYBOOK_DELIMITER = '---SECTION:playbook---';

function extractPlaybookContent(text) {
  const idx = text.indexOf(PLAYBOOK_DELIMITER);
  if (idx !== -1) return text.slice(idx + PLAYBOOK_DELIMITER.length).trim();
  // Strip all section delimiters and return full text
  return text.replace(/---SECTION:[a-z_]+---/g, '').trim();
}

export default function PlaybookStage({
  task,
  showGapQuestions,
  gapQuestions,
  gapAnswers,
  gapCurrentIndex = 0,
  gapSavingIndex = null,
  onGapAnswer,
  playbookStreaming,
  playbookText,
  playbookDone,
  playbookResult,
  onGoHome,
  showRetry,
  onRetry,
  retryLabel = 'Retry',
  onCancel,
  onRetryPlaybook,
}) {
  const activeGap = Array.isArray(gapQuestions) ? gapQuestions[gapCurrentIndex] : null;
  const scrollContainerRef = useRef(null);
  const [showCancelModal, setShowCancelModal] = useState(false);

  const autoScrollEnabledRef = useRef(true);
  const isProgrammaticScrollRef = useRef(false);

  useEffect(() => {
    if (playbookStreaming && !playbookDone) {
      autoScrollEnabledRef.current = true;
    }
  }, [playbookStreaming, playbookDone]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const handleScroll = () => {
      if (isProgrammaticScrollRef.current) return;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      autoScrollEnabledRef.current = distanceFromBottom <= 40;
    };
    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [showGapQuestions]);

  useEffect(() => {
    if (!playbookStreaming || !playbookText || playbookDone) return;
    if (!autoScrollEnabledRef.current) return;
    const el = scrollContainerRef.current;
    if (!el) return;
    isProgrammaticScrollRef.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => { isProgrammaticScrollRef.current = false; });
  }, [playbookText, playbookStreaming, playbookDone]);

  const playbookContent = playbookDone
    ? (playbookResult?.playbook || extractPlaybookContent(playbookText || ''))
    : extractPlaybookContent(playbookText || '');

  // Derive task label: prefer prop, then extract from playbook h1
  // New prompt writes: # The "[Task Name]" Playbook
  const taskLabel = (() => {
    if (task) return task;
    const src = playbookContent || playbookText || '';
    // Match: # The "XYZ" Playbook  or  # The XYZ Playbook
    const m = src.match(/^#\s+The\s+"([^"]+)"\s+Playbook/im)
      || src.match(/^#\s+The\s+([^#\n]+?)\s+Playbook/im);
    return m ? m[1].trim() : null;
  })();

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">

      {/* ── Task header bar ── */}
      <div style={{
        flexShrink: 0,
        padding: '12px 24px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '.12em',
          textTransform: 'uppercase', color: '#475569',
        }}>
          {showGapQuestions ? 'A Few More Questions' : playbookDone ? 'Your Playbook' : 'Generating Playbook…'}
        </span>

        {!showGapQuestions && taskLabel && (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '5px 16px',
            background: 'rgba(139,92,246,0.10)',
            border: '1px solid rgba(139,92,246,0.22)',
            borderRadius: 999,
            maxWidth: '80%',
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8b5cf6', flexShrink: 0 }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#c4b5fd', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{taskLabel}</span>
          </div>
        )}

        {!showGapQuestions && !taskLabel && playbookStreaming && !playbookDone && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#8b5cf6', animation: 'pulse 1.2s ease-in-out infinite' }} />
            <span style={{ fontSize: 12, color: '#64748b' }}>Thinking…</span>
          </div>
        )}
      </div>

      {/* ── Scrollable content ── */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-8 py-6">

      {showGapQuestions && (
        <div className="mx-auto flex w-full max-w-[640px] flex-col gap-5">
          <div className="text-xs text-white/60">
            Question {Math.min(gapCurrentIndex + 1, gapQuestions.length)} of {gapQuestions.length}
          </div>
          {activeGap && (
            <div className="rounded-xl border border-white/12 bg-[#1a1a1a] px-5 py-4">
              <p className="m-0 mb-3 text-sm font-semibold text-white/90">
                {typeof activeGap === 'string' ? activeGap : activeGap.question}
              </p>
              <div className="flex flex-col gap-2">
                {(typeof activeGap === 'object' && Array.isArray(activeGap.options) ? activeGap.options : []).map((opt, oi) => {
                  const optKey = String(opt ?? '').match(/^([A-E])\)/)?.[1] || String.fromCharCode(65 + oi);
                  const selected = gapAnswers[gapCurrentIndex] === optKey;
                  const saving = gapSavingIndex === gapCurrentIndex;
                  return (
                    <button
                      key={oi}
                      type="button"
                      disabled={saving}
                      onClick={() => onGapAnswer?.(gapCurrentIndex, optKey, String(opt ?? ''))}
                      className={clsx(
                        'cursor-pointer rounded-lg border px-3.5 py-2.5 text-left text-[13px] transition-all disabled:opacity-60',
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
            </div>
          )}
        </div>
      )}

      {showCancelModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-[#1a1030] p-6 shadow-2xl">
            <h3 className="m-0 mb-2 text-lg font-bold text-white">Cancel Playbook?</h3>
            <p className="m-0 mb-6 text-sm text-white/50">Your playbook is being generated. What would you like to do?</p>
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
                Start New Journey
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
        <div ref={scrollContainerRef} className="mx-auto w-full max-w-[720px] flex-1 overflow-auto">
          {playbookStreaming && !playbookText && (
            <div className="pt-10 text-center text-sm text-white/40">Thinking…</div>
          )}

          {!playbookStreaming && !playbookDone && !playbookText && showRetry && (
            <div className="pt-10 text-center">
              <p className="m-0 text-sm text-white/50">No active playbook run found. Please click retry to start again.</p>
              <button
                type="button"
                onClick={onRetry}
                className="mt-4 cursor-pointer rounded-[10px] border-none bg-gradient-to-r from-[#857BFF] to-[#BF69A2] px-6 py-3 text-sm font-extrabold text-white"
              >
                {retryLabel}
              </button>
            </div>
          )}

          {playbookText && (
            <div className="rounded-2xl border border-white/[0.07] bg-[#111318] px-6 py-7">
              {playbookStreaming && !playbookDone && (
                <div className="mb-4 flex items-center gap-2 text-xs text-white/40">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400" />
                  Generating…
                </div>
              )}
              <div className="playbook-markdown leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {playbookContent + (playbookStreaming && !playbookDone ? '\n\n▍' : '')}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {playbookText && playbookStreaming && !playbookDone && (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                onClick={() => setShowCancelModal(true)}
                className="cursor-pointer rounded-lg border border-white/15 bg-white/[0.05] px-6 py-2.5 text-sm text-white/50 transition hover:bg-white/[0.10] hover:text-white/80"
              >
                Cancel
              </button>
            </div>
          )}

          {playbookDone && (
            <div className="mt-5 flex flex-row gap-4">
              <button
                type="button"
                onClick={onGoHome}
                className="w-full cursor-pointer rounded-[10px] border border-white/15 bg-transparent py-2.5 px-8 text-[14px] font-semibold text-white/50 transition hover:text-white/80"
              >
                Start New Journey
              </button>
            </div>
          )}
        </div>
      )}
      </div>{/* end scrollable content */}
    </div>
  );
}
