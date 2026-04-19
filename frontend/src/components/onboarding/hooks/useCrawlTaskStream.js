import { useCallback, useEffect, useRef, useState, useLayoutEffect } from 'react';
import { runResumableTaskStream, getStoredTaskStreamId } from '../../../api/services/taskStream';
import { monitorTaskStreamStart, monitorTaskStreamEvent, monitorTaskStreamDone, monitorTaskStreamError, extractErrorMessage } from '../../../api/services/taskStreamMonitor';

const TASK_TYPE_CRAWL = 'crawl';
const STORAGE_CRAWL_STEP_REACHED = 'doable-claw-crawl-step-reached';

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

function hasCrawlStepReached() {
  return safeGetItem(STORAGE_CRAWL_STEP_REACHED) === '1';
}

export function useCrawlTaskStream({ ensureSession, setError }) {
  const [crawlStreaming, setCrawlStreaming] = useState(false);
  const [crawlStage, setCrawlStage] = useState('');
  const [crawlLabel, setCrawlLabel] = useState('');
  const [crawlProgress, setCrawlProgress] = useState(null);
  const [crawlProgressEvents, setCrawlProgressEvents] = useState([]);
  const [crawlDone, setCrawlDone] = useState(false);
  const [crawlResult, setCrawlResult] = useState(null);

  const runIdRef = useRef(0);
  const autoResumeTriggeredRef = useRef(false);

  // Refs that always hold the latest state — used inside setInterval callbacks
  // to avoid stale closures in waitForCrawlDone / waitForCrawl.
  const crawlDoneRef = useRef(false);
  const crawlStageRef = useRef('');
  const crawlStreamingRef = useRef(false);
  useLayoutEffect(() => { crawlDoneRef.current = crawlDone; }, [crawlDone]);
  useLayoutEffect(() => { crawlStageRef.current = crawlStage; }, [crawlStage]);
  useLayoutEffect(() => { crawlStreamingRef.current = crawlStreaming; }, [crawlStreaming]);

  const startForSession = useCallback(
    async (sid, { websiteUrl, forceFresh = false } = {}) => {
      const onboardingId = sid || (await ensureSession());
      const url = String(websiteUrl || '').trim();
      if (!onboardingId) return;

      // If we have a new URL (not resume), force a fresh crawl
      const shouldForceFresh = forceFresh || (url && url !== '(resume)');

      safeSetItem(STORAGE_CRAWL_STEP_REACHED, '1');
      setCrawlStreaming(true);
      setCrawlDone(false);
      setCrawlResult(null);
      setCrawlStage('starting');
      setCrawlLabel('Starting crawl');
      setCrawlProgress(null);
      setCrawlProgressEvents([]);

      const myRunId = ++runIdRef.current;
      let finished = false;

      await runResumableTaskStream(TASK_TYPE_CRAWL, {
        onboardingId,
        payload: url && url !== '(resume)' ? { website_url: url } : {},
        maxRetries: 2,
        forceFresh: shouldForceFresh,
        shouldStop: () => runIdRef.current !== myRunId,
        callbacks: {
          onEvent: (e) => {
            // 🛑 Ignore stale runs
            if (runIdRef.current !== myRunId) return;

            // 🛑 Validate event
            if (!e || typeof e !== "object") return;

            const streamId = e.stream_id ? String(e.stream_id) : undefined;

            // 📡 Track stream start
            if (streamId) {
              monitorTaskStreamStart({
                taskType: TASK_TYPE_CRAWL,
                streamId,
                onboardingId,
              });
            }

            // 📊 Log raw event
            monitorTaskStreamEvent({
              taskType: TASK_TYPE_CRAWL,
              streamId,
              onboardingId,
              event: e,
            });

            // 🚫 Ignore ping events (keep-alive)
            if (e.type === "ping") return;

            // =========================
            // 🔷 STAGE EVENTS (MAIN FLOW)
            // =========================
            if (e.type === "stage") {
              const stage = e.stage ? String(e.stage) : undefined;
              const label = e.label ? String(e.label) : undefined;

              // 🧭 Update stage + label
              if (stage) setCrawlStage(stage);
              if (label) setCrawlLabel(label);

              // 📈 Progress update (preserve previous values)
              setCrawlProgress((prev) => ({
                phase: e.phase || stage || prev?.phase || "",
                pages_found: e.pages_found ?? prev?.pages_found ?? 0,
                pages_crawled: e.pages_crawled ?? prev?.pages_crawled ?? 0,
                current_page: e.current_page ?? prev?.current_page ?? "",
              }));

              // 📝 Log stage event
              setCrawlProgressEvents((prev) => [
                ...prev,
                {
                  stage: stage || "unknown",
                  type: "stage",
                  message: label || "",
                  meta: e,
                },
              ]);

              // 🌐 If current_page exists → treat as URL event
              if (e.current_page) {
                setCrawlProgressEvents((prev) => [
                  ...prev,
                  {
                    stage: stage || "scraping",
                    type: "url",
                    message: `Processing: ${e.current_page}`,
                    meta: { url: String(e.current_page) },
                  },
                ]);
              }

              return;
            }

            // =========================
            // 🔷 URL EVENTS (RARE / OPTIONAL)
            // =========================
            if (e.type === "url" && e.url) {
              setCrawlProgressEvents((prev) => [
                ...prev,
                {
                  stage: "scraping",
                  type: "url",
                  message: `${e.event || "Visited"}: ${e.url}`,
                  meta: {
                    event: String(e.event || ""),
                    url: String(e.url),
                  },
                },
              ]);

              // also update current page
              setCrawlProgress((prev) => ({
                ...prev,
                current_page: String(e.url),
              }));

              return;
            }

            // =========================
            // 🔷 FALLBACK (UNKNOWN EVENTS)
            // =========================
            setCrawlProgressEvents((prev) => [
              ...prev,
              {
                stage: "unknown",
                type: e.type || "unknown",
                message: JSON.stringify(e),
                meta: e,
              },
            ]);
          },
          onDone: (e) => {
            if (runIdRef.current !== myRunId) return;
            finished = true;
            setCrawlStreaming(false);
            setCrawlDone(true);
            setCrawlStage('done');
            setCrawlLabel('Done');
            setCrawlResult({ web_summary: e.web_summary, rca_questions: e.rca_questions ?? [] });
            monitorTaskStreamDone({ taskType: TASK_TYPE_CRAWL, streamId: e.stream_id, onboardingId, event: e });
          },
          onError: (e) => {
            if (runIdRef.current !== myRunId) return;
            finished = true;
            setCrawlStreaming(false);
            setCrawlDone(false);
            setCrawlStage('error');
            setCrawlLabel('Error');
            setCrawlResult(null);
            const errMsg = extractErrorMessage(e);
            setError?.(errMsg);
            monitorTaskStreamError({ taskType: TASK_TYPE_CRAWL, streamId: e?.stream_id, onboardingId, event: e });
          },
        },
      });

      if (!finished && runIdRef.current === myRunId) {
        setCrawlStreaming(false);
        setCrawlDone(false);
        setCrawlStage('error');
        setCrawlLabel('Disconnected');
        setError?.('Crawl stream disconnected unexpectedly.');
      }
    },
    [ensureSession, setError],
  );

  // Wait until the crawl stream ends for any reason — done, error, or disconnect.
  // Resolves true if crawl completed successfully, false otherwise.
  // No fixed timeout: resolves as soon as streaming stops so the caller never
  // waits longer than the crawl actually takes.
  // A large absolute safety timeout (10 min) guards against a stuck stream.
  const waitForCrawlDone = useCallback(
    () =>
      new Promise((resolve) => {
        // Already resolved states
        if (crawlDoneRef.current) { resolve(true); return; }
        if (!crawlStreamingRef.current) { resolve(false); return; }

        const deadline = setTimeout(() => resolve(false), 600000); // 10-min absolute safety
        const t = window.setInterval(() => {
          if (crawlDoneRef.current) {
            window.clearInterval(t);
            clearTimeout(deadline);
            resolve(true);
          } else if (!crawlStreamingRef.current) {
            // Stream ended (error / disconnect) without setting done
            window.clearInterval(t);
            clearTimeout(deadline);
            resolve(false);
          }
        }, 300);
      }),
    [], // stable — reads live values via refs
  );

  // Legacy alias — resolves as soon as streaming stops (done or error).
  const waitForCrawl = useCallback(
    (timeoutMs = 8000) =>
      new Promise((resolve) => {
        if (!crawlStreamingRef.current) {
          resolve();
          return;
        }
        const deadline = setTimeout(resolve, timeoutMs);
        const t = window.setInterval(() => {
          if (!crawlStreamingRef.current) {
            window.clearInterval(t);
            clearTimeout(deadline);
            resolve();
          }
        }, 250);
      }),
    [], // stable — reads live values via refs
  );

  // Auto-resume after refresh if the user already triggered crawl.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (autoResumeTriggeredRef.current) return;
        if (!hasCrawlStepReached()) return;
        const sid = await ensureSession();
        if (cancelled || !sid) return;

        autoResumeTriggeredRef.current = true;
        const storedStreamId = getStoredTaskStreamId(TASK_TYPE_CRAWL, { onboardingId: sid, userId: null });
        if (!storedStreamId) return;

        // Auto-attach without status polling. If stale/expired, attach will error and we'll ignore it.
        startForSession(sid, { websiteUrl: '(resume)' }).catch(() => {});
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ensureSession, startForSession]);

  return {
    crawlStreaming,
    crawlStage,
    crawlLabel,
    crawlProgress,
    crawlProgressEvents,
    crawlDone,
    crawlResult,
    startForSession,
    waitForCrawl,
    waitForCrawlDone,
    taskType: TASK_TYPE_CRAWL,
  };
}
