import { useState, useEffect, useRef } from 'react';
import FlowNode from '../components/FlowNode';
import { outcomeOptions, OUTCOME_DOMAINS, DOMAIN_TASKS } from '../constants';
import './ScreensaverPreview.css';

const L_BAND_ITEMS = [
  'AI-Powered Growth Diagnosis',
  'Competitive Intel — 10 Insights',
  'Brand Depth — 10 Leverage Moves',
  'Conversion Optimise — Target 2x Lift',
  'Depth Action Plan — AI Powered',
  '100+ Tools Matched to Your Business',
  'Personalized Playbook in Minutes',
];

// Pre-built demo paths — one per outcome option, cycling each loop
const DEMO_PATHS = outcomeOptions.map((opt, i) => {
  const domains = OUTCOME_DOMAINS[opt.id] || [];
  const domainIdx = i % Math.max(domains.length, 1);
  const domain = domains[domainIdx];
  const tasks = DOMAIN_TASKS[domain] || [];
  const taskIdx = i % Math.max(tasks.length, 1);
  return { outcomeIdx: i, domainIdx, taskIdx, domains, domain, tasks };
});

// Timing (ms)
const INITIAL_DELAY = 800;
const BEFORE_FIRST = 1000;
const BRANCH_HOLD = 2500;
const BRANCH_TRANSITION = 500;

// ─── BranchArrows — measures actual DOM node positions ──────
function SSBranchArrows({ sourceRef, targetRef, sourceIndex, active }) {
  const [paths, setPaths] = useState([]);
  const svgRef = useRef(null);

  useEffect(() => {
    if (!active) { setPaths([]); return; }

    // Wait a frame for both columns to finish painting
    const raf = requestAnimationFrame(() => {
      if (!sourceRef.current || !targetRef.current || !svgRef.current) return;

      const svgRect = svgRef.current.getBoundingClientRect();
      const srcNodes = sourceRef.current.querySelectorAll('.ss-node-wrap');
      const tgtNodes = targetRef.current.querySelectorAll('.ss-node-wrap');

      if (!srcNodes.length || !tgtNodes.length) return;

      const srcNode = srcNodes[sourceIndex ?? 0];
      if (!srcNode) return;

      const srcRect = srcNode.getBoundingClientRect();
      const srcY = srcRect.top + srcRect.height / 2 - svgRect.top;

      const newPaths = [];
      tgtNodes.forEach((node, i) => {
        const tgtRect = node.getBoundingClientRect();
        const tgtY = tgtRect.top + tgtRect.height / 2 - svgRect.top;
        newPaths.push({ srcY, tgtY, index: i });
      });

      setPaths(newPaths);
    });

    return () => cancelAnimationFrame(raf);
  }, [sourceRef, targetRef, sourceIndex, active]);

  const w = 70;
  const spineX = 25;
  const R = 10;
  const endX = w - 10;

  return (
    <svg ref={svgRef} className="ss-branch-svg" style={{ width: '70px', height: '100%', minHeight: '1px' }}>
      <defs>
        <marker id="ss-bhead" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1" />
        </marker>
      </defs>
      {paths.map(({ srcY, tgtY, index }) => {
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
          <g key={index}>
            <path d={d} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="5"
              className="ss-branch__path" style={{ animationDelay: `${index * 40}ms` }} />
            <path d={d} fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5"
              markerEnd="url(#ss-bhead)"
              className="ss-branch__path" style={{ animationDelay: `${index * 40}ms` }} />
          </g>
        );
      })}
    </svg>
  );
}

