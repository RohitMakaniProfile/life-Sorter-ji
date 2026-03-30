import { useState, useEffect, useRef, useCallback } from 'react';
import FlowNode from './FlowNode';
import { outcomeOptions, OUTCOME_DOMAINS, DOMAIN_TASKS } from './constants';
import './ScreensaverPreview.css';

// Demo path – pre-selected indices for the walkthrough
const DEMO_OUTCOME_IDX = 0; // "Lead Generation"
const DEMO_DOMAIN_IDX = 1;  // "SEO & Organic Visibility"
const DEMO_TASK_IDX = 0;    // first task in that domain

// Timing (ms)
const INITIAL_DELAY = 800;
const SELECT_OUTCOME = 1400;
const SHOW_DOMAINS = 800;
const SELECT_DOMAIN = 1400;
const SHOW_TASKS = 800;
const SELECT_TASK = 1400;
const SHOW_URL = 800;
const LOOP_PAUSE = 2500;

// ─── Node measurement (mirrors IkshanApp logic) ────────────
const NODE_GAP = 8;

const measureNodeH = (labels, hasSubtext) =>
  labels.map((label) => {
    const baseH = 20;
    const labelLines = Math.ceil((label.length || 10) / 22);
    const labelH = labelLines * 16;
    const subtextH = hasSubtext ? 14 : 0;
    return baseH + labelH + subtextH;
  });

const colHeight = (nodeHeights) =>
  nodeHeights.reduce((s, h) => s + h, 0) + Math.max(0, nodeHeights.length - 1) * NODE_GAP;

const nodeYCenters = (nodeHeights, totalH) => {
  const col = colHeight(nodeHeights);
  const offset = (totalH - col) / 2;
  let y = offset;
  return nodeHeights.map((h) => {
    const center = y + h / 2;
    y += h + NODE_GAP;
    return center;
  });
};

// ─── Reusable BranchArrows (same math as IkshanApp) ────────
function SSBranchArrows({ sourceIndex, srcLabels, srcHasSubtext, tgtLabels, tgtHasSubtext }) {
  const count = tgtLabels.length;
  if (count <= 0) return null;

  const srcNodeH = measureNodeH(srcLabels, srcHasSubtext);
  const tgtNodeH = measureNodeH(tgtLabels, tgtHasSubtext);
  const srcColH = colHeight(srcNodeH);
  const tgtColH = colHeight(tgtNodeH);
  const h = Math.max(srcColH, tgtColH, 50);
  const w = 100;
  const spineX = 35;
  const R = 10;
  const endX = w - 10;

  const srcCenters = nodeYCenters(srcNodeH, h);
  const tgtCenters = nodeYCenters(tgtNodeH, h);
  const srcY = srcCenters[sourceIndex ?? 0];

  return (
    <svg className="ss-branch-svg" viewBox={`0 0 ${w} ${h}`} style={{ height: `${h}px`, width: '70px' }}>
      <defs>
        <marker id="ss-bhead" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1" />
        </marker>
      </defs>
      {tgtCenters.map((tgtY, i) => {
        const dy = tgtY - srcY;
        const absDy = Math.abs(dy);
        let d;

        if (absDy < 2) {
          d = `M 0,${srcY} L ${endX},${tgtY}`;
        } else {
          const r = Math.min(R, absDy / 2);
          if (dy > 0) {
            d = [
              `M 0,${srcY}`,
              `L ${spineX - r},${srcY}`,
              `A ${r},${r} 0 0,1 ${spineX},${srcY + r}`,
              `L ${spineX},${tgtY - r}`,
              `A ${r},${r} 0 0,0 ${spineX + r},${tgtY}`,
              `L ${endX},${tgtY}`,
            ].join(' ');
          } else {
            d = [
              `M 0,${srcY}`,
              `L ${spineX - r},${srcY}`,
              `A ${r},${r} 0 0,0 ${spineX},${srcY - r}`,
              `L ${spineX},${tgtY + r}`,
              `A ${r},${r} 0 0,1 ${spineX + r},${tgtY}`,
              `L ${endX},${tgtY}`,
            ].join(' ');
          }
        }

        return (
          <g key={i}>
            <path d={d} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="5"
              className="ss-branch__path" style={{ animationDelay: `${i * 40}ms` }} />
            <path d={d} fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5"
              markerEnd="url(#ss-bhead)"
              className="ss-branch__path" style={{ animationDelay: `${i * 40}ms` }} />
          </g>
        );
      })}
    </svg>
  );
}

