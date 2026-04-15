import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Navbar from '../components/onboarding/components/Navbar';
import PlaybookStage from '../components/onboarding/stages/PlaybookStage';
import PlaybookViewer from '../components/PlaybookViewer';
import { getPlaybookStatus, coreApi } from '../api/services/core';
import { runResumableTaskStream } from '../api/services/taskStream';
import { getUserIdFromJwt } from '../api/authSession';

const TASK_TYPE_PLAYBOOK_GENERATE = 'playbook/onboarding-generate';

// ---------------------------------------------------------------------------
// Tiny hook that drives the task-stream lifecycle for a single onboarding ID.
// ---------------------------------------------------------------------------
function usePlaybookStream(onboardingId) {
  const [streaming, setStreaming] = useState(false);
  const [text, setText] = useState('');
  const [done, setDone] = useState(false);
  const [result, setResult] = useState(null);
  const [retryNeeded, setRetryNeeded] = useState(false);
  const runIdRef = useRef(0);

  const reset = useCallback(() => {
    setStreaming(true);
    setText('');
    setDone(false);
    setResult(null);
    setRetryNeeded(false);
  }, []);

  const run = useCallback(
    async ({ forceFresh = false } = {}) => {
      reset();
      const myRun = ++runIdRef.current;
      let finished = false;

      await runResumableTaskStream(TASK_TYPE_PLAYBOOK_GENERATE, {
        userId: null,
        onboardingId,
        payload: { onboarding_id: onboardingId },
        maxRetries: 4,
        forceFresh,
        shouldStop: () => runIdRef.current !== myRun,
        callbacks: {
          onEvent(e) {
            if (runIdRef.current !== myRun) return;
            if (e?.type === 'token' && e.token) {
              setText((t) => t + String(e.token));
            }
          },
          onDone(e) {
            if (runIdRef.current !== myRun) return;
            finished = true;
            setStreaming(false);
            setDone(true);
            setResult({
              playbook: e.playbook || '',
              website_audit: e.website_audit || '',
              context_brief: e.context_brief || '',
              icp_card: e.icp_card || '',
            });
          },
          onError(e) {
            if (runIdRef.current !== myRun) return;
            finished = true;
            setStreaming(false);
            setRetryNeeded(true);
          },
        },
      });

      if (!finished && runIdRef.current === myRun) {
        setStreaming(false);
        setRetryNeeded(true);
      }
    },
    [onboardingId, reset],
  );

  const stop = useCallback(() => {
    runIdRef.current++;
    setStreaming(false);
  }, []);

  return { streaming, text, done, result, retryNeeded, run, stop };
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function PlaybookPage() {
  const { onboardingId } = useParams();
  const navigate = useNavigate();

  // ── Page-level state ──────────────────────────────────────────────────────
  const [pageState, setPageState] = useState('loading'); // loading|not_found|gap_questions|streaming|complete|error
  const [pageError, setPageError] = useState(null);

  // ── Pre-loaded content (when playbook already complete) ────────────────
  const [completedContent, setCompletedContent] = useState(null);

  // ── Gap questions ─────────────────────────────────────────────────────────
  const [gapQuestions, setGapQuestions] = useState([]);
  const [gapAnswers, setGapAnswers] = useState({});
  const [gapCurrentIndex, setGapCurrentIndex] = useState(0);
  const [gapSavingIndex, setGapSavingIndex] = useState(null);

  // ── Streaming ─────────────────────────────────────────────────────────────
  const stream = usePlaybookStream(onboardingId);
  const initDoneRef = useRef(false);

  // ── Helpers ───────────────────────────────────────────────────────────────
  const launchAndStream = useCallback(
    async ({ forceFresh = true } = {}) => {
      setPageState('streaming');
      try {
        await coreApi.onboardingPlaybookLaunch({ onboarding_id: onboardingId });
      } catch {
        // If launch fails (e.g. already running), still try to connect to stream
      }
      await stream.run({ forceFresh });
    },
    [onboardingId, stream],
  );

  const resumeStream = useCallback(async () => {
    setPageState('streaming');
    await stream.run({ forceFresh: false });
  }, [stream]);

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (initDoneRef.current) return;
    initDoneRef.current = true;

    // Gate: must be logged in before calling any protected API
    if (!getUserIdFromJwt()) {
      window.location.href = `/phone-verify?next=${encodeURIComponent(`/playbook-view/${onboardingId}`)}&oid=${encodeURIComponent(onboardingId)}`;
      return;
    }

    const init = async () => {
      try {
        const data = await getPlaybookStatus(onboardingId);

        // Already complete with content
        if (data.playbook_status === 'complete' && data.content?.playbook) {
          setCompletedContent(data.content);
          setPageState('complete');
          return;
        }

        // Stream already running — just attach
        if (data.playbook_status === 'generating' || data.playbook_status === 'started') {
          await resumeStream();
          return;
        }

        // Gap questions outstanding
        if (data.playbook_status === 'awaiting_gap_answers') {
          try {
            const gapData = await coreApi.onboardingGapQuestionsStart({ onboarding_id: onboardingId });
            const questions = gapData.questions || [];
            if (questions.length > 0) {
              setGapQuestions(questions);
              // Restore any previously saved answers
              const savedMap = gapData.gap_answers_parsed || {};
              const indexed = {};
              Object.entries(savedMap).forEach(([k, v]) => {
                const idx = Number(String(k).replace(/^Q/i, '')) - 1;
                if (Number.isFinite(idx) && idx >= 0) indexed[idx] = String(v);
              });
              setGapAnswers(indexed);
              let next = 0;
              while (next < questions.length && indexed[next]) next++;
              setGapCurrentIndex(next);
              setPageState('gap_questions');
              return;
            }
          } catch {
            // fallthrough to launch
          }
        }

        // Check gap questions (fresh / error / ready / no status)
        try {
          const gapData = await coreApi.onboardingGapQuestionsStart({ onboarding_id: onboardingId });
          const questions = gapData.questions || [];
          if (questions.length > 0) {
            setGapQuestions(questions);
            setPageState('gap_questions');
            return;
          }
        } catch {
          // If gap questions check fails, proceed to launch
        }

        await launchAndStream();
      } catch (err) {
        const msg = String(err?.message || err || '');
        const status = msg.match(/\b(401|403)\b/)?.[1];
        if (status === '401' || msg.toLowerCase().includes('authentication required')) {
          // Token expired or invalid — send to phone-verify
          window.location.href = `/phone-verify?next=${encodeURIComponent(`/playbook-view/${onboardingId}`)}&oid=${encodeURIComponent(onboardingId)}`;
          return;
        }
        if (status === '403' || msg.toLowerCase().includes('access denied')) {
          setPageError('You do not have permission to view this playbook.');
          setPageState('error');
          return;
        }
        if (msg.includes('404') || msg.toLowerCase().includes('not found')) {
          setPageState('not_found');
        } else {
          setPageError(msg || 'Failed to load playbook.');
          setPageState('error');
        }
      }
    };

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onboardingId]);

  // When stream finishes, move to complete state
  useEffect(() => {
    if (stream.done && pageState === 'streaming') {
      setPageState('complete');
    }
  }, [stream.done, pageState]);

  // ── Gap question handler ──────────────────────────────────────────────────
  const handleGapAnswer = useCallback(
    async (index, answerKey, answerText) => {
      setGapSavingIndex(index);
      try {
        await coreApi.onboardingPlaybookMcqAnswer({
          onboarding_id: onboardingId,
          question_index: index,
          answer_key: answerKey,
          answer_text: answerText,
        });
        setGapAnswers((prev) => ({ ...prev, [index]: answerKey }));
        const next = index + 1;
        if (next >= gapQuestions.length) {
          await launchAndStream();
        } else {
          setGapCurrentIndex(next);
        }
      } catch {
        setPageError('Failed to save answer.');
      } finally {
        setGapSavingIndex(null);
      }
    },
    [onboardingId, gapQuestions.length, launchAndStream],
  );

  const handleRetry = useCallback(() => {
    launchAndStream({ forceFresh: true });
  }, [launchAndStream]);

  const handleGoHome = useCallback(() => {
    window.location.href = '/?reset=1';
  }, []);

  const handleDeepAnalysis = useCallback(() => {
    navigate('/payment');
  }, [navigate]);

  // ── Render ────────────────────────────────────────────────────────────────
  const wrapPage = (children) => (
    <div className="flex h-screen max-h-screen flex-col overflow-hidden bg-[#111] font-sans text-white">
      <Navbar />
      {children}
    </div>
  );

  if (pageState === 'loading') {
    return wrapPage(
      <div className="flex flex-1 items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-violet-500" />
          <p className="text-sm text-white/50">Loading your playbook…</p>
        </div>
      </div>,
    );
  }

  if (pageState === 'not_found') {
    return wrapPage(
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 text-center">
        <div className="text-5xl">📭</div>
        <h2 className="text-xl font-bold text-white">Playbook Not Found</h2>
        <p className="max-w-sm text-sm text-white/50">
          We couldn't find a playbook for this ID. It may have expired or the link is invalid.
        </p>
        <button
          type="button"
          onClick={handleGoHome}
          className="mt-2 cursor-pointer rounded-xl border border-white/15 bg-white/[0.05] px-6 py-2.5 text-sm font-semibold text-white/70 transition hover:text-white"
        >
          Start New Journey
        </button>
      </div>,
    );
  }

  if (pageState === 'error') {
    return wrapPage(
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 text-center">
        <div className="text-5xl">⚠️</div>
        <h2 className="text-xl font-bold text-white">Something went wrong</h2>
        <p className="max-w-sm text-sm text-red-400/80">{pageError}</p>
        <button
          type="button"
          onClick={handleRetry}
          className="mt-2 cursor-pointer rounded-xl bg-gradient-to-r from-[#857BFF] to-[#BF69A2] px-6 py-2.5 text-sm font-bold text-white"
        >
          Retry
        </button>
        <button type="button" onClick={handleGoHome} className="text-sm text-white/40 hover:text-white/70">
          Start New Journey
        </button>
      </div>,
    );
  }

  // Complete — show full playbook
  if (pageState === 'complete') {
    const content = completedContent || {
      playbook: stream.result?.playbook || '',
      website_audit: stream.result?.website_audit || '',
      context_brief: stream.result?.context_brief || '',
      icp_card: stream.result?.icp_card || '',
    };

    return wrapPage(
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-8 py-6">
        <h1 className="m-0 mb-5 text-center text-[clamp(20px,2.5vw,32px)] font-extrabold text-white">
          Your Playbook
        </h1>
        <div className="mx-auto w-full max-w-[800px] flex-1 overflow-auto">
          <div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-4 shadow-sm">
            <PlaybookViewer
              initialPhase="playbook"
              themeMode="dark"
              playbookData={{
                playbook: content.playbook,
                websiteAudit: content.website_audit,
                contextBrief: content.context_brief,
                icpCard: content.icp_card,
              }}
            />
          </div>
          <div className="flex flex-row gap-4">
            <button
              type="button"
              onClick={handleDeepAnalysis}
              className="w-full cursor-pointer rounded-[10px] border-none bg-gradient-to-br from-indigo-500 to-violet-500 py-3 px-8 text-[15px] font-bold text-white"
            >
              Do Deep Analysis →
            </button>
            <button
              type="button"
              onClick={handleGoHome}
              className="w-full cursor-pointer rounded-[10px] border border-white/15 bg-transparent py-2.5 px-8 text-[14px] font-semibold text-white/50 transition hover:text-white/80"
            >
              Start New Journey
            </button>
          </div>
        </div>
      </div>,
    );
  }

  // gap_questions | streaming states — reuse PlaybookStage
  return wrapPage(
    <PlaybookStage
      showGapQuestions={pageState === 'gap_questions'}
      gapQuestions={gapQuestions}
      gapAnswers={gapAnswers}
      gapCurrentIndex={gapCurrentIndex}
      gapSavingIndex={gapSavingIndex}
      onGapAnswer={handleGapAnswer}
      playbookStreaming={stream.streaming}
      playbookText={stream.text}
      playbookDone={stream.done}
      playbookResult={stream.result}
      onDeepAnalysis={handleDeepAnalysis}
      onGoHome={handleGoHome}
      showRetry={stream.retryNeeded && !stream.streaming && !stream.done}
      onRetry={handleRetry}
      retryLabel="Retry Playbook"
      onRetryPlaybook={handleRetry}
      onCancel={handleGoHome}
    />,
  );
}

