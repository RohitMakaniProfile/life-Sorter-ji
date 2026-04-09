/* eslint-disable react-hooks/set-state-in-effect */
import { useState, useEffect, useRef } from 'react';
import { Globe, Brain, FileSearch, Search, MessageCircleQuestion } from 'lucide-react';

/**
 * AnalysisTransitionMessages - Animated message sequence shown after scale questions
 * are submitted while waiting for website analysis and RCA question generation.
 *
 * Messages progress based on actual crawl/analysis state:
 * - Phase 1: Website analysis (while crawlStreaming)
 * - Phase 2: Understanding answers (brief)
 * - Phase 3: Summarizing content (while crawl finishing)
 * - Phase 4: Finding root cause (when RCA API called)
 * - Phase 5: Preparing questions (just before showing)
 */

const ANALYSIS_MESSAGES = [
  {
    id: 'visiting',
    icon: Globe,
    text: 'Agent is visiting your website...',
    subtext: 'Exploring pages and gathering information',
    phase: 'crawl',
  },
  {
    id: 'understanding',
    icon: Brain,
    text: 'Agent understood your answers...',
    subtext: 'Connecting your business context with goals',
    phase: 'crawl',
  },
  {
    id: 'summarizing',
    icon: FileSearch,
    text: 'Agent is summarizing website content...',
    subtext: 'Identifying key information about your business',
    phase: 'crawl',
  },
  {
    id: 'rootcause',
    icon: Search,
    text: 'Finding root cause of your problem...',
    subtext: 'Analyzing patterns and potential blockers',
    phase: 'rca',
  },
  {
    id: 'questions',
    icon: MessageCircleQuestion,
    text: 'Agent has questions about the root cause...',
    subtext: 'Preparing diagnostic questions based on analysis',
    phase: 'rca',
  },
];

export default function AnalysisTransitionMessages({
  crawlStreaming,
  crawlProgress,
  rcaCalling,
  onComplete,
  isComplete = false,
}) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [fadeState, setFadeState] = useState('in');
  const [done, setDone] = useState(false);
  const lastPhaseRef = useRef('crawl');
  const messageTimerRef = useRef(null);

  // Determine current phase based on props
  const currentPhase = rcaCalling ? 'rca' : 'crawl';

  // Progress through messages based on time and phase
  useEffect(() => {
    if (done || isComplete) return;

    const message = ANALYSIS_MESSAGES[currentIndex];
    if (!message) {
      setDone(true);
      onComplete?.();
      return;
    }

    // If we've moved to RCA phase and current message is still crawl phase,
    // fast-forward to RCA messages
    if (currentPhase === 'rca' && message.phase === 'crawl') {
      const rcaStartIndex = ANALYSIS_MESSAGES.findIndex(m => m.phase === 'rca');
      if (rcaStartIndex > currentIndex) {
        setFadeState('out');
        setTimeout(() => {
          setCurrentIndex(rcaStartIndex);
          setFadeState('in');
        }, 300);
        return;
      }
    }

    // Calculate duration based on phase and message
    let duration = 2500; // Default duration

    // First message stays longer if crawl is still running
    if (currentIndex === 0 && crawlStreaming) {
      duration = 3500;
    }

    // If this is the last message in current phase and phase hasn't changed, stay longer
    const nextMessage = ANALYSIS_MESSAGES[currentIndex + 1];
    if (nextMessage && nextMessage.phase !== message.phase && currentPhase === message.phase) {
      duration = 4000; // Wait longer at phase boundary
    }

    // Start fade out before transitioning
    const fadeOutTimer = setTimeout(() => {
      if (currentIndex < ANALYSIS_MESSAGES.length - 1) {
        setFadeState('out');
      }
    }, duration - 300);

    // Move to next message
    messageTimerRef.current = setTimeout(() => {
      if (currentIndex < ANALYSIS_MESSAGES.length - 1) {
        // Only advance if we're allowed to (phase matches or we're past it)
        const next = ANALYSIS_MESSAGES[currentIndex + 1];
        if (!next || next.phase === currentPhase ||
            (currentPhase === 'rca' && next.phase === 'rca')) {
          setCurrentIndex(i => i + 1);
          setFadeState('in');
        }
      }
    }, duration);

    return () => {
      clearTimeout(fadeOutTimer);
      if (messageTimerRef.current) clearTimeout(messageTimerRef.current);
    };
  }, [currentIndex, done, isComplete, onComplete, currentPhase, crawlStreaming]);

  // Track phase changes
  useEffect(() => {
    lastPhaseRef.current = currentPhase;
  }, [currentPhase]);

  // Complete when isComplete becomes true
  useEffect(() => {
    if (isComplete && !done) {
      // Show last message briefly then complete
      const lastIndex = ANALYSIS_MESSAGES.length - 1;
      if (currentIndex < lastIndex) {
        setFadeState('out');
        setTimeout(() => {
          setCurrentIndex(lastIndex);
          setFadeState('in');
          setTimeout(() => {
            setDone(true);
            onComplete?.();
          }, 800);
        }, 300);
      } else {
        setTimeout(() => {
          setDone(true);
          onComplete?.();
        }, 500);
      }
    }
  }, [isComplete, done, onComplete, currentIndex]);

  if (done) return null;

  const message = ANALYSIS_MESSAGES[currentIndex];
  if (!message) return null;

  const IconComponent = message.icon;

  // Build subtext with crawl progress if available
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
        {/* Icon */}
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-violet-500/20 to-amber-500/20 ring-1 ring-white/10">
          <IconComponent className="h-8 w-8 text-violet-400" />
        </div>

        {/* Main text */}
        <h2 className="mb-2 text-xl font-semibold text-white">{message.text}</h2>

        {/* Subtext */}
        <p className="text-sm text-white/60">{subtext}</p>

        {/* Progress dots */}
        <div className="mt-8 flex items-center gap-2">
          {ANALYSIS_MESSAGES.map((_, idx) => (
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

        {/* Phase indicator */}
        <div className="mt-4 flex items-center gap-2 text-xs text-white/40">
          <span className={currentPhase === 'crawl' ? 'text-violet-400' : ''}>
            Website Analysis
          </span>
          <span>→</span>
          <span className={currentPhase === 'rca' ? 'text-violet-400' : ''}>
            Root Cause Detection
          </span>
        </div>
      </div>

      {/* Ambient animation */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-gradient-to-br from-violet-500/5 to-amber-500/5 blur-3xl" />
      </div>
    </div>
  );
}

