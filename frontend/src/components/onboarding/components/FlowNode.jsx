import { clsx } from 'clsx';

/**
 * Reusable node chip used in the tree/mind-map view.
 */
export default function FlowNode({ label, subtext, variant = 'dark', active = false, onClick }) {
  return (
    <div
      className={clsx(
        'inline-flex w-[220px] flex-col items-center justify-center rounded-[10px] px-4 py-2.5 text-center leading-snug transition-all duration-[250ms] [white-space:normal] select-none',
        variant === 'light' && 'bg-[#f0f0f0]/95 text-[#1a1a1a] shadow-[0_2px_12px_rgba(0,0,0,0.15)]',
        variant === 'dark' && 'border border-[#505050] bg-[#151515] text-white',
        variant === 'outline' && 'border border-white/15 bg-transparent text-white/85',
        onClick && 'cursor-pointer hover:-translate-y-0.5',
        variant === 'dark' &&
          onClick &&
          'hover:bg-white/10 hover:border-white/25 hover:shadow-[0_6px_24px_rgba(0,0,0,0.3)]',
        variant === 'light' && onClick && 'hover:shadow-[0_6px_24px_rgba(0,0,0,0.25)]',
        active && '!border-[rgba(168,130,255,0.6)] shadow-[0_0_0_2px_rgba(168,130,255,0.25)]',
      )}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <span className="text-xs font-semibold leading-snug">{label}</span>
      {subtext && (
        <span
          className={clsx('mt-0.5 text-[10px] font-normal opacity-60', variant === 'light' && 'text-[#555] opacity-100')}
        >
          {subtext}
        </span>
      )}
    </div>
  );
}
