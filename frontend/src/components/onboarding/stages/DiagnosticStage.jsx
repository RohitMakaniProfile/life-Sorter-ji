import { clsx } from 'clsx';

export default function DiagnosticStage({ currentQuestion, questionIndex, scaleAnswers, onAnswer, loading }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 px-6 pt-5 text-center">
        <h1 className="m-0 mb-1 text-[clamp(22px,2.8vw,32px)] font-extrabold tracking-tight text-white">
          Diagnostic Signals
        </h1>
        <p className="m-0 text-[13px] leading-snug text-white/40">
          Which of these symptoms are you currently experiencing
        </p>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden px-6 py-4">
        <div className="flex max-h-full w-full max-w-[680px] flex-col overflow-hidden">
          <p className="m-0 mb-4 shrink-0 text-[15px] font-semibold leading-snug text-white/90">
            {currentQuestion.question}
          </p>
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto [scrollbar-color:rgba(255,255,255,0.08)_transparent] [scrollbar-width:thin]">
            {currentQuestion.options.map((opt, i) => (
              <button
                key={i}
                type="button"
                className={clsx(
                  'flex shrink-0 cursor-pointer items-start gap-2.5 rounded-[10px] border px-3.5 py-2.5 text-left text-[13px] leading-snug transition-all',
                  scaleAnswers[questionIndex] === opt
                    ? 'border-[rgba(168,130,255,0.4)] bg-[rgba(168,130,255,0.12)] text-white'
                    : 'border-white/10 bg-white/[0.03] text-white/75 hover:border-white/20 hover:bg-white/[0.07]',
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
        </div>

        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#111]/70 text-base text-white/60 backdrop-blur-sm">
            Thinking…
          </div>
        )}
      </div>

      <div className="mx-auto mb-4 flex w-full max-w-[680px] shrink-0 items-center overflow-hidden rounded-xl border border-white/12 bg-white/[0.04]">
        <input
          className="min-w-0 flex-1 border-none bg-transparent px-5 py-3.5 text-sm text-white outline-none placeholder:text-white/30"
          type="text"
          placeholder="Type your own answer or message Clawbot..."
          onKeyDown={(e) => {
            if (e.key === 'Enter' && e.target.value.trim()) {
              onAnswer(e.target.value.trim());
              e.target.value = '';
            }
          }}
        />
        <button
          type="button"
          className="m-1 flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full border-none bg-gradient-to-br from-[#a882ff] to-[#7c4dff] text-white transition-[filter,transform] hover:scale-105 hover:brightness-110"
          onClick={(e) => {
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
