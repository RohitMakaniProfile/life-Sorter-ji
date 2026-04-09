import { useCallback, useEffect, useRef, useState } from 'react';
import { runResumableTaskStream, getStoredTaskStreamId } from '../../../api/services/taskStream';
import { monitorTaskStreamStart, monitorTaskStreamEvent, monitorTaskStreamDone, monitorTaskStreamError } from '../../../api/services/taskStreamMonitor';

const TASK_TYPE_PLAYBOOK_GENERATE = 'playbook/onboarding-generate';
const STORAGE_PLAYBOOK_STEP_REACHED = 'doable-claw-playbook-step-reached';
const PARTIAL_PLAYBOOK_PREFIX = 'life-sorter-playbook-partial:';

function safeGetItem(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSetItem(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore
  }
}

function safeRemoveItem(key) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

function hasPlaybookStepReached() {
  return safeGetItem(STORAGE_PLAYBOOK_STEP_REACHED) === '1';
}

function partialPlaybookKey(sessionId) {
  return `${PARTIAL_PLAYBOOK_PREFIX}${sessionId}`;
}

function loadPartialPlaybook(sessionId) {
  return safeGetItem(partialPlaybookKey(sessionId)) || '';
}

function savePartialPlaybook(sessionId, value) {
  safeSetItem(partialPlaybookKey(sessionId), value || '');
}

function clearPartialPlaybook(sessionId) {
  safeRemoveItem(partialPlaybookKey(sessionId));
}

