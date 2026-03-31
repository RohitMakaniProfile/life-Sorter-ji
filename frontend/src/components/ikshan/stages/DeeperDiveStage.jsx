import './DeeperDiveStage.css';

const SCALE_PER_PAGE = 2;

export default function DeeperDiveStage({
  scaleQuestions, scaleAnswers, onSelect, scalePage, onPageChange, onSubmit, loading,
}) {
  const scalePages = Math.ceil(scaleQuestions.length / SCALE_PER_PAGE);
  const currentQs = scaleQuestions.slice(scalePage * SCALE_PER_PAGE, (scalePage + 1) * SCALE_PER_PAGE);
  const isLastPage = scalePage === scalePages - 1;

  return (
    <div className="ik-dive">
      <h1 className="ik-dive__title">Business Context</h1>
      <p className="ik-dive__subtitle">Help us understand your situation to give better recommendations</p>

      <div className="ik-dive__body">
        {/* Dashed arrow */}
        <svg className="ik-dive__arrow" viewBox="0 0 200 20">
          <defs>
            <marker id="ik-dd-head" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto">
              <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.6)" strokeWidth="1" />
            </marker>
          </defs>
          <line x1="0" y1="10" x2="190" y2="10"
            stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" strokeDasharray="6,4"
            markerEnd="url(#ik-dd-head)" />
        </svg>

        {/* Question cards side by side */}
        {scaleQuestions.length > 0 ? (
          <div className="ik-dive__cards">
            {currentQs.map((q, qi) => {
              const qIdx = scalePage * SCALE_PER_PAGE + qi;
              return (
                <div key={qIdx} className="ik-dive__card">
                  <p className="ik-dive__question">{q.question}</p>
                  <div className="ik-dive__options">
                    {q.options.map((opt, oi) => (
                      <button key={oi}
                        className={`ik-dive__option ${
                          (q.multi_select
                            ? (scaleAnswers[qIdx] || []).includes(opt)
                            : scaleAnswers[qIdx] === opt)
                            ? 'ik-dive__option--sel' : ''
                        }`}
                        onClick={() => onSelect(qIdx, opt, q.multi_select)}>
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="ik-dive__cards">
            <div className="ik-dive__card">
              <p className="ik-dive__question">Loading questions…</p>
            </div>
          </div>
        )}
      </div>

      {/* Nav row */}
      <div className="ik-dive__nav">
        {scalePage > 0 && (
          <button className="ik-dive__nav-btn" onClick={() => onPageChange((p) => p - 1)}>
            &lsaquo; Previous
          </button>
        )}
        <div style={{ flex: 1 }} />
        <span className="ik-dive__page">{scalePage + 1} / {scalePages || 1}</span>
        <div style={{ flex: 1 }} />
        {!isLastPage ? (
          <button className="ik-dive__nav-btn ik-dive__nav-btn--primary"
            onClick={() => onPageChange((p) => p + 1)}>
            Next &rsaquo;
          </button>
        ) : (
          <button className="ik-dive__nav-btn ik-dive__nav-btn--primary"
            onClick={onSubmit} disabled={loading}>
            {loading ? 'Processing…' : 'Continue'}
          </button>
        )}
      </div>
    </div>
  );
}
