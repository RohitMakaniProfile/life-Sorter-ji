import StageLayout from '../components/StageLayout';

export default function CompleteStage({ error, onClearError, onDeepAnalysis }) {
  return (
    <StageLayout error={error} onClearError={onClearError}>
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 px-4 text-center text-white">
        <div className="text-5xl">&#10003;</div>
        <h1 className="m-0 text-[28px] font-extrabold tracking-tight">Analysis Complete</h1>
        <p className="m-0 max-w-[480px] text-[15px] leading-relaxed text-white/60">
          Your diagnostic journey is complete. Based on your answers, we have enough context to generate your
          personalized playbook and tool recommendations.
        </p>
        <button
          type="button"
          onClick={onDeepAnalysis}
          className="mt-3 cursor-pointer rounded-[10px] border-none bg-gradient-to-br from-indigo-500 to-violet-500 px-8 py-3 text-[15px] font-bold text-white"
        >
          Do Deep Analysis
        </button>
      </div>
    </StageLayout>
  );
}
