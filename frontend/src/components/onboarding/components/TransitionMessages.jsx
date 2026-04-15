/* eslint-disable react-hooks/set-state-in-effect */
import { useState, useEffect } from 'react';
import DoableClawLogo from './DoableClawLogo';

/**
 * TransitionMessages - Animated message sequence shown when gap questions
 * return empty and playbook generation starts in background.
 */
const TRANSITION_MESSAGES = [
  {
    text: 'Agent has no more questions...',
    subtext: 'You provided excellent context',
    duration: 3000,
  },
  {
    text: 'Building a complete picture of your business...',
    subtext: 'Analyzing your goals, challenges, and opportunities',
    duration: 3000,
  },
  {
    text: 'Crafting your personalized growth playbook...',
    subtext: 'Creating actionable strategies tailored for you',
    duration: 3000,
  },
  {
    text: 'Almost ready!',
    subtext: 'Finalizing your customized recommendations',
    duration: 3000,
  },
];

export default function TransitionMessages({ onComplete, isComplete = false }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [fadeState, setFadeState] = useState('in'); // 'in' | 'out'
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (done) return;

    const message = TRANSITION_MESSAGES[currentIndex];
    if (!message) {
      setDone(true);
      onComplete?.();
      return;
    }

    // Start fade out before transitioning to next message
    const fadeOutTimer = setTimeout(() => {
      if (currentIndex < TRANSITION_MESSAGES.length - 1) {
        setFadeState('out');
      }
    }, message.duration - 300);

    // Move to next message
    const nextTimer = setTimeout(() => {
      if (currentIndex < TRANSITION_MESSAGES.length - 1) {
        setCurrentIndex((i) => i + 1);
        setFadeState('in');
      } else {
        setDone(true);
        onComplete?.();
      }
    }, message.duration);

    return () => {
      clearTimeout(fadeOutTimer);
      clearTimeout(nextTimer);
    };
  }, [currentIndex, done, onComplete]);

  // If playbook completes early, skip to done
  useEffect(() => {
    if (isComplete && !done) {
      setDone(true);
      onComplete?.();
    }
  }, [isComplete, done, onComplete]);

  if (done) return null;

  const message = TRANSITION_MESSAGES[currentIndex];
  if (!message) return null;

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center px-4">
      <div
        className={`flex max-w-md flex-col items-center text-center transition-all duration-300 ${
          fadeState === 'in' ? 'translate-y-0 opacity-100' : '-translate-y-4 opacity-0'
        }`}
      >
        {/* Animated logo */}
        <div className="mb-6">
          <DoableClawLogo size={72} />
        </div>

        {/* Main text */}
        <h2 className="mb-2 text-xl font-semibold text-white">{message.text}</h2>

        {/* Subtext */}
        <p className="text-sm text-white/60">{message.subtext}</p>

        {/* Progress dots */}
        <div className="mt-8 flex items-center gap-2">
          {TRANSITION_MESSAGES.map((_, idx) => (
            <div
              key={idx}
              className={`h-2 w-2 rounded-full transition-all duration-300 ${
                idx === currentIndex
                  ? 'w-6 bg-violet-500'
                  : idx < currentIndex
                    ? 'bg-violet-500/50'
                    : 'bg-white/20'
              }`}
            />
          ))}
        </div>
      </div>

      {/* Ambient glow */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-gradient-to-br from-violet-500/5 to-cyan-500/5 blur-3xl" />
      </div>
    </div>
  );
}