export default function ScreensaverPreview({ active, onDismiss }) {
  const [phase, setPhase] = useState(0);
  // 0: blank → 1: outcomes visible → 2: outcome selected + arrows + domains → 3: fading → loop
  const [pathIndex, setPathIndex] = useState(0);
  const timerRef = useRef(null);
  const srcColRef = useRef(null);
  const tgtColRef = useRef(null);
  const hasStarted = useRef(false);
  const phaseRef = useRef(0);
  const pathIndexRef = useRef(0);

  // Keep refs in sync so the dismiss handler always reads current values
  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { pathIndexRef.current = pathIndex; }, [pathIndex]);

  const currentPath = DEMO_PATHS[pathIndex % DEMO_PATHS.length];
  const demoDomains = currentPath.domains;

  // When active turns ON: if first time, start from phase 0; otherwise resume
  // When active turns OFF: just stop timers, keep phase/pathIndex as-is
  useEffect(() => {
    if (active) {
      if (!hasStarted.current) {
        hasStarted.current = true;
        setPhase(0);
      }
    } else {
      clearTimeout(timerRef.current);
    }
  }, [active]);

  // Schedule phase transitions (only runs when active)
  useEffect(() => {
    if (!active) return;

    const timings = {
      0: INITIAL_DELAY,
      1: BEFORE_FIRST,
      2: BRANCH_HOLD,
      3: BRANCH_TRANSITION,
    };

    timerRef.current = setTimeout(() => {
      if (!active) return;

      if (phase === 3) {
        setPathIndex((p) => (p + 1) % DEMO_PATHS.length);
        setPhase(2);
      } else if (phase === 2) {
        setPhase(3);
      } else {
        setPhase((p) => p + 1);
      }
    }, timings[phase]);

    return () => clearTimeout(timerRef.current);
  }, [phase, pathIndex, active]);

  // Listen for user interaction to dismiss
  useEffect(() => {
    if (!active) return;

    let armed = false;
    const armTimer = setTimeout(() => { armed = true; }, 300);

    const handler = () => {
      if (!armed) return;
      // Read current values from refs (not stale closure)
      const idx = DEMO_PATHS[pathIndexRef.current % DEMO_PATHS.length].outcomeIdx;
      onDismiss(phaseRef.current >= 2 ? outcomeOptions[idx] : null);
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
  }, [active, onDismiss]);

  // Derived state
  const showOutcomes = phase >= 1;
  const outcomeSelected = phase >= 2;
  const branchVisible = phase === 2;

  return (
    <div className={`ss-overlay ${active ? '' : 'ss-overlay--hidden'}`}>
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

      {/* Animated workflow canvas — centered */}
      <div className="ss-canvas">
        <div className="ss-track">

          {/* ── Column 0: Outcomes (always in DOM, opacity controlled) ── */}
          <div className="ss-col ss-col--static" style={{ opacity: showOutcomes ? 1 : 0, transition: 'opacity 0.4s ease' }}>
            <div className="ss-col__nodes" ref={srcColRef}>
              {outcomeOptions.map((opt, i) => {
                const isSel = outcomeSelected && i === currentPath.outcomeIdx;
                const isDimmed = outcomeSelected && i !== currentPath.outcomeIdx;
                return (
                  <div key={opt.id}
                    className={`ss-node-wrap ${isDimmed ? 'ss-node-wrap--dimmed' : ''}`}>
                    <FlowNode label={opt.text} subtext={opt.subtext}
                      variant={isSel ? 'light' : 'dark'} active={isSel} />
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Arrows + Domains (fade in/out via CSS transition) ── */}
          <div className="ss-col ss-col--arrows" style={{ opacity: branchVisible ? 1 : 0, transition: 'opacity 0.4s ease' }}>
            <SSBranchArrows
              sourceRef={srcColRef}
              targetRef={tgtColRef}
              sourceIndex={currentPath.outcomeIdx}
              active={branchVisible}
            />
          </div>

          <div className="ss-col" style={{ opacity: branchVisible ? 1 : 0, transition: 'opacity 0.4s ease' }}>
            <div className="ss-col__nodes" ref={tgtColRef}>
              {demoDomains.map((d, i) => (
                <div key={d}
                  className="ss-node-wrap"
                  style={{ animationDelay: `${i * 80}ms` }}>
                  <FlowNode label={d} variant="dark" />
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>

      {/* ── L-Band (news ticker at bottom) ── */}
      <div className="ss-lband">
        <div className="ss-lband__label">
          <span className="ss-lband__label-dot" />
          IKSHAN AI
        </div>
        <div className="ss-lband__ticker">
          <div className="ss-lband__ticker-track">
            {/* Duplicate items for seamless loop */}
            {[...L_BAND_ITEMS, ...L_BAND_ITEMS].map((item, i) => (
              <span key={i} className="ss-lband__ticker-item">
                {item}
                <span className="ss-lband__ticker-sep">&#x2022;</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
