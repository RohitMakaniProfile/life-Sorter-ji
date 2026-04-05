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
  onBack,
}) {
  const markerLeftId = `ob-dd-L-${useId().replace(/:/g, '')}`;
  const markerRightId = `ob-dd-R-${useId().replace(/:/g, '')}`;
  const flowColor = '#c4c4d4';
  const scalePages = Math.ceil((scaleQuestions.length || 1) / SCALE_PER_PAGE);
  const currentQs = scaleQuestions.slice(scalePage * SCALE_PER_PAGE, (scalePage + 1) * SCALE_PER_PAGE);
  const isLastPage = scalePage === scalePages - 1;

  /** Left gutter: path L→R into panel. Right gutter: same L→R shape, xMaxYMid aligns end to screen right so arrow points right. */
  const pathLeft = 'M 0,24 L 95,24 C 118,24 118,8 141,8 L 302,8';

  /* Gutter clip + z-index: path/marker must not paint over the center column (overflow was visible before). */
  const gutterClass = 'relative isolate z-0 min-h-px min-w-0 flex-1 basis-0 overflow-hidden';
  /* Full gutter width; vertical offset stays below title+subtitle on short/tall viewports */
  const arrowSvgClass =
    'pointer-events-none absolute inset-x-0 max-w-full overflow-hidden select-none h-[clamp(20px,3vw,30px)] top-[clamp(9rem,min(26vh,11.5rem),14rem)]';

  return (
    <div className="isolate flex min-h-0 flex-1 flex-row overflow-x-hidden overflow-y-hidden py-7 pb-4">
      {/* Left gutter: curve begins at left edge, points inward — clipped to column */}
      <div className={gutterClass} aria-hidden>
        <svg
          className={arrowSvgClass}
          viewBox="0 0 311 32"
          preserveAspectRatio="xMinYMid meet"
          aria-hidden
        >
          <defs>
            <marker
              id={markerLeftId}
              markerWidth="9"
              markerHeight="9"
              refX="8.2"
              refY="4.5"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path d="M0,0.8 L8.2,4.5 L0,8.2 Z" fill={flowColor} stroke="none" />
            </marker>
          </defs>
          <path
            d={pathLeft}
            fill="none"
            stroke={flowColor}
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="8,5"
            markerEnd={`url(#${markerLeftId})`}
            opacity="0.92"
          />
        </svg>
      </div>

      {/* Main panel — above side decorations so chips never sit under stray strokes */}
      <div className="relative z-10 flex min-h-0 min-w-0 max-w-[780px] flex-none flex-col overflow-hidden rounded-[16px] px-3 sm:px-5">
        <h1 className="m-0 mb-1 shrink-0 text-center text-[32px] font-extrabold tracking-tight text-white">
          Deeper Dive
        </h1>
        <p className="m-0 mb-5 shrink-0 text-center text-[13px] text-white/40">
          Help us understand your situation to give better recommendations
        </p>

        {/* Questions */}
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          {scaleQuestions.length > 0 ? (
            currentQs.map((q, qi) => {
              const qIdx = scalePage * SCALE_PER_PAGE + qi;
              return (
                <div
                  key={qIdx}
                  className="flex flex-col rounded-[14px] border border-white/12 bg-white/[0.03] px-5 py-[18px]"
                >
                  <p className="m-0 mb-3 shrink-0 text-sm font-semibold leading-snug text-white/85">
                    {q.question}
                  </p>
                  {/* Horizontal wrap chips */}
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
                            'cursor-pointer rounded-lg border px-3.5 py-2 text-xs leading-snug transition-all',
                            selected
                              ? 'border-[rgba(168,130,255,0.4)] bg-[rgba(168,130,255,0.15)] text-white'
                              : 'border-white/20 bg-transparent text-white/75 hover:border-white/40 hover:bg-white/[0.06]',
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
            })
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-white/40">Loading questions…</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex shrink-0 items-center gap-3 pt-3.5">
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-white/12 bg-white/[0.04] px-5 py-2.5 text-[13px] font-semibold text-white/60 transition-colors hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-30"
            onClick={() => onPageChange((p) => p - 1)}
            disabled={scalePage === 0}
          >
            &lsaquo; Back
          </button>
          <div className="flex-1 text-center text-xs text-white/35">
            {scalePage + 1} / {scalePages || 1}
          </div>
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

        <button
          type="button"
          className="mt-3 shrink-0 cursor-pointer border-none bg-transparent px-4 py-1.5 text-[13px] font-semibold text-white/50 transition-colors hover:text-white"
          onClick={onBack}
        >
          ← Back to Tools
        </button>
      </div>

      {/* Right gutter: clipped; xMaxYMid so head points → toward screen edge */}
      <div className={gutterClass} aria-hidden>
        <svg
          className={arrowSvgClass}
          viewBox="0 0 311 32"
          preserveAspectRatio="xMaxYMid meet"
          aria-hidden
        >
          <defs>
            <marker
              id={markerRightId}
              markerWidth="9"
              markerHeight="9"
              refX="8.2"
              refY="4.5"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path d="M0,0.8 L8.2,4.5 L0,8.2 Z" fill={flowColor} stroke="none" />
            </marker>
          </defs>
          <path
            d={pathLeft}
            fill="none"
            stroke={flowColor}
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="8,5"
            markerEnd={`url(#${markerRightId})`}
            opacity="0.92"
          />
        </svg>
      </div>
    </div>
  );
}