// ─── Single straight arrow ─────────────────────────────────
function SSArrow() {
  return (
    <svg className="ss-single-arrow" viewBox="0 0 80 20" style={{ width: '60px', height: '20px' }}>
      <defs>
        <marker id="ss-ahead" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1" />
        </marker>
      </defs>
      <line x1="4" y1="10" x2="68" y2="10"
        stroke="rgba(255,255,255,0.15)" strokeWidth="6" className="ss-branch__path" />
      <line x1="4" y1="10" x2="68" y2="10"
        stroke="rgba(255,255,255,0.75)" strokeWidth="1.5" markerEnd="url(#ss-ahead)" className="ss-branch__path" />
    </svg>
  );
}

export default function ScreensaverPreview({ onDismiss }) {
  const [phase, setPhase] = useState(0);
  // 0: blank → 1: outcomes visible → 2: outcome selected → 3: domains + arrows
  // 4: domain selected → 5: tasks + arrows → 6: task selected → 7: url form
  const [fading, setFading] = useState(false);
  const dismissed = useRef(false);
  const timerRef = useRef(null);

  const demoOutcome = outcomeOptions[DEMO_OUTCOME_IDX];
  const demoDomains = OUTCOME_DOMAINS[demoOutcome.id] || [];
  const demoDomain = demoDomains[DEMO_DOMAIN_IDX];
  const demoTasks = DOMAIN_TASKS[demoDomain] || [];

  const dismiss = useCallback(() => {
    if (dismissed.current) return;
    dismissed.current = true;
    setFading(true);
    clearTimeout(timerRef.current);
    setTimeout(() => onDismiss(), 500);
  }, [onDismiss]);

  // Schedule phase transitions
  useEffect(() => {
    if (dismissed.current) return;

    const schedule = [
      INITIAL_DELAY,       // 0→1 show outcomes
      SELECT_OUTCOME,      // 1→2 select outcome
      SHOW_DOMAINS,        // 2→3 show domains + arrows
      SELECT_DOMAIN,       // 3→4 select domain
      SHOW_TASKS,          // 4→5 show tasks + arrows
      SELECT_TASK,         // 5→6 select task
      SHOW_URL,            // 6→7 show url form
      LOOP_PAUSE,          // 7→0 loop
    ];

    if (phase < schedule.length) {
      timerRef.current = setTimeout(() => {
        if (!dismissed.current) {
          if (phase === schedule.length - 1) {
            setPhase(0);
          } else {
            setPhase((p) => p + 1);
          }
        }
      }, schedule[phase]);
    }

    return () => clearTimeout(timerRef.current);
  }, [phase]);

  // Listen for user interaction to dismiss
  useEffect(() => {
    let armed = false;
    const armTimer = setTimeout(() => { armed = true; }, 300);

    const handler = () => {
      if (!armed) return;
      dismiss();
    };

    window.addEventListener('mousemove', handler);
    window.addEventListener('mousedown', handler);
    window.addEventListener('keydown', handler);
    window.addEventListener('touchstart', handler);
    window.addEventListener('wheel', handler);

    return () => {
      clearTimeout(armTimer);
      window.removeEventListener('mousemove', handler);
      window.removeEventListener('mousedown', handler);
      window.removeEventListener('keydown', handler);
      window.removeEventListener('touchstart', handler);
      window.removeEventListener('wheel', handler);
    };
  }, [dismiss]);

  // Derived state
  const showOutcomes = phase >= 1;
  const outcomeSelected = phase >= 2;
  const showDomains = phase >= 3;
  const domainSelected = phase >= 4;
  const showTasks = phase >= 5;
  const taskSelected = phase >= 6;
  const showUrl = phase >= 7;

  return (
    <div className={`ss-overlay ${fading ? 'ss-overlay--fading' : ''}`}>
      {/* Hint */}
      <div className="ss-hint">
        <div className="ss-hint__pulse" />
        Move your mouse to start
      </div>

      {/* Title */}
      <div className="ss-title">
        <h1 className="ss-title__text">
          Deploy 100+ <span className="ss-title__accent">AI Agents</span> to Grow Your Business
        </h1>
      </div>

      {/* Animated workflow canvas */}
      <div className="ss-canvas">
        <div className="ss-track">

          {/* ── Column 0: Outcomes ── */}
          {showOutcomes && (
            <div className="ss-col ss-col--pop">
              <div className="ss-col__nodes">
                {outcomeOptions.map((opt, i) => {
                  const isSel = outcomeSelected && i === DEMO_OUTCOME_IDX;
                  const isDimmed = outcomeSelected && i !== DEMO_OUTCOME_IDX;
                  return (
                    <div key={opt.id}
                      className={`ss-node-wrap ${isDimmed ? 'ss-node-wrap--dimmed' : ''}`}
                      style={{ animationDelay: `${i * 80}ms` }}>
                      <FlowNode label={opt.text} subtext={opt.subtext}
                        variant={isSel ? 'light' : 'dark'} active={isSel} />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Arrows: Outcome → Domains ── */}
          {showDomains && (
            <div className="ss-col ss-col--arrows ss-col--pop">
              <SSBranchArrows
                sourceIndex={DEMO_OUTCOME_IDX}
                srcLabels={outcomeOptions.map(o => o.text)}
                srcHasSubtext={true}
                tgtLabels={demoDomains}
                tgtHasSubtext={false}
              />
            </div>
          )}

          {/* ── Column 1: Domains ── */}
          {showDomains && (
            <div className="ss-col ss-col--pop">
              <div className="ss-col__nodes">
                {demoDomains.map((d, i) => {
                  const isSel = domainSelected && i === DEMO_DOMAIN_IDX;
                  const isDimmed = domainSelected && i !== DEMO_DOMAIN_IDX;
                  return (
                    <div key={d}
                      className={`ss-node-wrap ${isDimmed ? 'ss-node-wrap--dimmed' : ''}`}
                      style={{ animationDelay: `${i * 80}ms` }}>
                      <FlowNode label={d} variant={isSel ? 'light' : 'dark'} active={isSel} />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Arrows: Domain → Tasks ── */}
          {showTasks && (
            <div className="ss-col ss-col--arrows ss-col--pop">
              <SSBranchArrows
                sourceIndex={DEMO_DOMAIN_IDX}
                srcLabels={demoDomains}
                srcHasSubtext={false}
                tgtLabels={demoTasks}
                tgtHasSubtext={false}
              />
            </div>
          )}

          {/* ── Column 2: Tasks ── */}
          {showTasks && (
            <div className="ss-col ss-col--pop">
              <div className="ss-col__nodes">
                {demoTasks.map((t, i) => {
                  const isSel = taskSelected && i === DEMO_TASK_IDX;
                  const isDimmed = taskSelected && i !== DEMO_TASK_IDX;
                  return (
                    <div key={t}
                      className={`ss-node-wrap ${isDimmed ? 'ss-node-wrap--dimmed' : ''}`}
                      style={{ animationDelay: `${i * 60}ms` }}>
                      <FlowNode label={t} variant={isSel ? 'light' : 'dark'} active={isSel} />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Arrow: Task → URL ── */}
          {showUrl && (
            <div className="ss-col ss-col--arrows ss-col--pop">
              <SSArrow />
            </div>
          )}

          {/* ── URL form mock ── */}
          {showUrl && (
            <div className="ss-col ss-col--pop">
              <div className="ss-url-mock">
                <div className="ss-url-mock__label">Enter your business website</div>
                <div className="ss-url-mock__input">
                  <span className="ss-url-mock__typing">yourcompany.com</span>
                  <span className="ss-url-mock__cursor" />
                </div>
                <div className="ss-url-mock__btn">Analyze My Business</div>
              </div>
            </div>
          )}

          {/* End spacer */}
          <div className="ss-col ss-col--spacer" />
        </div>
      </div>
    </div>
  );
}
