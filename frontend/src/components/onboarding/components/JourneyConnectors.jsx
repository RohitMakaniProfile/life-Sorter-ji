import { useId, useState, useLayoutEffect, useCallback, useRef } from 'react';

const R = 10;
const END_INSET = 4;
const LAYOUT_RETRY_MAX = 120;

/** Path from source right (x0, y0) to target left (x1, y1) in the same coordinate space. */
export function buildMeasuredConnectorPath(x0, y0, x1, y1) {
  const dy = y1 - y0;
  const absDy = Math.abs(dy);
  const span = x1 - x0;
  const spineX = x0 + Math.min(35, Math.max(12, span * 0.42));
  const endX = x1 - END_INSET;

  if (absDy < 2) {
    return `M ${x0},${y0} L ${endX},${y1}`;
  }

  const r = Math.min(R, absDy / 2);
  if (dy > 0) {
    return [
      `M ${x0},${y0}`,
      `L ${spineX - r},${y0}`,
      `A ${r},${r} 0 0,1 ${spineX},${y0 + r}`,
      `L ${spineX},${y1 - r}`,
      `A ${r},${r} 0 0,0 ${spineX + r},${y1}`,
      `L ${endX},${y1}`,
    ].join(' ');
  }
  return [
    `M ${x0},${y0}`,
    `L ${spineX - r},${y0}`,
    `A ${r},${r} 0 0,0 ${spineX},${y0 - r}`,
    `L ${spineX},${y1 + r}`,
    `A ${r},${r} 0 0,1 ${spineX + r},${y1}`,
    `L ${endX},${y1}`,
  ].join(' ');
}

function queryAnchor(root, type, key) {
  if (!root || key == null || key === '') return null;
  try {
    return root.querySelector(
      `[data-journey-anchor="${type}"][data-journey-key="${CSS.escape(String(key))}"]`,
    );
  } catch {
    return null;
  }
}

function isLaidOut(el) {
  if (!el || !(el instanceof Element)) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return false;
  if (typeof window === 'undefined') return true;
  const st = window.getComputedStyle(el);
  if (st.display === 'none' || st.visibility === 'hidden') return false;
  if (Number.parseFloat(st.opacity) === 0) return false;
  return true;
}

function rectCenterRight(rect, rootRect) {
  return {
    x: rect.right - rootRect.left,
    y: rect.top + rect.height / 2 - rootRect.top,
  };
}

function rectCenterLeft(rect, rootRect) {
  return {
    x: rect.left - rootRect.left,
    y: rect.top + rect.height / 2 - rootRect.top,
  };
}

/**
 * One segment: every target must exist and be laid out, or we return ready:false (no partial paths).
 */
function computeSegmentPaths(root, rootRect, seg) {
  const keys = seg.targetKeys || [];
  if (keys.length === 0) {
    return { paths: [], ready: true };
  }

  const srcEl = queryAnchor(root, seg.sourceType, seg.sourceKey);
  if (!srcEl || !isLaidOut(srcEl)) {
    return { paths: [], ready: false };
  }

  const srcRect = srcEl.getBoundingClientRect();
  const p0 = rectCenterRight(srcRect, rootRect);
  const segmentPaths = [];

  for (let i = 0; i < keys.length; i += 1) {
    const tgtEl = queryAnchor(root, seg.targetType, keys[i]);
    if (!tgtEl || !isLaidOut(tgtEl)) {
      return { paths: [], ready: false };
    }
    const tgtRect = tgtEl.getBoundingClientRect();
    const p1 = rectCenterLeft(tgtRect, rootRect);
    if (p1.x <= p0.x + 2) {
      return { paths: [], ready: false };
    }
    segmentPaths.push({
      key: `${seg.key}-${i}`,
      d: buildMeasuredConnectorPath(p0.x, p0.y, p1.x, p1.y),
      delay: `${i * 40}ms`,
    });
  }

  return { paths: segmentPaths, ready: true };
}

