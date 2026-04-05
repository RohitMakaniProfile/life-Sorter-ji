import { useId } from 'react';

const SVG_W = 70;

function colH(len, nodeH, gap) {
  return len * nodeH + Math.max(0, len - 1) * gap;
}

function yCenterOf(idx, len, nodeH, gap, svgH) {
  const total = colH(len, nodeH, gap);
  const offset = (svgH - total) / 2;
  return offset + idx * (nodeH + gap) + nodeH / 2;
}

/**
 * S-curve arrow connecting a single source node to a single target node.
 * Mirrors BranchArrows geometry but for a 1→1 connection.
 *
 * Props:
 *   srcIdx  – 0-based index of the source node in its column
 *   srcLen  – total nodes in source column
 *   tgtIdx  – 0-based index of the target node in its column
 *   tgtLen  – total nodes in target column
 *   nodeH   – estimated node height in px (default 46)
 *   gap     – gap between nodes in px (default 8)
 */
export default function SingleConnector({ srcIdx, srcLen, tgtIdx, tgtLen, nodeH = 46, gap = 8 }) {
  const id = useId().replace(/:/g, '');
  const markerId = `sc-head-${id}`;

  const srcColH = colH(srcLen, nodeH, gap);
  const tgtColH = colH(tgtLen, nodeH, gap);
  const h = Math.max(srcColH, tgtColH, nodeH);

  const srcY = yCenterOf(srcIdx, srcLen, nodeH, gap, h);
  const tgtY = yCenterOf(tgtIdx, tgtLen, nodeH, gap, h);

  const midX = SVG_W / 2;
  const endX = SVG_W - 8;
  const d = `M 0,${srcY} C ${midX},${srcY} ${midX},${tgtY} ${endX},${tgtY}`;

  return (
    <svg
      className="block shrink-0"
      width={SVG_W}
      height={h}
      viewBox={`0 0 ${SVG_W} ${h}`}
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
          <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="white" strokeWidth="1" />
        </marker>
      </defs>
      <path
        d={d}
        fill="none"
        stroke="rgba(255,255,255,0.12)"
        strokeWidth="5"
      />
      <path
        d={d}
        fill="none"
        stroke="white"
        strokeWidth="1.8"
        markerEnd={`url(#${markerId})`}
      />
    </svg>
  );
}
