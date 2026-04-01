import { useState, useRef, useEffect } from 'react';

const IDLE_TIMEOUT = 2_500;

export function useOnboardingIdleScreensaver() {
  const [showScreensaver, setShowScreensaver] = useState(false);
  const idleTimerRef = useRef(null);

  useEffect(() => {
    if (showScreensaver) return;
    const resetIdle = () => {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = setTimeout(() => setShowScreensaver(true), IDLE_TIMEOUT);
    };
    resetIdle();
    const events = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'wheel', 'scroll'];
    events.forEach((e) => window.addEventListener(e, resetIdle));
    return () => {
      clearTimeout(idleTimerRef.current);
      events.forEach((e) => window.removeEventListener(e, resetIdle));
    };
  }, [showScreensaver]);

  return { showScreensaver, setShowScreensaver };
}
