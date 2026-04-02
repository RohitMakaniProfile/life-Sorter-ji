import { clsx } from 'clsx';

/** Same visual as selected journey node: light chip + purple ring (hover on dark matches this). */
const SELECTED_SURFACE =
  'border-[rgba(168,130,255,0.6)] bg-[#f0f0f0]/95 text-[#1a1a1a] shadow-[0_2px_12px_rgba(0,0,0,0.15),0_0_0_2px_rgba(168,130,255,0.25)]';

/**
 * Reusable node chip used in the tree/mind-map view.
 */
export default function FlowNode({ label, subtext, variant = 'dark', active = false, onClick }) {
  const darkInteractive = variant === 'dark' && onClick;

  return (
    <div
      className={clsx(
        'group inline-flex w-[220px] flex-col items-center justify-center rounded-[10px] border px-4 py-2.5 text-center leading-snug transition-all duration-[650ms] [white-space:normal] select-none',
        variant === 'light' && active && SELECTED_SURFACE,
        variant === 'light' &&
          !active &&
          'border-transparent bg-[#f0f0f0]/95 text-[#1a1a1a] shadow-[0_2px_12px_rgba(0,0,0,0.15)]',
        variant === 'dark' && 'border-[#505050] bg-[#151515] text-white',
        darkInteractive &&
          !active && [
            'hover:bg-[#f0f0f0]/95 hover:text-[#1a1a1a] hover:border-[rgba(168,130,255,0.6)]',
            'hover:shadow-[0_2px_12px_rgba(0,0,0,0.15),0_0_0_2px_rgba(168,130,255,0.25)]',
          ],
        variant === 'outline' && 'border-white/15 bg-transparent text-white/85',
        onClick && 'cursor-pointer',
      )}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <span className="text-xs font-semibold leading-snug">{label}</span>
      {subtext && (
        <span
          className={clsx(
            'mt-0.5 text-[10px] font-normal opacity-60',
            variant === 'light' && 'text-[#555] opacity-100',
            darkInteractive && 'group-hover:text-[#555] group-hover:opacity-100',
          )}
        >
          {subtext}
        </span>
      )}
    </div>
  );
}
