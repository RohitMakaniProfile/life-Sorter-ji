import { useCallback, useEffect, useRef, useState } from 'react';
import { runResumableTaskStream, getStoredTaskStreamId, clearStoredTaskStreamId } from '../../../api/services/taskStream';
import { monitorTaskStreamStart, monitorTaskStreamEvent, monitorTaskStreamDone, monitorTaskStreamError } from '../../../api/services/taskStreamMonitor';

const TASK_TYPE_PLAYBOOK_GENERATE = 'playbook/onboarding-generate';
const STORAGE_PLAYBOOK_STEP_REACHED = 'life-sorter-playbook-step-reached';
const STORAGE_PLAYBOOK_PARTIAL_PREFIX = 'life-sorter-playbook-partial';
const TASKSTREAM_STREAM_ID_PREFIX = `ikshan-taskstream:stream_id:${TASK_TYPE_PLAYBOOK_GENERATE}:`;
const TASKSTREAM_CURSOR_PREFIX = 'ikshan-taskstream:cursor:';

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

function partialKey(sessionId) {
  return `${STORAGE_PLAYBOOK_PARTIAL_PREFIX}:${String(sessionId || '').trim()}`;
}

function loadPartialPlaybook(sessionId) {
  const key = partialKey(sessionId);
  return safeGetItem(key) || '';
}

function savePartialPlaybook(sessionId, text) {
  const key = partialKey(sessionId);
  safeSetItem(key, text || '');
}

function clearPartialPlaybook(sessionId) {
  const key = partialKey(sessionId);
  safeRemoveItem(key);
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

  const clearResumeArtifacts = useCallback((sid) => {
    const sessionId = String(sid || '').trim();
    safeRemoveItem(STORAGE_PLAYBOOK_STEP_REACHED);
    try {
      const staleStreamIds = [];
      for (let i = 0; i < window.localStorage.length; i += 1) {
        const k = window.localStorage.key(i);
        if (!k || !k.startsWith(TASKSTREAM_STREAM_ID_PREFIX)) continue;
        const streamId = safeGetItem(k);
        if (streamId) staleStreamIds.push(streamId);
        safeRemoveItem(k);
      }
      staleStreamIds.forEach((id) => safeRemoveItem(`${TASKSTREAM_CURSOR_PREFIX}${id}`));
    } catch {
      // ignore
    }
    if (sessionId) {
      clearStoredTaskStreamId(TASK_TYPE_PLAYBOOK_GENERATE, { sessionId, userId: null });
      clearPartialPlaybook(sessionId);
    }
  }, []);

  const startForSession = useCallback(
    async (sid, { fresh = true } = {}) => {
      const sessionId = sid;
      if (!sessionId) return;

      if (!fresh) {
        // Keep current UI state, but make sure streaming indicator is on.
        setPlaybookStreaming(true);
        setPlaybookText((prev) => prev || loadPartialPlaybook(sessionId));
      } else {
        resetPlaybackState();
        clearPartialPlaybook(sessionId);
      }

      // Starting from UI implies user reached this step; allow future auto-resume.
      markStepReached();
      onShowPlaybook?.();

      // OTP gate: store pending and let effect below resume once verified.
      if (!otpVerified) {
        pendingSidRef.current = sessionId;
        onRequestOtp?.();
        return;
      }

      const myRunId = ++runIdRef.current;
      let finished = false;
      const callbacks = {
        onEvent: (e) => {
          if (runIdRef.current !== myRunId) return;
          if (!e || typeof e !== 'object') return;
          if (e.stream_id) monitorTaskStreamStart({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: String(e.stream_id), sessionId: sessionId });
          monitorTaskStreamEvent({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, sessionId: sessionId, event: e });
          if (e.type === 'token' && e.token) {
            setPlaybookText((t) => {
              const next = t + String(e.token);
              savePartialPlaybook(sessionId, next);
              return next;
            });
          }
        },
        onDone: (e) => {
          if (runIdRef.current !== myRunId) return;
          finished = true;
          // Playbook is done — clear flag so auto-resume never re-triggers on next page load
          safeRemoveItem(STORAGE_PLAYBOOK_STEP_REACHED);
          clearPartialPlaybook(sessionId);
          setPlaybookStreaming(false);
          setPlaybookDone(true);
          setPlaybookResult({
            playbook: e.playbook || '',
            website_audit: e.website_audit || '',
            context_brief: e.context_brief || '',
            icp_card: e.icp_card || '',
          });
          monitorTaskStreamDone({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, sessionId: sessionId, event: e });
        },
        onError: (e) => {
          if (runIdRef.current !== myRunId) return;
          finished = true;
          setPlaybookStreaming(false);
          setPlaybookDone(false);
          setPlaybookResult(null);
          setNeedsManualRetry(true);
          setError?.(e?.message || 'Playbook generation failed');
          monitorTaskStreamError({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e?.stream_id, sessionId: sessionId, event: e });
        },
      };

      await runResumableTaskStream(TASK_TYPE_PLAYBOOK_GENERATE, {
        userId: null,
        sessionId: sessionId,
        payload: { session_id: sessionId },
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

  // Resume after refresh (localStorage has a stream_id) — needs session_id to resolve actor.
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
        // We store task streams for onboarding playbook under the session actor key:
        // runResumableTaskStream() starts with { sessionId: sid, userId: null }.
        const storedStreamId = getStoredTaskStreamId(TASK_TYPE_PLAYBOOK_GENERATE, { sessionId: sid, userId: null });
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
          sessionId: sid,
          payload: { session_id: sid },
          maxRetries: 4,
          shouldStop: () => runIdRef.current !== myRunId,
          callbacks: {
            onEvent: (e) => {
              if (runIdRef.current !== myRunId) return;
              if (!e || typeof e !== 'object') return;
              if (e.stream_id) monitorTaskStreamStart({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: String(e.stream_id), sessionId: sid });
              monitorTaskStreamEvent({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, sessionId: sid, event: e });
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
              clearPartialPlaybook(sid);
              setPlaybookStreaming(false);
              setPlaybookDone(true);
              setPlaybookResult({
                playbook: e.playbook || '',
                website_audit: e.website_audit || '',
                context_brief: e.context_brief || '',
                icp_card: e.icp_card || '',
              });
              monitorTaskStreamDone({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e.stream_id, sessionId: sid, event: e });
            },
            onError: (e) => {
              if (runIdRef.current !== myRunId) return;
              finished = true;
              setPlaybookStreaming(false);
              setPlaybookDone(false);
              setPlaybookResult(null);
              setNeedsManualRetry(true);
              setError?.(e?.message || 'Playbook generation failed');
              monitorTaskStreamError({ taskType: TASK_TYPE_PLAYBOOK_GENERATE, streamId: e?.stream_id, sessionId: sid, event: e });
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

