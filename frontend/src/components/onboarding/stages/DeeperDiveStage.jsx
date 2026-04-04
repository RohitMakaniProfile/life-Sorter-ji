import { clsx } from 'clsx';
import Arrow from '../components/Arrow';

const SCALE_PER_PAGE = 2;

export default function DeeperDiveStage({
  scaleQuestions,
  scaleAnswers,
  onSelect,
  scalePage,
  onPageChange,
  onSubmit,
  onBack,
  loading,
}) {
  const scalePages = Math.ceil(scaleQuestions.length / SCALE_PER_PAGE);
  const currentQs = scaleQuestions.slice(scalePage * SCALE_PER_PAGE, (scalePage + 1) * SCALE_PER_PAGE);
  const isLastPage = scalePage === scalePages - 1;

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-hidden pt-6 pb-5">
      <h1 className="m-0 mb-6 shrink-0 text-center text-[32px] font-extrabold tracking-tight text-white px-8">
        Business Context
      </h1>

      <div className="flex min-h-0 flex-1 w-full items-center">
        {/* Arrow - extends from left edge to touch question box */}
        <Arrow
          className="h-[60px] shrink-0"
          style={{ width: 'calc(50% - 360px)', minWidth: '120px' }}
        />

        {/* Question box - centered with max width */}
        <div className="flex min-h-0 max-h-full flex-1 max-w-[720px]">
          {scaleQuestions.length > 0 ? (
            <div className="flex min-h-0 max-h-full w-full flex-col rounded-[14px] border border-white/12 bg-[#1a1a1a]/80 px-6 py-5">
              <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto [scrollbar-color:rgba(255,255,255,0.08)_transparent] [scrollbar-width:thin]">
                {currentQs.map((q, qi) => {
                  const qIdx = scalePage * SCALE_PER_PAGE + qi;
                  return (
                    <div key={qIdx} className="flex flex-col">
                      <p className="m-0 mb-4 text-[15px] font-semibold leading-snug text-white/90">{q.question}</p>
                      <div className="flex flex-wrap gap-2">
                        {q.options.map((opt, oi) => {
                          const selected = q.multi_select
                            ? (scaleAnswers[qIdx] || []).includes(opt)
                            : scaleAnswers[qIdx] === opt;
                          return (
                            <button
                              key={oi}
                              type="button"
                              className={clsx(
                                'cursor-pointer rounded-lg border px-4 py-2.5 text-left text-[13px] leading-snug transition-all',
                                selected
                                  ? 'border-[rgba(168,130,255,0.5)] bg-[rgba(168,130,255,0.2)] text-white'
                                  : 'border-white/15 bg-white/[0.06] text-white/80 hover:border-white/25 hover:bg-white/[0.1]',
                              )}
                              onClick={() => onSelect(qIdx, opt, q.multi_select)}
                            >
                              {opt}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Pagination inside the card */}
              <div className="flex shrink-0 items-center justify-end gap-3 pt-5 mt-4 border-t border-white/10">
                <span className="text-sm text-white/50">
                  {scalePage + 1}/{scalePages || 1}
                </span>
                <button
                  type="button"
                  className={clsx(
                    'flex h-9 w-9 items-center justify-center rounded-full border transition-colors',
                    scalePage > 0
                      ? 'border-white/20 bg-white/[0.06] text-white/70 hover:bg-white/[0.1] cursor-pointer'
                      : 'border-white/10 bg-white/[0.03] text-white/25 cursor-not-allowed',
                  )}
                  onClick={() => scalePage > 0 && onPageChange((p) => p - 1)}
                  disabled={scalePage === 0}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
                {!isLastPage ? (
                  <button
                    type="button"
                    className="flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-transparent bg-gradient-to-br from-[#a882ff] to-[#7c4dff] px-5 text-[13px] font-semibold text-white transition-[filter] hover:brightness-110"
                    onClick={() => onPageChange((p) => p + 1)}
                  >
                    NEXT
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </button>
                ) : (
                  <button
                    type="button"
                    className="flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-transparent bg-gradient-to-br from-[#a882ff] to-[#7c4dff] px-5 text-[13px] font-semibold text-white transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={onSubmit}
                    disabled={loading}
                  >
                    {loading ? 'Processing…' : 'Continue'}
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="flex min-h-0 w-full flex-col rounded-[14px] border border-white/12 bg-[#1a1a1a]/80 px-6 py-5">
              <p className="m-0 text-sm font-semibold text-white/85">Loading questions…</p>
            </div>
          )}
        </div>

        {/* Right spacer to balance the layout */}
        <div className="shrink-0" style={{ width: 'calc(50% - 360px)', minWidth: '120px' }} />
      </div>

      {/* Back to Tools button - centered at bottom */}
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="mt-6 flex cursor-pointer items-center gap-2 bg-transparent border-none text-white text-sm font-medium transition-colors hover:text-white/90"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
          Back to Tools
        </button>
      )}
    </div>
  );
}
