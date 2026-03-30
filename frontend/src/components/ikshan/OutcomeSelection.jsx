import { useState } from 'react';
import { outcomeOptions, OUTCOME_DOMAINS } from './constants';
import './OutcomeSelection.css';

/**
 * Q1 Landing — "Deploy 100+ AI Agents to Grow Your Business"
 * Shows 4 outcome cards. Hover reveals Q2 domain preview tooltip.
 *
 * Props:
 *   onSelect(outcome)  – called with the full outcome object when clicked
 */
export default function OutcomeSelection({ onSelect }) {
  const [hoveredId, setHoveredId] = useState(null);

  return (
    <div className="ik-outcome">
      <div className="ik-outcome__hero">
        <h1 className="ik-outcome__title">
          Deploy 100+ <span className="ik-outcome__accent">AI Agents</span> to Grow Your Business
        </h1>
        <p className="ik-outcome__subtitle">Select what Matters most to you right now</p>
      </div>

      <div className="ik-outcome__cards">
        {outcomeOptions.map((opt) => (
          <div
            key={opt.id}
            className={`ik-outcome__card ${hoveredId === opt.id ? 'ik-outcome__card--hovered' : ''}`}
            onClick={() => onSelect(opt)}
            onMouseEnter={() => setHoveredId(opt.id)}
            onMouseLeave={() => setHoveredId(null)}
          >
            <span className="ik-outcome__card-label">{opt.text}</span>
            <span className="ik-outcome__card-sub">{opt.subtext}</span>

            {/* Q2 preview tooltip on hover */}
            {hoveredId === opt.id && OUTCOME_DOMAINS[opt.id] && (
              <div className="ik-outcome__tooltip">
                {OUTCOME_DOMAINS[opt.id].map((d) => (
                  <div key={d} className="ik-outcome__tooltip-item">{d}</div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="ik-outcome__quote">
        "I don't have time or team to figure out AI" - Netizen
      </p>
    </div>
  );
}
