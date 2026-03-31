import './DiagnosticStage.css';

export default function DiagnosticStage({
  currentQuestion, questionIndex, scaleAnswers, onAnswer, loading,
}) {
  return (
    <>
      {/* Header */}
      <div className="ik-diag__header">
        <h1 className="ik-diag__title">Diagnostic Signals</h1>
        <p className="ik-diag__subtitle">Which of these symptoms are you currently experiencing</p>
      </div>

      {/* Question area */}
      <div className="ik-diag">
        <div className="ik-diag__card">
          <p className="ik-diag__question">{currentQuestion.question}</p>
          <div className="ik-diag__options">
            {currentQuestion.options.map((opt, i) => (
              <button key={i}
                className={`ik-diag__option ${scaleAnswers[questionIndex] === opt ? 'ik-diag__option--selected' : ''}`}
                onClick={() => onAnswer(opt)}>
                <span className="ik-diag__option-num">{String.fromCharCode(65 + i)}</span>
                {opt}
              </button>
            ))}
          </div>
        </div>

        {loading && <div className="ik-diag__loading">Thinking…</div>}
      </div>

      {/* Chat bar at bottom */}
      <div className="ik-diag-chat">
        <input className="ik-diag-chat__input" type="text" placeholder="Type your own answer or message Clawbot..."
          onKeyDown={(e) => {
            if (e.key === 'Enter' && e.target.value.trim()) {
              onAnswer(e.target.value.trim());
              e.target.value = '';
            }
          }} />
        <button className="ik-diag-chat__btn"
          onClick={(e) => {
            const input = e.currentTarget.previousElementSibling;
            if (input.value.trim()) {
              onAnswer(input.value.trim());
              input.value = '';
            }
          }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </>
  );
}
