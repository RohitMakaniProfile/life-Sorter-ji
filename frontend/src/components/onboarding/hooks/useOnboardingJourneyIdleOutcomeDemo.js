/* eslint-disable react-hooks/set-state-in-effect */
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  ONBOARDING_IDLE_MS,
  OUTCOME_LOOP_HOLD_MS,
  OUTCOME_LOOP_TRANSITION_MS,
} from '../onboardingDemoTimings';

const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'wheel', 'scroll'];

/** Phase 2 = hold current outcome; phase 3 = pause before advancing (hover id unchanged). */
const PHASE_HOLD = 2;
const PHASE_BEFORE_NEXT = 3;

/**
 * After `ONBOARDING_IDLE_MS` without window activity, cycles programmatic hovers on the outcome
 * column (domain branch follows from `OnboardingJourneyCanvas`). Window activity after a 300ms arm,
 * or any direct journey interaction, stops the loop and restarts the idle countdown.
 *
 * While the loop runs, some outcome stays programmatically hovered at all times (no gap between
 * switching from one outcome to the next).
 */
export function useOnboardingJourneyIdleOutcomeDemo(enabled, outcomeIds) {
  const [demoActive, setDemoActive] = useState(false);
  const [phase, setPhase] = useState(PHASE_HOLD);
  const [pathIndex, setPathIndex] = useState(0);
  const [programmaticHoveredOutcomeId, setProgrammaticHoveredOutcomeId] = useState(null);

  const idleTimerRef = useRef(null);
  const enabledRef = useRef(enabled);
  const outcomeIdsRef = useRef(outcomeIds);
  const demoActiveRef = useRef(false);
  const dismissArmedRef = useRef(false);

  const n = Math.max(outcomeIds.length, 1);

  useEffect(() => {
    outcomeIdsRef.current = outcomeIds;
  }, [outcomeIds]);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    demoActiveRef.current = demoActive;
  }, [demoActive]);

  const stopDemo = useCallback(() => {
    setDemoActive(false);
    setPhase(PHASE_HOLD);
    setPathIndex(0);
  }, []);

  const armIdleTimer = useCallback(() => {
    clearTimeout(idleTimerRef.current);
    if (!enabledRef.current) return;
    idleTimerRef.current = setTimeout(() => {
      if (!enabledRef.current || outcomeIdsRef.current.length === 0) return;
      setDemoActive(true);
    }, ONBOARDING_IDLE_MS);
  }, []);

  const onUserActivity = useCallback(() => {
    if (demoActiveRef.current && !dismissArmedRef.current) return;

    clearTimeout(idleTimerRef.current);
    if (demoActiveRef.current) {
      stopDemo();
    }
    armIdleTimer();
  }, [stopDemo, armIdleTimer]);

  useEffect(() => {
    if (!enabled) {
      clearTimeout(idleTimerRef.current);
      stopDemo();
      return;
    }
    armIdleTimer();
    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, onUserActivity, { passive: true }));
    return () => {
      clearTimeout(idleTimerRef.current);
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, onUserActivity));
    };
  }, [enabled, onUserActivity, armIdleTimer, stopDemo]);

  useEffect(() => {
    if (!demoActive) {
      dismissArmedRef.current = false;
      return;
    }
    dismissArmedRef.current = false;
    const t = setTimeout(() => {
      dismissArmedRef.current = true;
    }, 300);
    return () => clearTimeout(t);
  }, [demoActive]);

  useEffect(() => {
    if (!demoActive) {
      setPathIndex(0);
      setPhase(PHASE_HOLD);
      return;
    }
    setPhase(PHASE_HOLD);
    setPathIndex(0);
  }, [demoActive]);

  useEffect(() => {
    if (!demoActive || !enabled) return;

    const delay = phase === PHASE_HOLD ? OUTCOME_LOOP_HOLD_MS : OUTCOME_LOOP_TRANSITION_MS;

    const t = setTimeout(() => {
      if (phase === PHASE_BEFORE_NEXT) {
        setPathIndex((p) => (p + 1) % n);
        setPhase(PHASE_HOLD);
      } else {
        setPhase(PHASE_BEFORE_NEXT);
      }
    }, delay);

    return () => clearTimeout(t);
  }, [phase, pathIndex, demoActive, enabled, n]);

  useEffect(() => {
    if (!enabled || outcomeIds.length === 0) {
      setProgrammaticHoveredOutcomeId(null);
      return;
    }
    // If the user interacted, we stop the idle demo loop (`demoActive=false`), but we keep the
    // last programmatic hovered outcome so the UI doesn't "cancel" what the user was just
    // looking at / about to click.
    if (!demoActive) return;

    setProgrammaticHoveredOutcomeId(outcomeIds[pathIndex % outcomeIds.length]);
  }, [demoActive, enabled, pathIndex, outcomeIds]);

  const onJourneyDirectInteraction = useCallback(() => {
    clearTimeout(idleTimerRef.current);
    if (demoActiveRef.current) {
      stopDemo();
    }
    armIdleTimer();
  }, [stopDemo, armIdleTimer]);

  return { programmaticHoveredOutcomeId, onJourneyDirectInteraction };
}
