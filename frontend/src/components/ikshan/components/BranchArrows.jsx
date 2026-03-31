const NODE_GAP = 8;

function measureNodeH(labels, hasSubtext) {
  return labels.map((label) => {
    const baseH = 22;
    const labelLines = Math.ceil((label.length || 10) / 27);
    const labelH = labelLines * 16;
    const subtextH = hasSubtext ? 15 : 0;
    return baseH + labelH + subtextH;
  });
}

function colHeight(nodeHeights) {
  return nodeHeights.reduce((sum, h) => sum + h, 0) + Math.max(0, nodeHeights.length - 1) * NODE_GAP;
}

function nodeYCenters(nodeHeights, totalH) {
  const col = colHeight(nodeHeights);
  const offset = (totalH - col) / 2;
  let y = offset;
  return nodeHeights.map((h) => {
    const center = y + h / 2;
    y += h + NODE_GAP;
    return center;
  });
}

export default function BranchArrows({ count, sourceIndex, srcLabels, srcHasSubtext = false, tgtLabels, tgtHasSubtext = false }) {
  if (count <= 0) return null;

  const srcNodeH = srcLabels ? measureNodeH(srcLabels, srcHasSubtext) : Array((sourceIndex ?? 0) + 1).fill(46);
  const tgtNodeH = tgtLabels ? measureNodeH(tgtLabels, tgtHasSubtext) : Array(count).fill(46);

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
    <svg className="ik-branch-arrows" viewBox={`0 0 ${w} ${h}`} style={{ height: `${h}px` }}>
      <defs>
        <marker id="ik-bhead" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto" markerUnits="strokeWidth">
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
            <path d={d}
              fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="5"
              className="ik-branch-arrows__path" style={{ animationDelay: `${i * 40}ms` }}
            />
            <path d={d}
              fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5"
              markerEnd="url(#ik-bhead)"
              className="ik-branch-arrows__path" style={{ animationDelay: `${i * 40}ms` }}
            />
          </g>
        );
      })}
    </svg>
  );
}
