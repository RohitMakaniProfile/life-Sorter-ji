/** No pointer activity for this long → start cycling outcome hovers on the journey canvas. */
export const ONBOARDING_IDLE_MS = 2_500;

/** How long each outcome stays hovered (domain branch visible) before the pre-advance pause. */
export const OUTCOME_LOOP_HOLD_MS = 2_500;
/** Pause after hold before advancing to the next outcome; hover stays on the current outcome until `pathIndex` updates. */
export const OUTCOME_LOOP_TRANSITION_MS = 500;
