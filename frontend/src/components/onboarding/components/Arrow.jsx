/**
 * Arrow component - combines a stretching curved line with a fixed-size arrow head.
 * The line stretches to fill the container width, while the arrow head stays fixed size.
 * They are placed in sequence (line ends where head begins).
 *
 * @param {boolean} dashed - If true, uses dashed line. If false, uses solid line. Default: true
 */
export default function Arrow({ className, style, dashed = true }) {
  const lineSrc = dashed ? '/arrow-line.svg' : '/arrow-line-solid.svg';

  return (
    <div
      className={`flex items-start ${className || ''}`}
      style={style}
    >
      {/* Curved line - stretches to fill remaining space */}
      <img
        src={lineSrc}
        alt=""
        className="flex-1 h-full min-w-0"
      />
      {/* Arrow head - fixed size, aligned with the upper horizontal line */}
      <img
        src="/arrow-head.svg"
        alt=""
        className="w-[14px] h-[14px] shrink-0"
        style={{ marginTop: '8px' }}
      />
    </div>
  );
}

