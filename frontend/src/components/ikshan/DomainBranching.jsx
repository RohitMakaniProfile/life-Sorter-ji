import { useState, useEffect, useRef } from 'react';
import { OUTCOME_DOMAINS, DOMAIN_TASKS } from './constants';
import FlowNode from './FlowNode';
import './DomainBranching.css';

/**
 * Q2 → Q3 Tree/Mind-map View
 * Shows: SelectedOutcome (left node) → branching connectors → Domain nodes (Q2)
 * On domain click: domains collapse, selected domain connects → Task nodes (Q3)
 *
 * Props:
 *   outcome        – { id, text, subtext }
 *   onDomainSelect – (domainName) => void
 *   onTaskSelect   – (taskName) => void
 *   onBack         – go back to Q1
 */
export default function DomainBranching({ outcome, onDomainSelect, onTaskSelect, onBack }) {
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [animPhase, setAnimPhase] = useState('entering'); // 'entering' | 'branches' | 'domains' | 'task-select' | 'tasks'
  const containerRef = useRef(null);

  const domains = OUTCOME_DOMAINS[outcome.id] || [];
  const tasks = selectedDomain ? (DOMAIN_TASKS[selectedDomain] || []) : [];

  // Animation sequence on mount: entering → branches → domains
  useEffect(() => {
    const t1 = setTimeout(() => setAnimPhase('branches'), 300);
    const t2 = setTimeout(() => setAnimPhase('domains'), 700);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  const handleDomainClick = (domain) => {
    setSelectedDomain(domain);
    setAnimPhase('task-select');
    onDomainSelect(domain);
    // Animate tasks in
    setTimeout(() => setAnimPhase('tasks'), 400);
  };

  const handleTaskClick = (task) => {
    onTaskSelect(task);
  };

  const handleBack = () => {
    if (selectedDomain) {
      setSelectedDomain(null);
      setAnimPhase('domains');
    } else {
      onBack();
    }
  };

  return (
    <div className="ik-branch" ref={containerRef}>
      {/* Hero (stays) */}
      <div className="ik-branch__hero">
        <h1 className="ik-branch__title">
          Deploy 100+ <span className="ik-branch__accent">AI Agents</span> to Grow Your Business
        </h1>
        <p className="ik-branch__subtitle">Select what Matters most to you right now</p>
      </div>

      {/* Tree visualization area */}
      <div className="ik-branch__tree">
        {/* Origin node (Q1 selection) */}
        <div className="ik-branch__origin">
          <FlowNode label={outcome.text} subtext={outcome.subtext} variant="light" />
        </div>

        {/* SVG connectors */}
        <svg className="ik-branch__svg" viewBox="0 0 200 400" preserveAspectRatio="xMidYMid meet">
          {!selectedDomain && (animPhase === 'branches' || animPhase === 'domains') && domains.map((_, i) => {
            const startY = 200;
            const endY = 40 + (i * (360 / Math.max(domains.length - 1, 1)));
            return (
              <path
                key={i}
                className="ik-branch__connector"
                d={`M 0,${startY} C 100,${startY} 100,${endY} 200,${endY}`}
                fill="none"
                stroke="rgba(255,255,255,0.4)"
                strokeWidth="2"
              />
            );
          })}
          {selectedDomain && (
            <path
              className="ik-branch__connector"
              d="M 0,200 C 100,200 100,200 200,200"
              fill="none"
              stroke="rgba(255,255,255,0.4)"
              strokeWidth="2"
            />
          )}
        </svg>

        {/* Domain nodes (Q2) — shown when no domain selected */}
        {!selectedDomain && (animPhase === 'domains' || animPhase === 'branches') && (
          <div className="ik-branch__targets">
            {domains.map((d, i) => (
              <div
                key={d}
                className="ik-branch__target-item"
                style={{ animationDelay: `${i * 80}ms` }}
              >
                <FlowNode
                  label={d}
                  variant="dark"
                  onClick={() => handleDomainClick(d)}
                />
              </div>
            ))}
          </div>
        )}

        {/* Selected domain + task branch */}
        {selectedDomain && (
          <div className="ik-branch__domain-selected">
            <FlowNode label={selectedDomain} variant="dark" active />

            {animPhase === 'tasks' && (
              <>
                {/* Second connector set going right */}
                <svg className="ik-branch__svg ik-branch__svg--tasks" viewBox="0 0 200 600" preserveAspectRatio="xMidYMid meet">
                  {tasks.map((_, i) => {
                    const startY = 300;
                    const endY = 20 + (i * (560 / Math.max(tasks.length - 1, 1)));
                    return (
                      <path
                        key={i}
                        className="ik-branch__connector"
                        d={`M 0,${startY} C 100,${startY} 100,${endY} 200,${endY}`}
                        fill="none"
                        stroke="rgba(255,255,255,0.3)"
                        strokeWidth="1.5"
                      />
                    );
                  })}
                </svg>

                <div className="ik-branch__task-list">
                  {tasks.map((t, i) => (
                    <div
                      key={t}
                      className="ik-branch__target-item"
                      style={{ animationDelay: `${i * 60}ms` }}
                    >
                      <FlowNode label={t} variant="dark" onClick={() => handleTaskClick(t)} />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Back button */}
      <button className="ik-branch__back" onClick={handleBack}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M10 13L5 8L10 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        {selectedDomain ? 'Step 1' : 'Back'}
      </button>
    </div>
  );
}
