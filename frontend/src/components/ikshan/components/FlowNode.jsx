import './FlowNode.css';

/**
 * Reusable node chip used in the tree/mind-map view.
 * @param {string}  label     - Primary text (e.g. "Lead Generation")
 * @param {string}  subtext   - Secondary text (e.g. "Marketing, SEO & Social")
 * @param {string}  variant   - 'light' (selected/origin) | 'dark' (option) | 'outline' (unselected)
 * @param {boolean} active    - Adds highlight ring
 * @param {function} onClick  - Click handler
 */
export default function FlowNode({ label, subtext, variant = 'dark', active = false, onClick }) {
  const classes = [
    'ik-flow-node',
    `ik-flow-node--${variant}`,
    active ? 'ik-flow-node--active' : '',
    onClick ? 'ik-flow-node--clickable' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={classes} onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}>
      <span className="ik-flow-node__label">{label}</span>
      {subtext && <span className="ik-flow-node__subtext">{subtext}</span>}
    </div>
  );
}
