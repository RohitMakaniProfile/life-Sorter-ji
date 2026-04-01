import { useState, useEffect, useRef, useId } from 'react';
import FlowNode from '../components/FlowNode';
import { outcomeOptions, OUTCOME_DOMAINS } from '../constants';

const L_BAND_ITEMS = [
  'AI-Powered Growth Diagnosis',
  'Competitive Intel — 10 Insights',
  'Brand Depth — 10 Leverage Moves',
  'Conversion Optimise — Target 2x Lift',
  'Depth Action Plan — AI Powered',
  '100+ Tools Matched to Your Business',
  'Personalized Playbook in Minutes',
];

const DEMO_PATHS = outcomeOptions.map((opt, i) => {
  const domains = OUTCOME_DOMAINS[opt.id] || [];
  const domainIdx = i % Math.max(domains.length, 1);
  const domain = domains[domainIdx];
  return { outcomeIdx: i, domainIdx, domains, domain };
});

const INITIAL_DELAY = 800;
const BEFORE_FIRST = 1000;
const BRANCH_HOLD = 2500;
const BRANCH_TRANSITION = 500;

const pathDrawClass =
  '[stroke-dasharray:400] [stroke-dashoffset:400] animate-[ob-ss-draw-line_0.6s_ease_forwards]';

function SSBranchArrows({ sourceRef, targetRef, sourceIndex, active }) {
  const [paths, setPaths] = useState([]);
  const svgRef = useRef(null);
  const markerId = `ob-ss-bhead-${useId().replace(/:/g, '')}`;

  useEffect(() => {
    if (!active) {
      setPaths([]);
      return;
    }

    const raf = requestAnimationFrame(() => {
      if (!sourceRef.current || !targetRef.current || !svgRef.current) return;

      const svgRect = svgRef.current.getBoundingClientRect();
      const srcNodes = sourceRef.current.querySelectorAll('[data-ob-ss-wrap]');
      const tgtNodes = targetRef.current.querySelectorAll('[data-ob-ss-wrap]');

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
    <svg ref={svgRef} className="block h-full min-h-px w-[70px] shrink-0 md:w-[70px]" style={{ width: '70px' }}>
      <defs>
        <marker
          id={markerId}
          markerWidth="6"
          markerHeight="5"
          refX="5.5"
          refY="2.5"
          orient="auto"
          markerUnits="strokeWidth"
        >
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
            <path
              d={d}
              fill="none"
              stroke="rgba(255,255,255,0.12)"
              strokeWidth="5"
              className={pathDrawClass}
              style={{ animationDelay: `${index * 40}ms` }}
            />
            <path
              d={d}
              fill="none"
              stroke="rgba(255,255,255,0.75)"
              strokeWidth="1.5"
              markerEnd={`url(#${markerId})`}
              className={pathDrawClass}
              style={{ animationDelay: `${index * 40}ms` }}
            />
          </g>
        );
      })}
    </svg>
  );
}

