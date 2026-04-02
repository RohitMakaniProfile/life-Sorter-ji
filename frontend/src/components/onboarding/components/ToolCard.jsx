/**
 * Tool recommendation card in the URL stage carousel.
 */
export default function ToolCard({ name, rating, description, bullets = [], tag, url }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex min-w-[260px] max-w-[320px] shrink-0 flex-col rounded-[14px] border border-[#b3b3b3] bg-[#161616] font-sans text-white no-underline shadow-[0_2px_8px_rgba(0,0,0,0.3)] transition-all duration-[650ms] hover:-translate-y-[3px] hover:border-white/[0.22] hover:shadow-[0_4px_16px_rgba(0,0,0,0.4)]"
    >
      <div className="flex items-center justify-between rounded-t-[14px] border-b border-white/[0.06] bg-[#252525] px-4 py-3">
        <span className="text-[15px] font-bold tracking-tight text-white">{name}</span>
        {rating && (
          <span className="flex items-center gap-1 rounded-full bg-[rgba(76,140,50,0.35)] px-2 py-0.5 text-xs font-semibold whitespace-nowrap text-[#e8b931]">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="#e8b931">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.56 5.82 22 7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
            {rating}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 px-4 py-3 pb-3.5">
        {tag && (
          <span className="order-3 mt-auto self-start rounded bg-[rgba(110,60,180,0.3)] px-2 py-0.5 text-[9px] font-bold tracking-wider text-purple-300 uppercase">
            {tag}
          </span>
        )}
        <p className="order-1 m-0 text-[12.5px] leading-relaxed text-[#f0f0f0]">{description}</p>
        {bullets.length > 0 && (
          <ul className="order-2 m-0 flex list-disc flex-col gap-1 pl-4 marker:text-white/35">
            {bullets.map((b, i) => (
              <li key={i} className="text-[11.5px] leading-snug text-white/50">
                {b}
              </li>
            ))}
          </ul>
        )}
      </div>
    </a>
  );
}