export function usePlaybookTaskStream({ ensureSession, otpVerified, onRequestOtp, onShowPlaybook, setError }) {
  const [playbookStreaming, setPlaybookStreaming] = useState(false);
  const [playbookText, setPlaybookText] = useState('');
  const [playbookDone, setPlaybookDone] = useState(false);
  const [playbookResult, setPlaybookResult] = useState(null);

  const pendingSidRef = useRef(null);
  const runIdRef = useRef(0);
  const autoResumeTriggeredRef = useRef(false);
  const [needsManualRetry, setNeedsManualRetry] = useState(false);

  const stopStreaming = useCallback(() => {
    setPlaybookStreaming(false);
  }, []);

  const resetPlaybackState = useCallback(() => {
    setPlaybookStreaming(true);
    setPlaybookText('');
    setPlaybookDone(false);
    setPlaybookResult(null);
    setNeedsManualRetry(false);
  }, []);

  const markStepReached = useCallback(() => {
    safeSetItem(STORAGE_PLAYBOOK_STEP_REACHED, '1');
  }, []);

  const clearStepReached = useCallback(() => {
    safeRemoveItem(STORAGE_PLAYBOOK_STEP_REACHED);
  }, []);

  const startForSession = useCallback(
    async (sid, { fresh = true } = {}) => {
      const onboardingId = sid;
      if (!onboardingId) return;

      if (!fresh) {
        // Keep current UI state, but make sure streaming indicator is on.
        setPlaybookStreaming(true);
        const existing = loadPartialPlaybook(onboardingId);
        if (existing) setPlaybookText(existing);
      } else {
        resetPlaybackState();
        clearPartialPlaybook(onboardingId);
      }

      // Starting from UI implies user reached this step; allow future auto-resume.
      markStepReached();
      onShowPlaybook?.();

      // OTP gate: store pending and let effect below resume once verified.
      if (!otpVerified) {
        pendingSidRef.current = onboardingId;
        onRequestOtp?.();
        return;
      }

      const myRunId = ++runIdRef.current;
      let finished = false;
      const callbacks = {
        onEvent: (e) => {
          if (runIdRef.current !== myRunId) return;
          if (!e || typeof e !== 'object') return;
          if (e.stream_id) monitorTaskStreamStart({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: String(e.stream_id), onboardingId });
          monitorTaskStreamEvent({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, onboardingId, event: e });
          if (e.type === 'token' && e.token) {
            setPlaybookText((t) => {
              const next = t + String(e.token);
              savePartialPlaybook(onboardingId, next);
              return next;
            });
          }
        },
        onDone: (e) => {
          if (runIdRef.current !== myRunId) return;
          finished = true;
          // Playbook is done — clear flag so auto-resume never re-triggers on next page load
          safeRemoveItem(STORAGE_PLAYBOOK_STEP_REACHED);
          setPlaybookStreaming(false);
          setPlaybookDone(true);
          setPlaybookResult({
            playbook: e.playbook || '',
            website_audit: e.website_audit || '',
            context_brief: e.context_brief || '',
            icp_card: e.icp_card || '',
          });
          clearPartialPlaybook(onboardingId);
          monitorTaskStreamDone({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, onboardingId, event: e });
        },
        onError: (e) => {
          if (runIdRef.current !== myRunId) return;
          finished = true;
          setPlaybookStreaming(false);
          setPlaybookDone(false);
          setPlaybookResult(null);
          setNeedsManualRetry(true);
          setError?.(e?.message || 'Playbook generation failed');
          monitorTaskStreamError({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e?.stream_id, onboardingId, event: e });
        },
      };

      await runResumableTaskStream(TASK_TYPE_PLAYBOOK_GENERATE, {
        userId: null,
        onboardingId,
        payload: { onboarding_id: onboardingId },
        maxRetries: 4,
        shouldStop: () => runIdRef.current !== myRunId,
        callbacks,
      });

      if (!finished && runIdRef.current === myRunId) {
        setPlaybookStreaming(false);
        setPlaybookDone(false);
        setPlaybookResult(null);
        setNeedsManualRetry(true);
        setError?.('Playbook stream disconnected. Please retry.');
      }
    },
    [ensureSession, otpVerified, onRequestOtp, onShowPlaybook, resetPlaybackState, setError, markStepReached],
  );

  // Resume after refresh (localStorage has a stream_id) using the onboarding actor id.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (autoResumeTriggeredRef.current) return;
        // Only auto-resume if the user had actually reached the playbook step before.
        if (!hasPlaybookStepReached()) return;
        const sid = await ensureSession();
        if (cancelled || !sid) return;

        autoResumeTriggeredRef.current = true;
        const storedStreamId = getStoredTaskStreamId(TASK_TYPE_PLAYBOOK_GENERATE, { onboardingId: sid, userId: null });
        if (!storedStreamId) return;

        // Auto-attach without status polling. If stale/expired, the attach will error and we'll ignore it.
        onShowPlaybook?.();

        setPlaybookStreaming(true);
        setPlaybookText(loadPartialPlaybook(sid));
        setPlaybookDone(false);
        setPlaybookResult(null);
        setNeedsManualRetry(false);

        const myRunId = ++runIdRef.current;
        let finished = false;

        await runResumableTaskStream(TASK_TYPE_PLAYBOOK_GENERATE, {
          userId: null,
          onboardingId: sid,
          payload: { onboarding_id: sid },
          maxRetries: 4,
          shouldStop: () => runIdRef.current !== myRunId,
          callbacks: {
            onEvent: (e) => {
              if (runIdRef.current !== myRunId) return;
              if (!e || typeof e !== 'object') return;
              if (e.stream_id) monitorTaskStreamStart({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: String(e.stream_id), onboardingId: sid });
              monitorTaskStreamEvent({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, onboardingId: sid, event: e });
              if (e.type === 'token' && e.token) {
                setPlaybookText((t) => {
                  const next = t + String(e.token);
                  savePartialPlaybook(sid, next);
                  return next;
                });
              }
            },
            onDone: (e) => {
              if (runIdRef.current !== myRunId) return;
              finished = true;
              // Clear flag so auto-resume doesn't re-trigger on next page load
              safeRemoveItem(STORAGE_PLAYBOOK_STEP_REACHED);
              setPlaybookStreaming(false);
              setPlaybookDone(true);
              setPlaybookResult({
                playbook: e.playbook || '',
                website_audit: e.website_audit || '',
                context_brief: e.context_brief || '',
                icp_card: e.icp_card || '',
              });
              clearPartialPlaybook(sid);
              monitorTaskStreamDone({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, onboardingId: sid, event: e });
            },
            onError: (e) => {
              if (runIdRef.current !== myRunId) return;
              finished = true;
              setPlaybookStreaming(false);
              setPlaybookDone(false);
              setPlaybookResult(null);
              setNeedsManualRetry(true);
              setError?.(e?.message || 'Playbook generation failed');
              monitorTaskStreamError({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e?.stream_id, onboardingId: sid, event: e });
            },
          },
        });

        if (!finished && runIdRef.current === myRunId) {
          setPlaybookStreaming(false);
          setPlaybookDone(false);
          setPlaybookResult(null);
          setNeedsManualRetry(true);
          setError?.('Playbook stream disconnected. Please retry.');
        }
      } catch {
        // Ignore auto-resume failures.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ensureSession, onShowPlaybook, setError]);

  // Resume pending start once OTP becomes verified.
  useEffect(() => {
    if (!otpVerified) return;
    const sid = pendingSidRef.current;
    if (!sid) return;
    pendingSidRef.current = null;
    startForSession(sid, { fresh: true }).catch(() => {});
  }, [otpVerified, startForSession]);

  const markRetryNeeded = useCallback(() => {
    setPlaybookStreaming(false);
    setPlaybookDone(false);
    setPlaybookResult(null);
    setNeedsManualRetry(true);
  }, []);

  const clearResumeArtifacts = useCallback(() => {
    try {
      const keys = [];
      for (let i = 0; i < window.localStorage.length; i += 1) {
        const key = window.localStorage.key(i);
        if (!key) continue;
        if (
          key === STORAGE_PLAYBOOK_STEP_REACHED ||
          key.startsWith('ikshan-taskstream') ||
          key.startsWith(PARTIAL_PLAYBOOK_PREFIX)
        ) {
          keys.push(key);
        }
      }
      keys.forEach((k) => window.localStorage.removeItem(k));
    } catch {
      // ignore storage cleanup failures
    }
  }, []);

  return {
    playbookStreaming,
    playbookText,
    playbookDone,
    playbookResult,
    needsManualRetry,
    prepareStreaming: resetPlaybackState,
    markRetryNeeded,
    stopStreaming,
    startForSession,
    markStepReached,
    clearStepReached,
    clearResumeArtifacts,
  };
}
