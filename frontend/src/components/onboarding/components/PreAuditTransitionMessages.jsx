import { useState, useEffect, useRef } from 'react';
import CrawlUrlList from '../../ai/chat/CrawlUrlList';
import DoableClawLogo from './DoableClawLogo';

const MESSAGES = [
  {
    id: 'understanding',
    text: 'Agent understood your answers...',
    subtext: 'Connecting your business context with goals',
  },
  {
    id: 'visiting',
    text: 'Agent is visiting your website...',
    subtext: 'Exploring pages and gathering information',
  },
  {
    id: 'summarizing',
    text: 'Agent is summarizing website content...',
    subtext: 'Identifying key information about your business',
  },
];

export default function PreAuditTransitionMessages({
  crawlStreaming,
  crawlProgress,
  crawlProgressEvents,
}) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [fadeState, setFadeState] = useState('in');
  const timerRef = useRef(null);

  useEffect(() => {
    const message = MESSAGES[currentIndex];
    if (!message) return;

    // Stay on current message longer when crawl is still active
    let duration = 2500;
    if (currentIndex === 0 && crawlStreaming) duration = 3500;
    // Hold last message until parent unmounts this component
    if (currentIndex === MESSAGES.length - 1) return;

    const fadeOut = setTimeout(() => setFadeState('out'), duration - 300);
    timerRef.current = setTimeout(() => {
      setCurrentIndex((i) => i + 1);
      setFadeState('in');
    }, duration);

    return () => {
      clearTimeout(fadeOut);
      clearTimeout(timerRef.current);
    };
  }, [currentIndex, crawlStreaming]);

  const message = MESSAGES[currentIndex];
  if (!message) return null;

  let subtext = message.subtext;
  if (message.id === 'visiting' && crawlProgress?.pages_crawled) {
    subtext = `Analyzed ${crawlProgress.pages_crawled} page${crawlProgress.pages_crawled > 1 ? 's' : ''} so far...`;
  } else if (message.id === 'summarizing' && crawlProgress?.pages_crawled) {
    subtext = `Processing insights from ${crawlProgress.pages_crawled} pages`;
  }

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center px-4">
      <div
        className={`flex max-w-md flex-col items-center text-center transition-all duration-300 ${
          fadeState === 'in' ? 'translate-y-0 opacity-100' : '-translate-y-4 opacity-0'
        }`}
      >
        <div className="mb-6">
          <DoableClawLogo size={72} />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-white">{message.text}</h2>
        <p className="text-sm text-white/60">{subtext}</p>

        <div className="mt-8 flex items-center gap-2">
          {MESSAGES.map((_, idx) => (
            <div
              key={idx}
              className={`h-2 rounded-full transition-all duration-300 ${
                idx === currentIndex
                  ? 'w-6 bg-violet-500'
                  : idx < currentIndex
                    ? 'w-2 bg-violet-500/50'
                    : 'w-2 bg-white/20'
              }`}
            />
          ))}
        </div>

        <div className="mt-4 text-xs text-white/40">Website Analysis</div>
      </div>

      {crawlProgressEvents && crawlProgressEvents.length > 0 && (
        <div className="mt-6 w-full max-w-md">
          <CrawlUrlList progressEvents={crawlProgressEvents} />
        </div>
      )}

      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-gradient-to-br from-violet-500/5 to-amber-500/5 blur-3xl" />
      </div>
    </div>
  );
}
