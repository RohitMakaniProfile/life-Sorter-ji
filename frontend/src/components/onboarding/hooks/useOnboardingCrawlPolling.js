import { useState, useRef, useCallback, useEffect } from 'react';
import * as api from '../api';

export function useOnboardingCrawlPolling(sessionIdRef) {
  const [crawlStatus, setCrawlStatus] = useState('');
  const crawlPollRef = useRef(null);
  const crawlSummaryRef = useRef(null);

  const startCrawlPolling = useCallback(() => {
    if (crawlPollRef.current) clearInterval(crawlPollRef.current);
    crawlPollRef.current = setInterval(async () => {
      try {
        const sid = sessionIdRef.current;
        if (!sid) return;
        const data = await api.getCrawlStatus(sid);
        if (data.crawl_status === 'complete' || data.crawl_status === 'failed') {
          setCrawlStatus(data.crawl_status);
          clearInterval(crawlPollRef.current);
          crawlPollRef.current = null;
          if (data.crawl_status === 'complete' && data.crawl_summary) {
            crawlSummaryRef.current = data.crawl_summary;
          }
        }
      } catch {
        /* silent */
      }
    }, 3000);
  }, [sessionIdRef]);

  useEffect(
    () => () => {
      if (crawlPollRef.current) clearInterval(crawlPollRef.current);
    },
    []
  );

  const waitForCrawl = useCallback(
    () =>
      new Promise((resolve) => {
        if (!crawlPollRef.current) {
          resolve();
          return;
        }
        const check = setInterval(() => {
          if (!crawlPollRef.current) {
            clearInterval(check);
            resolve();
          }
        }, 500);
      }),
    []
  );

  return {
    crawlStatus,
    setCrawlStatus,
    crawlSummaryRef,
    startCrawlPolling,
    waitForCrawl,
  };
}