export default function ScreensaverPreview({ active, onDismiss }) {
  const [phase, setPhase] = useState(0);
  const [pathIndex, setPathIndex] = useState(0);
  const timerRef = useRef(null);
  const srcColRef = useRef(null);
  const tgtColRef = useRef(null);
  const hasStarted = useRef(false);
  const phaseRef = useRef(0);
  const pathIndexRef = useRef(0);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);
  useEffect(() => {
    pathIndexRef.current = pathIndex;
  }, [pathIndex]);

  const currentPath = DEMO_PATHS[pathIndex % DEMO_PATHS.length];
  const demoDomains = currentPath.domains;

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

  useEffect(() => {
    if (!active) return;

    let armed = false;
    const armTimer = setTimeout(() => {
      armed = true;
    }, 300);

    const handler = () => {
      if (!armed) return;
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

  const showOutcomes = phase >= 1;
  const outcomeSelected = phase >= 2;
  const branchVisible = phase === 2;

  return (
    <div
      className={`fixed inset-0 z-[9999] flex flex-col items-center overflow-hidden bg-[#111] bg-[radial-gradient(circle,rgba(255,255,255,0.18)_1px,transparent_1px)] bg-[length:14px_14px] transition-[opacity,visibility] duration-500 ${
        active ? 'visible opacity-100' : 'pointer-events-none invisible opacity-0'
      }`}
    >
      <div className="absolute bottom-16 left-1/2 z-10 flex -translate-x-1/2 animate-[ob-ss-hint-float_2.5s_ease-in-out_infinite] items-center gap-2.5 text-sm tracking-wide text-white/45 md:bottom-16 max-md:bottom-6 max-md:text-xs">
        <div className="h-2 w-2 animate-[ob-ss-pulse_1.5s_ease-in-out_infinite] rounded-full bg-[rgba(168,130,255,0.7)]" />
        Move your mouse to start
      </div>

      <div className="shrink-0 px-6 pb-3 pt-7 text-center">
        <h1 className="m-0 text-[clamp(22px,3vw,40px)] leading-tight font-extrabold text-white">
          Deploy 100+{' '}
          <span className="animate-[ob-gradient-flow_4s_ease_infinite] bg-clip-text text-transparent [background-image:linear-gradient(90deg,rgba(133,123,255,0.9),#BF69A2,rgba(133,123,255,0.9),#BF69A2)] bg-[length:300%_100%] drop-shadow-[0_0_12px_rgba(133,123,255,0.5)]">
            AI Agents
          </span>{' '}
          to Grow Your Business
        </h1>
      </div>

      <div className="flex w-full flex-1 items-center justify-center overflow-hidden">
        <div className="flex items-stretch gap-0 px-5 py-6 pb-12 max-md:px-5 max-md:py-4 max-md:pb-10 md:px-10">
          <div
            className="flex shrink-0 animate-[ob-ss-fade-in_0.5s_ease_both] items-center justify-center px-1"
            style={{ opacity: showOutcomes ? 1 : 0, transition: 'opacity 0.4s ease' }}
          >
            <div className="flex flex-col items-stretch gap-2" ref={srcColRef}>
              {outcomeOptions.map((opt, i) => {
                const isSel = outcomeSelected && i === currentPath.outcomeIdx;
                const isDimmed = outcomeSelected && i !== currentPath.outcomeIdx;
                return (
                  <div
                    key={opt.id}
                    data-ob-ss-wrap
                    className={`transition-[opacity,transform] duration-500 ${isDimmed ? 'scale-95 opacity-20' : ''}`}
                  >
                    <FlowNode label={opt.text} subtext={opt.subtext} variant={isSel ? 'light' : 'dark'} active={isSel} />
                  </div>
                );
              })}
            </div>
          </div>

          <div
            className="flex shrink-0 items-center px-0.5 max-md:w-10"
            style={{ opacity: branchVisible ? 1 : 0, transition: 'opacity 0.4s ease' }}
          >
            <SSBranchArrows
              sourceRef={srcColRef}
              targetRef={tgtColRef}
              sourceIndex={currentPath.outcomeIdx}
              active={branchVisible}
            />
          </div>

          <div
            className="flex shrink-0 items-center justify-center px-1"
            style={{ opacity: branchVisible ? 1 : 0, transition: 'opacity 0.4s ease' }}
          >
            <div className="flex flex-col items-stretch gap-2" ref={tgtColRef}>
              {demoDomains.map((d, i) => (
                <div key={d} data-ob-ss-wrap className="transition-[opacity,transform] duration-500">
                  <FlowNode label={d} variant="dark" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="absolute bottom-0 left-0 right-0 z-20 flex h-11 items-stretch bg-gradient-to-t from-black/60 to-transparent">
        <div className="flex shrink-0 items-center gap-2 bg-gradient-to-br from-indigo-500 via-violet-500 to-violet-400 py-0 pr-8 pl-6 text-[11px] font-extrabold tracking-[0.15em] text-white uppercase [clip-path:polygon(0_0,calc(100%-14px)_0,100%_100%,0_100%)]">
          <span className="h-1.5 w-1.5 animate-[ob-ss-lband-dot-pulse_1.5s_ease-in-out_infinite] rounded-full bg-white shadow-[0_0_6px_rgba(255,255,255,0.6)]" />
          ONBOARDING AI
        </div>
        <div className="flex flex-1 items-center overflow-hidden border-t border-indigo-500/25 bg-[rgba(15,15,20,0.85)] backdrop-blur-md">
          <div className="flex animate-[ob-ss-ticker-scroll_25s_linear_infinite] whitespace-nowrap">
            {[...L_BAND_ITEMS, ...L_BAND_ITEMS].map((item, i) => (
              <span key={i} className="px-1.5 text-[13px] font-medium tracking-wide text-white/80">
                {item}
                <span className="mx-3 align-middle text-[8px] text-violet-400/60">&#x2022;</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
