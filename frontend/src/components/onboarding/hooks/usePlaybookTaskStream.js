import { useCallback, useEffect, useRef, useState } from 'react';
import { runResumableTaskStream, getStoredTaskStreamId } from '../../../api/services/taskStream';
import { monitorTaskStreamStart, monitorTaskStreamEvent, monitorTaskStreamDone, monitorTaskStreamError } from '../../../api/services/taskStreamMonitor';
import { getUserIdFromJwt } from '../../../api/authSession';

const TASK_TYPE_PLAYBOOK_GENERATE = 'playbook/onboarding-generate';
const STORAGE_PLAYBOOK_STEP_REACHED = 'life-sorter-playbook-step-reached';

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
      const sessionId = sid;
      if (!sessionId) return;

      if (!fresh) {
        // Keep current UI state, but make sure streaming indicator is on.
        setPlaybookStreaming(true);
      } else {
        resetPlaybackState();
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
            setPlaybookText((t) => t + String(e.token));
          }
        },
        onDone: (e) => {
          if (runIdRef.current !== myRunId) return;
          finished = true;
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
        const actorUserId = getUserIdFromJwt();

        autoResumeTriggeredRef.current = true;
        const storedStreamId = getStoredTaskStreamId(TASK_TYPE_PLAYBOOK_GENERATE, { sessionId: null, userId: actorUserId });
        if (!storedStreamId) return;

        // Auto-attach without status polling. If stale/expired, the attach will error and we'll ignore it.
        onShowPlaybook?.();

        setPlaybookStreaming(true);
        setPlaybookText('');
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
              if (e.type === 'token' && e.token) setPlaybookText((t) => t + String(e.token));
            },
            onDone: (e) => {
              if (runIdRef.current !== myRunId) return;
              finished = true;
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
  };
}

