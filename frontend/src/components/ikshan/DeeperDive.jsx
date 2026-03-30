import { useState } from 'react';
import './DeeperDive.css';

/**
 * Scale Questions — "Deeper Dive" paginated form (1/N, 2/N ... N/N)
 * Each page shows 2 questions with chip-select options.
 *
 * Props:
 *   questions        – array of { id, question, options, multiSelect, icon }
 *   onSubmit(answers) – called with { questionId: selectedValue(s) }
 *   onBack()          – go back to tools/url stage
 *   loading           – boolean
 */
export default function DeeperDive({ questions = [], onSubmit, onBack, loading = false }) {
  const QUESTIONS_PER_PAGE = 2;
  const totalPages = Math.ceil(questions.length / QUESTIONS_PER_PAGE);

  const [page, setPage] = useState(0);
  const [answers, setAnswers] = useState({});

  const currentQuestions = questions.slice(
    page * QUESTIONS_PER_PAGE,
    (page + 1) * QUESTIONS_PER_PAGE
  );

  const isLastPage = page === totalPages - 1;

  const handleSelect = (qId, option, multiSelect) => {
    setAnswers((prev) => {
      if (multiSelect) {
        const current = prev[qId] || [];
        const exists = current.includes(option);
        return {
          ...prev,
          [qId]: exists ? current.filter((o) => o !== option) : [...current, option],
        };
      }
      return { ...prev, [qId]: option };
    });
  };

  const isSelected = (qId, option, multiSelect) => {
    if (multiSelect) {
      return (answers[qId] || []).includes(option);
    }
    return answers[qId] === option;
  };

  const handleNext = () => {
    if (isLastPage) {
      onSubmit(answers);
    } else {
      setPage((p) => p + 1);
    }
  };

  const handlePrev = () => {
    if (page > 0) setPage((p) => p - 1);
  };

  return (
    <div className="ik-dive">
      <div className="ik-dive__header">
        <h1 className="ik-dive__title">Deeper Dive</h1>
      </div>

      <div className={`ik-dive__card ${loading ? 'ik-dive__card--loading' : ''}`}>
        {currentQuestions.map((q) => (
          <div key={q.id} className="ik-dive__question-block">
            <h3 className="ik-dive__question-text">
              {q.icon && <span className="ik-dive__icon">{q.icon}</span>}
              {q.question}
            </h3>
            <div className="ik-dive__chips">
              {(q.options || []).map((opt) => (
                <button
                  key={opt}
                  className={`ik-dive__chip ${isSelected(q.id, opt, q.multiSelect) ? 'ik-dive__chip--selected' : ''}`}
                  onClick={() => handleSelect(q.id, opt, q.multiSelect)}
                  disabled={loading}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
        ))}

        {/* Pagination footer */}
        <div className="ik-dive__footer">
          <span className="ik-dive__page-info">{page + 1}/{totalPages}</span>
          <div className="ik-dive__nav-btns">
            <button
              className="ik-dive__nav-btn ik-dive__nav-btn--prev"
              onClick={handlePrev}
              disabled={page === 0}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M10 13L5 8L10 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
            <button
              className="ik-dive__nav-btn ik-dive__nav-btn--next"
              onClick={handleNext}
              disabled={loading}
            >
              {isLastPage ? 'Continue' : 'NEXT'}
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M6 3L11 8L6 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Back to Tools */}
      <button className="ik-dive__back" onClick={onBack}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M10 13L5 8L10 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        Back to Tools
      </button>
    </div>
  );
}
