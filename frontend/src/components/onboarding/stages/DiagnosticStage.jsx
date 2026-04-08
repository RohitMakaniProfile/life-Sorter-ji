import { clsx } from 'clsx';

export default function DiagnosticStage({ currentQuestion, questionIndex, scaleAnswers, onAnswer, loading, onBack }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-hidden pt-6 pb-5">
      <h1 className="m-0 mb-6 shrink-0 text-center text-[32px] font-extrabold tracking-tight text-white px-8">
        Diagnostic Signals
      </h1>

      <div className="flex min-h-0 flex-1 w-full items-center justify-center px-6">
        <div className="relative flex min-h-0 max-h-full w-full max-w-[720px] flex-col rounded-[14px] border border-white/12 bg-[#1a1a1a]/80 px-6 py-5">
          <p className="m-0 mb-4 shrink-0 text-[15px] font-semibold leading-snug text-white/90">
            {currentQuestion.question}
          </p>
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto [scrollbar-color:rgba(255,255,255,0.08)_transparent] [scrollbar-width:thin]">
            {currentQuestion.options?.map((opt, i) => (
              <button
                key={i}
                type="button"
                disabled={loading}
                className={clsx(
                  'flex shrink-0 cursor-pointer items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-left text-[13px] leading-snug transition-all',
                  loading && 'cursor-not-allowed opacity-60',
                  scaleAnswers[questionIndex] === opt
                    ? 'border-[rgba(168,130,255,0.5)] bg-[rgba(168,130,255,0.2)] text-white'
                    : 'border-white/15 bg-white/[0.06] text-white/80 hover:border-white/25 hover:bg-white/[0.1]',
                )}
                onClick={() => onAnswer(opt)}
              >
                <span
                  className={clsx(
                    'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md text-[11px] font-bold',
                    scaleAnswers[questionIndex] === opt
                      ? 'bg-[rgba(168,130,255,0.3)] text-[#d4bfff]'
                      : 'bg-white/[0.06] text-white/40',
                  )}
                >
                  {String.fromCharCode(65 + i)}
                </span>
                {opt}
              </button>
            ))}
          </div>

          {/* Type your own - styled as the last option row */}
          <div className="mt-2 flex shrink-0 items-center gap-2.5 rounded-lg border border-white/15 bg-white/[0.06] px-3.5 py-2.5">
            <input
              className="min-w-0 flex-1 border-none bg-transparent text-[13px] leading-snug text-white/80 outline-none placeholder:text-white/50"
              type="text"
              disabled={loading}
              placeholder="Type your own"
              onKeyDown={(e) => {
                if (loading) return;
                if (e.key === 'Enter' && e.target.value.trim()) {
                  onAnswer(e.target.value.trim());
                  e.target.value = '';
                }
              }}
            />
            <button
              type="button"
              disabled={loading}
              className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full border-none bg-white/10 text-white/60 transition-all hover:bg-white/20 hover:text-white"
              onClick={(e) => {
                if (loading) return;
                const input = e.currentTarget.previousElementSibling;
                if (input.value.trim()) {
                  onAnswer(input.value.trim());
                  input.value = '';
                }
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
          </div>

          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[14px] bg-[#111]/70 text-base text-white/60 backdrop-blur-sm">
              Thinking…
            </div>
          )}
        </div>
      </div>

      {/* Back button - centered at bottom */}
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="mt-6 flex cursor-pointer items-center gap-2 bg-transparent border-none text-white/70 text-sm font-medium transition-colors hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
          Back to Business Context
        </button>
      )}

      {/* Message Clawbot input at bottom */}
      <div className="mx-auto mt-4 flex w-full max-w-[720px] shrink-0 items-center overflow-hidden rounded-xl border border-white/12 bg-white/[0.04]">
        <input
          className="min-w-0 flex-1 border-none bg-transparent px-5 py-3.5 text-sm text-white outline-none placeholder:text-white/30"
          type="text"
          disabled={loading}
          placeholder="Message Clawbot"
          onKeyDown={(e) => {
            if (loading) return;
            if (e.key === 'Enter' && e.target.value.trim()) {
              onAnswer(e.target.value.trim());
              e.target.value = '';
            }
          }}
        />
        <button
          type="button"
          disabled={loading}
          className="m-1 flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full border-none bg-gradient-to-br from-[#a882ff] to-[#7c4dff] text-white transition-[filter,transform] hover:scale-105 hover:brightness-110"
          onClick={(e) => {
            if (loading) return;
            const input = e.currentTarget.previousElementSibling;
            if (input.value.trim()) {
              onAnswer(input.value.trim());
              input.value = '';
            }
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
