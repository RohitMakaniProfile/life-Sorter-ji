import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Navbar from '../components/onboarding/components/Navbar';
import PlaybookStage from '../components/onboarding/stages/PlaybookStage';
import { getPlaybookStatus } from '../api/index';
import { runResumableTaskStream } from '../api/index';
import { DOMAIN_TASKS } from '../components/onboarding/onboardingJourneyData';
import { useDeepAnalysis } from '../components/onboarding/hooks/useDeepAnalysis';

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
          onError(_e) {
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

  // ── Page-level state ──────────────────────────────────────────────────────
  const [pageState, setPageState] = useState('loading'); // loading|not_found|streaming|complete|error
  const [pageError, setPageError] = useState(null);

  // ── Pre-loaded content (when playbook already complete) ────────────────
  const [completedContent, setCompletedContent] = useState(null);
  const [completedTask, setCompletedTask] = useState('');
  const [completedDomain, setCompletedDomain] = useState('');
  const [websiteUrl, setWebsiteUrl] = useState('');

  const { handleDeepAnalysis } = useDeepAnalysis({
    getWebsiteUrl: useCallback(() => websiteUrl, [websiteUrl]),
    setError: setPageError,
  });

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


    const init = async () => {
      try {
        const data = await getPlaybookStatus(onboardingId);

        if (data.domain) setCompletedDomain(data.domain);
        if (data.task) setCompletedTask(data.task);
        else if (data.domain) setCompletedTask(data.domain);
        if (data.website_url) setWebsiteUrl(data.website_url);

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

        await launchAndStream();
      } catch (err) {
        const msg = String(err?.message || err || '');
        const status = msg.match(/\b(401|403)\b/)?.[1];
        if (status === '401' || msg.toLowerCase().includes('authentication required')) {
          // Not authenticated — load empty complete state; OTP gate will unlock tab 3
          setPageState('complete');
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

  const handleRetry = useCallback(() => {
    launchAndStream({ forceFresh: true });
  }, [launchAndStream]);

  const handleGoHome = useCallback(() => {
    window.location.href = '/?reset=1';
  }, []);

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
    const playbookText = completedContent?.playbook || stream.result?.playbook || '';

    // Derive task label: API value first, then extract from playbook H1
    const taskLabel = (() => {
      if (completedTask) return completedTask;
      const m = playbookText.match(/^#\s+The\s+"([^"]+)"\s+Playbook/im)
        || playbookText.match(/^#\s+The\s+([^#\n]+?)\s+Playbook/im);
      return m ? m[1].trim() : null;
    })();

    // Derive domain: use saved value, or reverse-lookup from DOMAIN_TASKS by task
    const effectiveDomain = completedDomain || (() => {
      if (!completedTask) return '';
      const entry = Object.entries(DOMAIN_TASKS).find(([, tasks]) => tasks.includes(completedTask));
      return entry ? entry[0] : '';
    })();

    return wrapPage(
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {/* ── Task header bar ── */}
        <div style={{
          flexShrink: 0,
          padding: '12px 24px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 6,
        }}>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: '.12em',
            textTransform: 'uppercase', color: '#475569',
          }}>
            Your Playbook
          </span>
          {taskLabel && (
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '5px 16px',
              background: 'rgba(139,92,246,0.10)',
              border: '1px solid rgba(139,92,246,0.22)',
              borderRadius: 999,
              maxWidth: '80%',
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8b5cf6', flexShrink: 0 }} />
              <span style={{
                fontSize: 13, fontWeight: 600, color: '#c4b5fd',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {taskLabel}
              </span>
            </div>
          )}
        </div>

        {/* ── Scrollable playbook ── */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-8 py-6">
          <div className="mx-auto w-full max-w-[720px] flex-1 overflow-auto">
            <div className="rounded-2xl border border-white/[0.07] bg-[#111318] px-6 py-7">
              <div className="playbook-markdown leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{playbookText}</ReactMarkdown>
              </div>
            </div>

            {/* ── Other tasks in this domain ── */}
            {effectiveDomain && DOMAIN_TASKS[effectiveDomain]?.length > 0 && (
              <div className="mt-6">
                <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', color: '#475569', marginBottom: 10 }}>
                  Other {effectiveDomain} tasks
                </div>
                <div style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                  {DOMAIN_TASKS[effectiveDomain]
                    .filter((t) => t !== completedTask)
                    .map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => { window.location.href = `/?task=${encodeURIComponent(t)}&domain=${encodeURIComponent(effectiveDomain)}`; }}
                        style={{
                          cursor: 'pointer',
                          border: '1px solid rgba(255,255,255,0.10)',
                          borderRadius: 10,
                          background: 'rgba(255,255,255,0.04)',
                          padding: '8px 14px',
                          fontSize: 12,
                          fontWeight: 500,
                          color: 'rgba(255,255,255,0.60)',
                          transition: 'all 0.15s',
                          textAlign: 'left',
                          lineHeight: 1.35,
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(139,92,246,0.12)'; e.currentTarget.style.borderColor = 'rgba(139,92,246,0.35)'; e.currentTarget.style.color = '#c4b5fd'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.10)'; e.currentTarget.style.color = 'rgba(255,255,255,0.60)'; }}
                      >
                        {t}
                      </button>
                    ))}
                </div>
              </div>
            )}

            <div className="mt-5 flex flex-row gap-4">
              <button
                type="button"
                onClick={handleGoHome}
                className="w-full cursor-pointer rounded-[10px] border border-white/15 bg-transparent py-2.5 px-8 text-[14px] font-semibold text-white/50 transition hover:text-white/80"
              >
                Start New Journey
              </button>
              <button
                type="button"
                onClick={handleDeepAnalysis}
                className="w-full cursor-pointer rounded-[10px] border-none bg-gradient-to-r from-[#6366f1] to-[#8b5cf6] py-2.5 px-8 text-[14px] font-bold text-white shadow-lg shadow-violet-500/20 transition hover:shadow-violet-500/35"
              >
                Do Deep Analysis
              </button>
            </div>
          </div>
        </div>
      </div>,
    );
  }

  // streaming state — render PlaybookStage
  return wrapPage(
    <PlaybookStage
      task={completedTask}
      playbookStreaming={stream.streaming}
      playbookText={stream.text}
      playbookDone={stream.done}
      playbookResult={stream.result}
      onGoHome={handleGoHome}
      showRetry={stream.retryNeeded && !stream.streaming && !stream.done}
      onRetry={handleRetry}
      retryLabel="Retry Playbook"
      onRetryPlaybook={handleRetry}
      onCancel={handleGoHome}
    />,
  );
}

