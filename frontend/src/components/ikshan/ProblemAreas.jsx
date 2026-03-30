import { useState } from 'react';
import './ProblemAreas.css';

/**
 * Diagnostic Questions Screen — "Problem Areas" / "Diagnostic Signals"
 * Shows a question with selectable pill options + "Type your own" input.
 * Also has "Message Clawbot" chat bar at bottom.
 *
 * Props:
 *   sectionLabel      – e.g. "Problem Areas", "Diagnostic Signals"
 *   sectionSubtext    – e.g. "For generate social media posts captions & hooks"
 *   question          – question text
 *   options           – string[] of selectable options
 *   insight           – short insight line (stat/benchmark)
 *   acknowledgment    – brief line acknowledging previous answer
 *   onAnswer(answer)  – called with selected option or typed text
 *   loading           – boolean, shows loading state
 *   onChatMessage(msg)– send a freeform chat message
 */
export default function ProblemAreas({
  sectionLabel,
  sectionSubtext,
  question,
  options = [],
  insight,
  acknowledgment,
  onAnswer,
  loading = false,
  onChatMessage,
}) {
  const [selected, setSelected] = useState(null);
  const [customText, setCustomText] = useState('');
  const [chatText, setChatText] = useState('');

  const handleOptionClick = (opt) => {
    setSelected(opt);
    onAnswer(opt);
  };

  const handleCustomSubmit = () => {
    if (customText.trim()) {
      onAnswer(customText.trim());
      setCustomText('');
    }
  };

  const handleChatSubmit = (e) => {
    e.preventDefault();
    if (chatText.trim() && onChatMessage) {
      onChatMessage(chatText.trim());
      setChatText('');
    }
  };

  return (
    <div className="ik-problems">
      {/* Header */}
      <div className="ik-problems__header">
        <h1 className="ik-problems__title">{sectionLabel || 'Problem Areas'}</h1>
        {sectionSubtext && <p className="ik-problems__subtext">{sectionSubtext}</p>}
      </div>

      {/* Acknowledgment from AI */}
      {acknowledgment && (
        <div className="ik-problems__ack">{acknowledgment}</div>
      )}

      {/* Question card */}
      <div className={`ik-problems__card ${loading ? 'ik-problems__card--loading' : ''}`}>
        {insight && <p className="ik-problems__insight">{insight}</p>}

        <h2 className="ik-problems__question">{question || 'Which of these problems best describe your current challenge?'}</h2>

        {/* Options */}
        <div className="ik-problems__options">
          {options.map((opt, i) => (
            <button
              key={i}
              className={`ik-problems__option ${selected === opt ? 'ik-problems__option--selected' : ''}`}
              onClick={() => handleOptionClick(opt)}
              disabled={loading}
            >
              {opt}
            </button>
          ))}
        </div>

        {/* Type your own */}
        <div className="ik-problems__custom">
          <input
            className="ik-problems__custom-input"
            type="text"
            placeholder="Type your own"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCustomSubmit()}
            disabled={loading}
          />
          <button
            className="ik-problems__custom-send"
            onClick={handleCustomSubmit}
            disabled={!customText.trim() || loading}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Loading indicator */}
      {loading && (
        <div className="ik-problems__loading">
          <div className="ik-problems__spinner" />
          <span>Thinking...</span>
        </div>
      )}

      {/* Chat bar */}
      <form className="ik-problems__chatbar" onSubmit={handleChatSubmit}>
        <input
          className="ik-problems__chat-input"
          type="text"
          placeholder="Message Clawbot"
          value={chatText}
          onChange={(e) => setChatText(e.target.value)}
        />
        <button className="ik-problems__chat-send" type="submit" disabled={!chatText.trim()}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </form>
    </div>
  );
}
