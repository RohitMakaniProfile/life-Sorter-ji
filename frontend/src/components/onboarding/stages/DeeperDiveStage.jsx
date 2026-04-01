import { useId } from 'react';
import { clsx } from 'clsx';

const SCALE_PER_PAGE = 2;

export default function DeeperDiveStage({
  scaleQuestions,
  scaleAnswers,
  onSelect,
  scalePage,
  onPageChange,
  onSubmit,
  loading,
}) {
  const markerId = `ob-dd-${useId().replace(/:/g, '')}`;
  const scalePages = Math.ceil(scaleQuestions.length / SCALE_PER_PAGE);
  const currentQs = scaleQuestions.slice(scalePage * SCALE_PER_PAGE, (scalePage + 1) * SCALE_PER_PAGE);
  const isLastPage = scalePage === scalePages - 1;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-8 pt-6 pb-5">
      <h1 className="m-0 mb-1 shrink-0 text-center text-[32px] font-extrabold tracking-tight text-white">
        Business Context
      </h1>
      <p className="m-0 mb-5 shrink-0 text-center text-[13px] text-white/40">
        Help us understand your situation to give better recommendations
      </p>

      <div className="flex min-h-0 flex-1 items-center gap-0">
        <svg className="h-5 w-[120px] shrink-0" viewBox="0 0 200 20">
          <defs>
            <marker id={markerId} markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto">
              <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.6)" strokeWidth="1" />
            </marker>
          </defs>
          <line
            x1="0"
            y1="10"
            x2="190"
            y2="10"
            stroke="rgba(255,255,255,0.3)"
            strokeWidth="1.5"
            strokeDasharray="6,4"
            markerEnd={`url(#${markerId})`}
          />
        </svg>

        {scaleQuestions.length > 0 ? (
          <div className="flex min-h-0 max-h-full flex-1 gap-4">
            {currentQs.map((q, qi) => {
              const qIdx = scalePage * SCALE_PER_PAGE + qi;
              return (
                <div
                  key={qIdx}
                  className="flex min-h-0 flex-1 flex-col overflow-y-auto rounded-[14px] border border-white/12 bg-white/[0.03] px-5 py-[18px]"
                >
                  <p className="m-0 mb-3 shrink-0 text-sm font-semibold leading-snug text-white/85">{q.question}</p>
                  <div className="flex min-h-0 flex-1 flex-col gap-1.5">
                    {q.options.map((opt, oi) => {
                      const selected = q.multi_select
                        ? (scaleAnswers[qIdx] || []).includes(opt)
                        : scaleAnswers[qIdx] === opt;
                      return (
                        <button
                          key={oi}
                          type="button"
                          className={clsx(
                            'shrink-0 cursor-pointer rounded-lg border px-3.5 py-2 text-left text-xs leading-snug transition-all',
                            selected
                              ? 'border-[rgba(168,130,255,0.4)] bg-[rgba(168,130,255,0.15)] text-white'
                              : 'border-white/10 bg-white/[0.04] text-white/75 hover:border-white/20 hover:bg-white/[0.08]',
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
        ) : (
          <div className="flex min-h-0 flex-1 gap-4">
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto rounded-[14px] border border-white/12 bg-white/[0.03] px-5 py-[18px]">
              <p className="m-0 text-sm font-semibold text-white/85">Loading questions…</p>
            </div>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-3 pt-3.5">
        {scalePage > 0 && (
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-white/12 bg-white/[0.04] px-5 py-2.5 text-[13px] font-semibold text-white/60 transition-colors hover:bg-white/[0.08]"
            onClick={() => onPageChange((p) => p - 1)}
          >
            &lsaquo; Previous
          </button>
        )}
        <div className="flex-1" />
        <span className="text-xs text-white/35">
          {scalePage + 1} / {scalePages || 1}
        </span>
        <div className="flex-1" />
        {!isLastPage ? (
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-transparent bg-gradient-to-br from-[#a882ff] to-[#7c4dff] px-5 py-2.5 text-[13px] font-semibold text-white transition-[filter] hover:brightness-110"
            onClick={() => onPageChange((p) => p + 1)}
          >
            Next &rsaquo;
          </button>
        ) : (
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-transparent bg-gradient-to-br from-[#a882ff] to-[#7c4dff] px-5 py-2.5 text-[13px] font-semibold text-white transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={onSubmit}
            disabled={loading}
          >
            {loading ? 'Processing…' : 'Continue'}
          </button>
        )}
      </div>
    </div>
  );
}
