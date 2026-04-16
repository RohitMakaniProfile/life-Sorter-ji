import { useCallback } from 'react';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { streamWebsiteAudit } from '../../../api/services/core';
import { mapToolsToEarlyTools } from '../toolService';
import { toRectObj, TASK_KEY_SEP, buildOnboardingPatch } from '../utils/onboardingUtils';
import STATIC_SCALE_QUESTIONS from '../data/scale_questions.json';
import { buildScaleQuestions } from '../utils/scaleQuestions';

const rcaNextQuestion = (body) => apiPost(API_ROUTES.onboarding.rcaNextQuestion, body ?? {});

/**
 * All onboarding flow handlers/actions consolidated.
 * Takes state + setters from useOnboardingFlowState and returns handler functions.
 */
export function useOnboardingHandlers({
  // Session
  onboardingIdRef,
  ensureSession,
  updateOnboarding,
  clearSession,

  // State
  state,

  // Playbook streaming
  playbook,

  // Crawl streaming
  crawl,

  // Callbacks
  scrollToEnd,
  clearOnboardingClientStorage,
}) {
  const {
    selectedOutcome, setSelectedOutcome,
    selectedDomain, setSelectedDomain,
    setSelectedTask,
    setShowUrlForm,
    setToolPage,
    urlValue, setUrlValue,
    gbpValue, setGbpValue,
    setUrlSubmitting,
    earlyTools, setEarlyTools,
    setShowDeeperDive,
    setScaleQuestions,
    scaleAnswers, setScaleAnswers,
    setShowDiagnostic,
    setCurrentQuestion,
    setQuestionIndex,
    loading, setLoading,
    setShowTransitionMessages,
    setShowAnalysisTransition,
    setRcaCalling,
    setShowWebsiteAudit,
    setWebsiteAuditText,
    setWebsiteAuditLoading,
    setShowComplete,
    setError,
    otpVerified,
    pendingTaskNodeTransitionRef,
    taskToolsCacheRef,
    setTaskNodeTransition,
    resetAll,
    clearPostTask,
    clearError,
  } = state;

  const {
    clearStepReached,
    clearResumeArtifacts,
  } = playbook;

  const {
    startForSession: startCrawlForSession,
    waitForCrawlDone,
  } = crawl;

  // Scroll helper
  const scheduleScrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollToEnd());
    });
  }, [scrollToEnd]);

  // Shared: start streaming the website audit for a session
  const startWebsiteAuditStream = useCallback((sid) => {
    setShowAnalysisTransition(false);
    setWebsiteAuditText('');
    setWebsiteAuditLoading(true);
    setShowWebsiteAudit(true);
    streamWebsiteAudit(sid, {
      onToken: (token) => setWebsiteAuditText((prev) => prev + token),
      onDone: (full) => { setWebsiteAuditText(full); setWebsiteAuditLoading(false); },
      onError: () => { setWebsiteAuditText(''); setWebsiteAuditLoading(false); },
    }).catch(() => setWebsiteAuditLoading(false));
  }, [setWebsiteAuditText, setWebsiteAuditLoading, setShowWebsiteAudit, setShowAnalysisTransition]);

  // Start new journey
  const startNewJourney = useCallback(() => {
    clearStepReached();
    clearResumeArtifacts();
    clearSession();
    resetAll();
    clearOnboardingClientStorage();
    window.location.href = '/?reset=1';
  }, [clearStepReached, clearResumeArtifacts, clearSession, resetAll, clearOnboardingClientStorage]);

  // Onboarding field update
  const handleOnboardingFieldUpdate = useCallback(
    async (fields, ui = {}) => {
      const { nextOutcome, nextDomain, nextTask, clearPostTaskStages, openUrlForm, toolContext } = ui;

      if (nextOutcome !== undefined) setSelectedOutcome(nextOutcome);
      if (nextDomain !== undefined) setSelectedDomain(nextDomain);
      if (nextTask !== undefined) setSelectedTask(nextTask);
      if (clearPostTaskStages) clearPostTask();

      if (openUrlForm) {
        const pending = pendingTaskNodeTransitionRef.current;
        if (pending) {
          const rawKey = `${pending.domain}${TASK_KEY_SEP}${pending.task}`;
          const safeKey = typeof window !== 'undefined' && window.CSS?.escape
            ? window.CSS.escape(rawKey)
            : rawKey.replace(/"/g, '\\"');
          const anchorEl = document.querySelector(`[data-journey-anchor="task"][data-journey-key="${safeKey}"]`);
          const fromRect = anchorEl?.getBoundingClientRect?.();
          if (fromRect && fromRect.width > 0 && fromRect.height > 0) {
            setTaskNodeTransition({ fromRect: toRectObj(fromRect), toRect: null, phase: 'enter', label: pending.task });
          }
          pendingTaskNodeTransitionRef.current = null;
        }
        setShowUrlForm(true);
        setShowDeeperDive(false);
        setShowDiagnostic(false);
        setShowComplete(false);
        setToolPage(0);
      }

      if (toolContext) {
        const cacheKey = `${toolContext.outcomeId}|||${toolContext.domain}|||${toolContext.task}`;
        const cached = taskToolsCacheRef.current.get(cacheKey);
        if (cached) {
          setEarlyTools(mapToolsToEarlyTools(cached));
        } else {
          const res = await apiPost(API_ROUTES.onboarding.toolsByQ1Q2Q3, {
            outcome: toolContext.outcomeId,
            domain: toolContext.domain,
            task: toolContext.task,
          });
          const tools = res?.tools || [];
          taskToolsCacheRef.current.set(cacheKey, tools);
          setEarlyTools(mapToolsToEarlyTools(tools));
        }
      }

      scheduleScrollToEnd();
      const patch = buildOnboardingPatch(fields);
      if (Object.keys(patch).length === 0) return;
      try {
        await updateOnboarding(patch);
      } catch (err) {
        console.warn('Onboarding update:', err?.message || err);
      }
    },
    [updateOnboarding, scheduleScrollToEnd, clearPostTask, setSelectedOutcome, setSelectedDomain, setSelectedTask, setShowUrlForm, setShowDeeperDive, setShowDiagnostic, setShowComplete, setToolPage, setEarlyTools, setTaskNodeTransition, pendingTaskNodeTransitionRef, taskToolsCacheRef],
  );

  // Journey clicks
  const handleOutcomeClick = useCallback((outcome) => {
    handleOnboardingFieldUpdate(
      { outcome: outcome.id, domain: null, task: null },
      { nextOutcome: outcome, nextDomain: null, nextTask: null, clearPostTaskStages: true },
    );
  }, [handleOnboardingFieldUpdate]);

  const handleDomainClick = useCallback((domain, previewOutcome) => {
    handleOnboardingFieldUpdate(
      previewOutcome ? { outcome: previewOutcome.id, domain, task: null } : { domain, task: null },
      { ...(previewOutcome ? { nextOutcome: previewOutcome } : {}), nextDomain: domain, nextTask: null, clearPostTaskStages: true },
    );
  }, [handleOnboardingFieldUpdate]);

  const handleTaskClick = useCallback((task, previewOutcome, previewDomain) => {
    const effectiveOutcome = selectedOutcome ?? previewOutcome;
    const effectiveDomain = selectedDomain ?? previewDomain;
    if (!effectiveOutcome || !effectiveDomain) return;
    pendingTaskNodeTransitionRef.current = { domain: effectiveDomain, task };
    const fields = { task };
    if (previewOutcome) fields.outcome = previewOutcome.id;
    if (previewDomain) fields.domain = previewDomain;
    handleOnboardingFieldUpdate(fields, {
      ...(previewOutcome ? { nextOutcome: previewOutcome } : {}),
      ...(previewDomain != null ? { nextDomain: previewDomain } : {}),
      nextTask: task,
      clearPostTaskStages: true,
      openUrlForm: true,
      toolContext: { outcomeId: effectiveOutcome.id, domain: effectiveDomain, task },
    });
  }, [selectedOutcome, selectedDomain, handleOnboardingFieldUpdate, pendingTaskNodeTransitionRef]);

  // URL handlers
  const moveToScaleQuestions = useCallback(async () => {
    setScaleQuestions(buildScaleQuestions(earlyTools));
    setShowDeeperDive(true);
    setTimeout(scrollToEnd, 50);
  }, [setScaleQuestions, setShowDeeperDive, scrollToEnd, earlyTools]);

  const handleUrlSubmit = useCallback(async (e) => {
    e.preventDefault();
    if (!urlValue.trim() && !gbpValue.trim()) return;
    setUrlSubmitting(true);
    try {
      const web = urlValue.trim();
      const gbp = gbpValue.trim();
      if (web || gbp) {
        const patch = {};
        if (web) patch.website_url = web;
        if (gbp) patch.gbp_url = gbp;
        await handleOnboardingFieldUpdate({ ...patch });
        const sid = onboardingIdRef.current || (await ensureSession());
        if (web && sid) startCrawlForSession(sid, { websiteUrl: web }).catch(() => {});
      }
      await moveToScaleQuestions();
    } catch {
      setError('Failed to submit URL.');
    } finally {
      setUrlSubmitting(false);
    }
  }, [urlValue, gbpValue, handleOnboardingFieldUpdate, onboardingIdRef, ensureSession, startCrawlForSession, moveToScaleQuestions, setUrlSubmitting, setError]);

  const handleUrlSkip = useCallback(async () => {
    setUrlSubmitting(true);
    await moveToScaleQuestions();
    setUrlSubmitting(false);
  }, [moveToScaleQuestions, setUrlSubmitting]);

  // Scale handlers
  const handleScaleSelect = useCallback((qId, option, multiSelect) => {
    setScaleAnswers((prev) => {
      if (multiSelect) {
        const cur = prev[qId] || [];
        return { ...prev, [qId]: cur.includes(option) ? cur.filter((o) => o !== option) : [...cur, option] };
      }
      return { ...prev, [qId]: option };
    });
  }, [setScaleAnswers]);

  // Playbook handlers — now just redirect to the dedicated PlaybookPage
  const handleStartPlaybook = useCallback(async ({ forceVerified = false } = {}) => {
    const oid = onboardingIdRef.current || (await ensureSession());
    if (!oid) return;

    if (!forceVerified && !otpVerified) {
      window.location.href = `/phone-verify?next=${encodeURIComponent(`/playbook-view/${oid}`)}&oid=${encodeURIComponent(oid)}`;
      return;
    }

    window.location.href = `/playbook-view/${oid}`;
  }, [otpVerified, onboardingIdRef, ensureSession]);

  const handleTransitionComplete = useCallback(() => {
    setShowTransitionMessages(false);
    setTimeout(scrollToEnd, 50);
  }, [setShowTransitionMessages, scrollToEnd]);

  const handleGapAnswer = useCallback(async () => {
    // Gap questions are now handled on the dedicated PlaybookPage.
    // This handler is kept as a no-op for compatibility.
  }, []);

  // Scale submit
  const handleScaleSubmit = useCallback(async () => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      const byId = {};
      for (let i = 0; i < STATIC_SCALE_QUESTIONS.length; i += 1) {
        const q = STATIC_SCALE_QUESTIONS[i];
        const v = scaleAnswers[i];
        if (v == null || (Array.isArray(v) && v.length === 0)) continue;
        byId[q.id] = v;
      }
      await handleOnboardingFieldUpdate({ scale_answers: byId });

      setShowAnalysisTransition(true);
      setShowDeeperDive(false);
      await waitForCrawlDone(90000);

      // Website audit comes before RCA — start it now
      startWebsiteAuditStream(sid);
    } catch {
      setShowAnalysisTransition(false);
      setError('Failed to start analysis.');
    } finally {
      setLoading(false);
    }
  }, [ensureSession, scaleAnswers, handleOnboardingFieldUpdate, waitForCrawlDone, startWebsiteAuditStream, setLoading, setShowAnalysisTransition, setShowDeeperDive, setError]);

  // Diagnostic handlers
  const handleDiagnosticAnswer = useCallback(async (answer) => {
    if (loading) return;
    setLoading(true);
    try {
      const sid = await ensureSession();
      const res = await rcaNextQuestion({ onboarding_id: sid, answer });
      if (res?.status === 'complete') {
        setShowDiagnostic(false);
        handleStartPlaybook();
        return;
      }
      if (res?.status === 'question' && res?.question) {
        setCurrentQuestion(res.question);
        setQuestionIndex((i) => i + 1);
        return;
      }
      throw new Error('Unexpected diagnostic response');
    } catch (err) {
      setError(`Failed to submit answer: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [loading, ensureSession, handleStartPlaybook, setLoading, setShowDiagnostic, setCurrentQuestion, setQuestionIndex, setError]);

  // Called when user clicks Continue on the website audit stage — now starts RCA
  const handleWebsiteAuditContinue = useCallback(async () => {
    setShowWebsiteAudit(false);
    setWebsiteAuditText('');
    setLoading(true);
    try {
      const sid = await ensureSession();
      setRcaCalling(true);
      const res = await rcaNextQuestion({ onboarding_id: sid });
      if (res?.status === 'question' && res?.question) {
        setCurrentQuestion(res.question);
        setQuestionIndex(0);
        setShowDiagnostic(true);
        setRcaCalling(false);
        setTimeout(scrollToEnd, 50);
      } else if (res?.status === 'complete') {
        setRcaCalling(false);
        handleStartPlaybook();
      } else {
        throw new Error('No diagnostic question available');
      }
    } catch (err) {
      setRcaCalling(false);
      setError(`Failed to start diagnostic: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [ensureSession, handleStartPlaybook, setShowWebsiteAudit, setWebsiteAuditText, setLoading, setRcaCalling, setCurrentQuestion, setQuestionIndex, setShowDiagnostic, scrollToEnd, setError]);

  const handleBackToStep1 = useCallback(() => {
    setSelectedTask(null);
    clearPostTask();
    setUrlValue('');
    setGbpValue('');
  }, [setSelectedTask, clearPostTask, setUrlValue, setGbpValue]);

  // Called when user clicks a claw product after the API pre-creates the onboarding
  const handleClawSelect = useCallback(async ({ onboarding, outcomeObj, domain, task }) => {
    const oid = String(onboarding?.onboarding_id || onboarding?.id || '').trim();
    if (!oid) {
      // API failed — fall back to normal task click
      handleTaskClick(task, outcomeObj, domain);
      return;
    }

    // Point the session at the pre-created onboarding
    onboardingIdRef.current = oid;

    setSelectedOutcome(outcomeObj);
    setSelectedDomain(domain);
    setSelectedTask(task);

    const websiteUrl = String(onboarding.website_url || '').trim();
    if (websiteUrl) setUrlValue(websiteUrl);

    // Restore scale answers from DB format { [question_id]: value } → state format { [index]: value }
    const dbAnswers = onboarding.scale_answers || {};
    if (Object.keys(dbAnswers).length > 0) {
      const indexedAnswers = {};
      STATIC_SCALE_QUESTIONS.forEach((q, i) => {
        if (dbAnswers[q.id] != null) indexedAnswers[i] = dbAnswers[q.id];
      });
      if (Object.keys(indexedAnswers).length > 0) setScaleAnswers(indexedAnswers);
    }

    const webScrapDone = Boolean(onboarding.web_scrap_done);
    const hasScaleAnswers = Object.keys(dbAnswers).length > 0;

    const runRca = () => {
      // Website audit comes before RCA — show audit first, RCA starts after user clicks Continue
      startWebsiteAuditStream(oid);
    };

    if (webScrapDone) {
      // Scraping already done — skip crawl, go straight to RCA
      setShowUrlForm(false);
      setShowDeeperDive(false);
      setShowAnalysisTransition(true);
      await runRca();
    } else if (websiteUrl && hasScaleAnswers) {
      // Have URL + scale answers — start crawl then RCA, skip UI forms
      startCrawlForSession(oid, { websiteUrl }).catch(() => {});
      setShowUrlForm(false);
      setShowDeeperDive(false);
      setShowAnalysisTransition(true);
      try {
        await waitForCrawlDone(90000);
      } catch {
        // Proceed to RCA even if crawl timed out
      }
      await runRca();
    } else {
      // No previous URL/answers — open URL form normally
      handleTaskClick(task, outcomeObj, domain);
    }
  }, [
    onboardingIdRef, handleTaskClick,
    setSelectedOutcome, setSelectedDomain, setSelectedTask,
    setUrlValue, setScaleAnswers,
    setShowUrlForm, setShowDeeperDive, setShowAnalysisTransition,
    startWebsiteAuditStream,
    setError, startCrawlForSession, waitForCrawlDone,
  ]);

  return {
    startNewJourney,
    startWebsiteAuditStream,
    handleOnboardingFieldUpdate,
    handleOutcomeClick,
    handleDomainClick,
    handleTaskClick,
    handleClawSelect,
    handleUrlSubmit,
    handleUrlSkip,
    handleScaleSelect,
    handleScaleSubmit,
    handleStartPlaybook,
    handleTransitionComplete,
    handleGapAnswer,
    handleDiagnosticAnswer,
    handleWebsiteAuditContinue,
    handleBackToStep1,
    clearError,
    scheduleScrollToEnd,
  };
}

