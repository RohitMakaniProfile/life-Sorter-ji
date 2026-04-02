import { flushSync } from 'react-dom';

/**
 * Runs a synchronous React state update inside document.startViewTransition when supported,
 * so layout changes (e.g. onboarding journey) can animate ~300ms instead of snapping.
 */
export function runViewTransition(update) {
  if (typeof document !== 'undefined' && typeof document.startViewTransition === 'function') {
    document.startViewTransition(() => {
      flushSync(update);
    });
  } else {
    update();
  }
}
