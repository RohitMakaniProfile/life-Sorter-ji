import { useCallback, useEffect, useRef, useState } from 'react';
import { runResumableTaskStream, getStoredTaskStreamId } from '../../../api/services/taskStream';
import { monitorTaskStreamStart, monitorTaskStreamEvent, monitorTaskStreamDone, monitorTaskStreamError } from '../../../api/services/taskStreamMonitor';

const TASK_TYPE_CRAWL = 'crawl';
const STORAGE_CRAWL_STEP_REACHED = 'life-sorter-crawl-step-reached';

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
  const [crawlDone, setCrawlDone] = useState(false);
  const [crawlResult, setCrawlResult] = useState(null);

  const runIdRef = useRef(0);
  const autoResumeTriggeredRef = useRef(false);
  /** Fresh flag for waitForCrawl — interval must read current state, not a stale closure. */
  const crawlStreamingRef = useRef(false);

  useEffect(() => {
    crawlStreamingRef.current = crawlStreaming;
  }, [crawlStreaming]);

  const startForSession = useCallback(
    async (sid, { websiteUrl } = {}) => {
      const sessionId = sid || (await ensureSession());
      const url = String(websiteUrl || '').trim();
      if (!sessionId) return;

      safeSetItem(STORAGE_CRAWL_STEP_REACHED, '1');
      setCrawlStreaming(true);
      setCrawlDone(false);
      setCrawlResult(null);
      setCrawlStage('starting');
      setCrawlLabel('Starting crawl');
      setCrawlProgress(null);

      const myRunId = ++runIdRef.current;
      let finished = false;

      await runResumableTaskStream(TASK_TYPE_CRAWL, {
        sessionId,
        payload: url && url !== '(resume)' ? { website_url: url } : {},
        maxRetries: 2,
        shouldStop: () => runIdRef.current !== myRunId,
        callbacks: {
          onEvent: (e) => {
            if (runIdRef.current !== myRunId) return;
            if (!e || typeof e !== "object") return;
            if (e.stream_id) monitorTaskStreamStart({ taskType: TASK_TYPE_CRAWL, streamId: String(e.stream_id), sessionId });
            monitorTaskStreamEvent({ taskType: TASK_TYPE_CRAWL, streamId: e.stream_id, sessionId, event: e });
            if (e.type === 'stage') {
              if (e.stage) setCrawlStage(String(e.stage));
              if (e.label) setCrawlLabel(String(e.label));
              if (e.phase || e.pages_found || e.pages_crawled || e.current_page) {
                setCrawlProgress({
                  phase: e.phase || e.stage || '',
                  pages_found: e.pages_found || 0,
                  pages_crawled: e.pages_crawled || 0,
                  current_page: e.current_page || '',
                });
              }
            }
          },
          onDone: (e) => {
            if (runIdRef.current !== myRunId) return;
            finished = true;
            setCrawlStreaming(false);
            setCrawlDone(true);
            setCrawlStage('done');
            setCrawlLabel('Done');
            setCrawlResult({ crawl_raw: e.crawl_raw, crawl_summary: e.crawl_summary });
            monitorTaskStreamDone({ taskType: TASK_TYPE_CRAWL, streamId: e.stream_id, sessionId, event: e });
          },
          onError: (e) => {
            if (runIdRef.current !== myRunId) return;
            finished = true;
            setCrawlStreaming(false);
            setCrawlDone(false);
            setCrawlStage('error');
            setCrawlLabel('Error');
            setCrawlResult(null);
            setError?.(e?.message || 'Crawl failed');
            monitorTaskStreamError({ taskType: TASK_TYPE_CRAWL, streamId: e?.stream_id, sessionId, event: e });
          },
        },
      });

      if (!finished && runIdRef.current === myRunId) {
        setCrawlStreaming(false);
        setCrawlDone(false);
        setCrawlStage('error');
        setCrawlLabel('Disconnected');
        setError?.('Crawl stream disconnected.');
      }
    },
    [ensureSession, setError],
  );

  const waitForCrawl = useCallback(() => {
    const POLL_MS = 250;
    const MAX_WAIT_MS = 180000;
    return new Promise((resolve) => {
      if (!crawlStreamingRef.current) {
        resolve();
        return;
      }
      const started = Date.now();
      const t = window.setInterval(() => {
        if (!crawlStreamingRef.current) {
          window.clearInterval(t);
          resolve();
          return;
        }
        if (Date.now() - started >= MAX_WAIT_MS) {
          window.clearInterval(t);
          console.warn('[crawl] waitForCrawl gave up after', MAX_WAIT_MS, 'ms; continuing to playbook');
          setError?.('Crawl is still running; opening playbook with data gathered so far.');
          resolve();
        }
      }, POLL_MS);
    });
  }, [setError]);

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
        const storedStreamId = getStoredTaskStreamId(TASK_TYPE_CRAWL, { sessionId: sid, userId: null });
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
    crawlDone,
    crawlResult,
    startForSession,
    waitForCrawl,
    taskType: TASK_TYPE_CRAWL,
  };
}

