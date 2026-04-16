import { useState, useEffect } from 'react';
import DoableClawLogo from './DoableClawLogo';

const MESSAGES = [
  {
    text: 'Finding root cause of your problem...',
    subtext: 'Analyzing patterns and potential blockers',
  },
  {
    text: 'Agent has questions about the root cause...',
    subtext: 'Preparing diagnostic questions based on analysis',
  },
];

export default function PreRcaTransitionMessages() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [fadeState, setFadeState] = useState('in');

  useEffect(() => {
    if (currentIndex >= MESSAGES.length - 1) return;

    const fadeOut = setTimeout(() => setFadeState('out'), 2200);
    const next = setTimeout(() => {
      setCurrentIndex((i) => i + 1);
      setFadeState('in');
    }, 2500);

    return () => {
      clearTimeout(fadeOut);
      clearTimeout(next);
    };
  }, [currentIndex]);

  const message = MESSAGES[currentIndex];
  if (!message) return null;

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
        <p className="text-sm text-white/60">{message.subtext}</p>

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

        <div className="mt-4 text-xs text-white/40">Root Cause Detection</div>
      </div>

      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-gradient-to-br from-violet-500/5 to-cyan-500/5 blur-3xl" />
      </div>
    </div>
  );
}
