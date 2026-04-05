import FlowNode from '../components/FlowNode';
import ToolCard from '../components/ToolCard';
import Arrow from '../components/Arrow';

const TOOLS_PER_PAGE = 3;

export default function UrlStage({
  selectedDomain,
  selectedTask,
  taskNodeContainerRef,
  urlValue,
  gbpValue,
  onUrlChange,
  onGbpChange,
  urlTab,
  onTabChange,
  onSubmit,
  onSkip,
  urlSubmitting,
  crawlRunning,
  earlyTools,
  toolPage,
  onToolPageChange,
  onBack,
}) {
  const totalPages = Math.ceil(earlyTools.length / TOOLS_PER_PAGE);
  const pageTools = earlyTools.slice(toolPage * TOOLS_PER_PAGE, (toolPage + 1) * TOOLS_PER_PAGE);

  const isWebsite = urlTab === 'website';
  const currentValue = isWebsite ? urlValue : gbpValue;
  const currentOnChange = isWebsite ? onUrlChange : onGbpChange;
  const placeholder = isWebsite ? 'yourcompany.com' : 'google.com/maps/place/your-business';

  return (
    <div className="flex flex-1 flex-col items-center overflow-hidden px-6 py-4 pb-3 font-sans">
      <h1 className="m-0 mb-4 text-center text-[clamp(20px,2.8vw,34px)] leading-tight font-extrabold text-white">
        Get Business{' '}
        <span className="bg-gradient-to-br from-amber-500 to-orange-500 bg-clip-text text-transparent">Audit</span>{' '}
        report and{' '}
        <span className="bg-gradient-to-br from-[#a882ff] to-[#7c4dff] bg-clip-text text-transparent">Playbook</span>
      </h1>

      <div className="mb-4 flex w-full max-w-[1100px] flex-col items-center gap-4 md:flex-row md:flex-nowrap md:items-center md:justify-center">
        <div ref={taskNodeContainerRef} className="shrink-0">
          <FlowNode label={selectedTask || selectedDomain} variant="light" active />
        </div>

        {/* Curved solid arrow — stretches responsively between node and URL box */}
        <Arrow
          dashed={false}
          className="hidden md:flex shrink-0"
          style={{ width: 'clamp(60px, 8vw, 130px)', height: '60px', marginTop: '-20px' }}
        />

        <div className="w-full min-w-[min(100%,340px)] max-w-[420px] shrink-0">
          <div className="flex flex-col gap-2.5 rounded-[14px] border border-[#b3b3b3] bg-[#161616] p-4 shadow-[0_2px_8px_rgba(0,0,0,0.3)]">
            <div className="flex gap-4">
              <button
                type="button"
                className={`cursor-pointer border-none bg-transparent p-0 text-[13px] font-semibold transition-colors ${
                  isWebsite ? 'text-white' : 'text-white/35 hover:text-white/60'
                }`}
                onClick={() => onTabChange('website')}
              >
                Website URL
              </button>
              <button
                type="button"
                className={`cursor-pointer border-none bg-transparent p-0 text-[13px] font-semibold transition-colors ${
                  !isWebsite ? 'text-white' : 'text-white/35 hover:text-white/60'
                }`}
                onClick={() => onTabChange('gbp')}
              >
                Google Business Profile URI
              </button>
            </div>
            <form onSubmit={onSubmit}>
              <input
                className="mb-1 w-full rounded-lg border border-[rgba(179,179,179,0.4)] bg-white/5 px-3.5 py-2.5 text-[13px] text-[#f0f0f0] outline-none transition-colors placeholder:text-white/30 focus:border-[rgba(168,130,255,0.5)]"
                type="text"
                placeholder={placeholder}
                value={currentValue}
                onChange={(e) => currentOnChange(e.target.value)}
                autoFocus
                key={urlTab}
              />
              <button
                className="mt-1.5 w-full cursor-pointer rounded-[10px] border-none bg-gradient-to-r from-[rgba(133,123,255,0.85)] to-[#BF69A2] py-2.5 text-sm font-extrabold tracking-wide text-white transition-all hover:brightness-110 hover:[transform:translateY(-1px)] disabled:cursor-not-allowed disabled:bg-gradient-to-r disabled:from-[rgba(133,123,255,0.26)] disabled:to-[rgba(191,105,162,0.4)] disabled:hover:transform-none"
                type="submit"
                disabled={urlSubmitting || (!urlValue.trim() && !gbpValue.trim())}
              >
                {urlSubmitting || crawlRunning ? 'Analyzing...' : 'Analyze My Business'}
              </button>
            </form>
            <button
              type="button"
              className="cursor-pointer border-none bg-transparent p-1 text-center text-xs text-white/40 hover:text-white/70"
              onClick={onSkip}
              disabled={urlSubmitting}
            >
              Skip — without URLs, we&apos;ll give general recommendations
            </button>
          </div>
        </div>
      </div>

      {earlyTools.length > 0 && (
        <div className="mb-2 flex w-full max-w-[1100px] flex-col">
          <h2 className="m-0 mb-2.5 shrink-0 text-center text-lg font-bold text-white">Best Tools For You</h2>
          <div className="relative flex items-stretch gap-0">
            <button
              type="button"
              className="z-[2] flex w-11 shrink-0 cursor-pointer items-center justify-center rounded-l-xl border border-[#b3b3b3] bg-[#161616] text-white/60 transition-colors hover:bg-[rgba(165,120,255,0.15)] hover:text-white disabled:cursor-not-allowed disabled:opacity-20"
              onClick={() => onToolPageChange((p) => p - 1)}
              disabled={toolPage === 0}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            </button>
            <div className="flex flex-1 animate-[ob-carousel-slide_0.3s_ease] gap-3 px-3 py-1.5 [&>*]:min-w-0 [&>*]:max-w-none [&>*]:flex-1">
              {pageTools.map((tool, i) => (
                <ToolCard
                  key={toolPage * TOOLS_PER_PAGE + i}
                  name={tool.name}
                  rating={tool.rating}
                  description={tool.description}
                  bullets={tool.bullets}
                  tag={tool.tag}
                  url={tool.url}
                />
              ))}
            </div>
            <button
              type="button"
              className="z-[2] flex w-11 shrink-0 cursor-pointer items-center justify-center rounded-r-xl border border-[#b3b3b3] bg-[#161616] text-white/60 transition-colors hover:bg-[rgba(165,120,255,0.15)] hover:text-white disabled:cursor-not-allowed disabled:opacity-20"
              onClick={() => onToolPageChange((p) => p + 1)}
              disabled={toolPage >= totalPages - 1}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M9 18l6-6-6-6" />
              </svg>
            </button>
          </div>
          <div className="mt-2 flex shrink-0 justify-center gap-2">
            {Array.from({ length: totalPages }).map((_, i) => (
              <button
                key={i}
                type="button"
                className={`h-2 w-2 cursor-pointer rounded-full border-none p-0 transition-all ${
                  i === toolPage ? 'scale-[1.3] bg-[#a882ff]' : 'bg-white/15 hover:bg-white/30'
                }`}
                onClick={() => onToolPageChange(i)}
              />
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        className="mt-1 shrink-0 cursor-pointer border-none bg-transparent px-4 py-1.5 text-[13px] font-semibold text-white/50 transition-colors hover:text-white"
        onClick={onBack}
      >
        &lsaquo; BACK
      </button>
    </div>
  );
}