const pathAnimClass =
  '[stroke-dasharray:400] [stroke-dashoffset:400] animate-[ob-draw-arrow_0.5s_ease_forwards]';

/**
 * Draws connector arrows from measured DOM nodes (vertical center, source right → target left).
 * Waits until each segment’s source and every target are mounted and laid out (non-zero size)
 * before drawing that segment — avoids broken paths while `JourneyGrow` opens or nodes reposition.
 */
export default function JourneyConnectors({ rootRef, scrollRef, branchTransitionRef, segments }) {
  const reactId = useId().replace(/:/g, '');
  const markerId = `ob-jc-head-${reactId}`;
  const [layout, setLayout] = useState({ w: 0, h: 0, paths: [] });
  const segmentsRef = useRef(segments);
  segmentsRef.current = segments;

  const remeasure = useCallback(() => {
    const run = (generation) => {
      const root = rootRef?.current;
      const segs = segmentsRef.current;
      if (!root) {
        setLayout({ w: 0, h: 0, paths: [] });
        return;
      }

      const rootRect = root.getBoundingClientRect();
      const w = Math.max(1, rootRect.width);
      const h = Math.max(1, rootRect.height);
      const paths = [];
      let deferred = false;

      for (let s = 0; s < segs.length; s += 1) {
        const seg = segs[s];
        if (!seg?.show) continue;
        const { paths: segPaths, ready } = computeSegmentPaths(root, rootRect, seg);
        if (ready) {
          paths.push(...segPaths);
        } else {
          deferred = true;
        }
      }

      setLayout({ w, h, paths });

      if (deferred && generation < LAYOUT_RETRY_MAX) {
        requestAnimationFrame(() => run(generation + 1));
      }
    };

    run(0);
  }, [rootRef]);

  useLayoutEffect(() => {
    const tick = () => remeasure();
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(tick);
    });

    const root = rootRef?.current;
    const scrollEl = scrollRef?.current;
    const branchEl = branchTransitionRef?.current;

    const ro = new ResizeObserver(() => remeasure());
    if (root) ro.observe(root);
    if (branchEl) ro.observe(branchEl);

    if (scrollEl) scrollEl.addEventListener('scroll', remeasure, { passive: true });
    window.addEventListener('resize', remeasure);

    const onTransitionEnd = (e) => {
      if (e.propertyName !== 'grid-template-columns') return;
      if (branchEl && e.target !== branchEl) return;
      requestAnimationFrame(() => requestAnimationFrame(tick));
    };
    if (branchEl) branchEl.addEventListener('transitionend', onTransitionEnd);

    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      ro.disconnect();
      if (scrollEl) scrollEl.removeEventListener('scroll', remeasure);
      window.removeEventListener('resize', remeasure);
      if (branchEl) branchEl.removeEventListener('transitionend', onTransitionEnd);
    };
  }, [remeasure, rootRef, scrollRef, branchTransitionRef, segments]);

  if (layout.paths.length === 0 || layout.w < 1 || layout.h < 1) return null;

  return (
    <svg
      className="pointer-events-none absolute inset-0 z-[6] h-full w-full overflow-visible"
      viewBox={`0 0 ${layout.w} ${layout.h}`}
      preserveAspectRatio="none"
      aria-hidden
    >
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
      {layout.paths.map(({ key, d, delay }) => (
        <g key={key}>
          <path
            d={d}
            fill="none"
            stroke="rgba(255,255,255,0.12)"
            strokeWidth="5"
            className={pathAnimClass}
            style={{ animationDelay: delay }}
          />
          <path
            d={d}
            fill="none"
            stroke="rgba(255,255,255,0.75)"
            strokeWidth="1.5"
            markerEnd={`url(#${markerId})`}
            className={pathAnimClass}
            style={{ animationDelay: delay }}
          />
        </g>
      ))}
    </svg>
  );
}
