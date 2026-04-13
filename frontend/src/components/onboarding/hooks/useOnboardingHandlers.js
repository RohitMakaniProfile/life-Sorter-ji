import { useCallback, useLayoutEffect } from 'react';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { coreApi } from '../../../api/services/core';
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
    selectedTask, setSelectedTask,
    showUrlForm, setShowUrlForm,
    setToolPage,
    urlValue, setUrlValue,
    gbpValue, setGbpValue,
    setUrlSubmitting,
    earlyTools, setEarlyTools,
    setShowDeeperDive,
    scaleQuestions, setScaleQuestions,
    scaleAnswers, setScaleAnswers,
    setShowDiagnostic,
    currentQuestion, setCurrentQuestion,
    questionIndex, setQuestionIndex,
    loading, setLoading,
    showPrecision, setShowPrecision,
    setPrecisionQuestions,
    precisionIndex, setPrecisionIndex,
    precisionAnswers, setPrecisionAnswers,
    showGapQuestions, setShowGapQuestions,
    gapQuestions, setGapQuestions,
    gapAnswers, setGapAnswers,
    gapCurrentIndex, setGapCurrentIndex,
    setGapSavingIndex,
    setShowPlaybook,
    setShowTransitionMessages,
    setCheckingGapQuestions,
    setShowAnalysisTransition,
    setRcaCalling,
    setShowComplete,
    setError,
    otpVerified, setOtpVerified,
    setViewingRunId,
    pendingPlaybookLaunchRef,
    pendingTaskNodeTransitionRef,
    urlStageTaskNodeRef,
    taskToolsCacheRef,
    taskNodeTransition, setTaskNodeTransition,
    resetAll,
    clearPostTask,
    clearError,
  } = state;

  const {
    prepareStreaming,
    stopStreaming,
    startForSession,
    clearStepReached,
    clearResumeArtifacts,
  } = playbook;

  const {
    startForSession: startCrawlForSession,
    waitForCrawl,
    waitForCrawlDone,
  } = crawl;

  // Scroll helper
  const scheduleScrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollToEnd());
    });
  }, [scrollToEnd]);

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
        setShowPrecision(false);
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
    [updateOnboarding, scheduleScrollToEnd, clearPostTask, setSelectedOutcome, setSelectedDomain, setSelectedTask, setShowUrlForm, setShowDeeperDive, setShowDiagnostic, setShowPrecision, setShowComplete, setToolPage, setEarlyTools, setTaskNodeTransition, pendingTaskNodeTransitionRef, taskToolsCacheRef],
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

  // Playbook handlers
  const handleStartPlaybook = useCallback(async ({ forceVerified = false } = {}) => {
    if (!forceVerified && !otpVerified) {
      pendingPlaybookLaunchRef.current = true;
      const oid = onboardingIdRef.current || '';
      try { sessionStorage.setItem('pending-playbook-launch', 'true'); } catch { /* ignore */ }
      window.location.href = `/phone-verify?next=${encodeURIComponent('/')}&oid=${encodeURIComponent(oid)}`;
      return;
    }

    setCheckingGapQuestions(true);
    try {
      const sid = await ensureSession();
      await waitForCrawl();

      const gapData = await coreApi.onboardingGapQuestionsStart({ onboarding_id: sid });
      const parsedGap = gapData.questions || [];

      if (Array.isArray(parsedGap) && parsedGap.length > 0) {
        setGapQuestions(parsedGap);
        const restored = gapData.gap_answers_parsed && typeof gapData.gap_answers_parsed === 'object' ? gapData.gap_answers_parsed : {};
        const indexed = {};
        Object.entries(restored).forEach(([k, v]) => {
          const idx = Number(String(k).replace(/^Q/i, '')) - 1;
          if (Number.isFinite(idx) && idx >= 0) indexed[idx] = String(v);
        });
        setGapAnswers(indexed);
        let next = 0;
        while (next < parsedGap.length && indexed[next]) next += 1;
        setGapCurrentIndex(next);
        setShowGapQuestions(true);
        setShowPlaybook(true);
        setCheckingGapQuestions(false);
        return;
      }

      setCheckingGapQuestions(false);
      setShowTransitionMessages(true);
      setShowPlaybook(true);
      prepareStreaming();

      try {
        await coreApi.onboardingPlaybookLaunch({ onboarding_id: sid });
        await startForSession(sid, { fresh: true, forceFresh: true });
      } catch (launchErr) {
        console.error('Playbook launch error:', launchErr);
        setError('Failed to start playbook generation.');
        setShowTransitionMessages(false);
        stopStreaming();
      }
    } catch (err) {
      console.error('Gap questions check error:', err);
      setCheckingGapQuestions(false);
      setError('Failed to check gap questions.');
    }
  }, [otpVerified, onboardingIdRef, ensureSession, waitForCrawl, prepareStreaming, startForSession, stopStreaming, setCheckingGapQuestions, setGapQuestions, setGapAnswers, setGapCurrentIndex, setShowGapQuestions, setShowPlaybook, setShowTransitionMessages, setError, pendingPlaybookLaunchRef]);

  const handleTransitionComplete = useCallback(() => {
    setShowTransitionMessages(false);
    setTimeout(scrollToEnd, 50);
  }, [setShowTransitionMessages, scrollToEnd]);

  const handleGapAnswer = useCallback(async (index, answerKey, answerText) => {
    if (!otpVerified) {
      pendingPlaybookLaunchRef.current = true;
      const oid = onboardingIdRef.current || '';
      try { sessionStorage.setItem('pending-playbook-launch', 'true'); } catch { /* ignore */ }
      window.location.href = `/phone-verify?next=${encodeURIComponent('/')}&oid=${encodeURIComponent(oid)}`;
      return;
    }
    setGapSavingIndex(index);
    try {
      const sid = await ensureSession();
      await coreApi.onboardingPlaybookMcqAnswer({
        onboarding_id: sid,
        question_index: index,
        answer_key: answerKey,
        answer_text: answerText,
      });
      setGapAnswers((prev) => ({ ...prev, [index]: answerKey }));
      const next = index + 1;
      if (next >= gapQuestions.length) {
        setShowGapQuestions(false);
        prepareStreaming();
        await coreApi.onboardingPlaybookLaunch({ onboarding_id: sid });
        await startForSession(sid, { fresh: false });
      } else {
        setGapCurrentIndex(next);
      }
    } catch {
      setError('Failed to save answer.');
      stopStreaming();
    } finally {
      setGapSavingIndex(null);
    }
  }, [otpVerified, onboardingIdRef, ensureSession, gapQuestions.length, prepareStreaming, startForSession, stopStreaming, setGapSavingIndex, setGapAnswers, setShowGapQuestions, setGapCurrentIndex, setError, pendingPlaybookLaunchRef]);

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

      setRcaCalling(true);
      const res = await rcaNextQuestion({ onboarding_id: sid });

      if (res?.status === 'question' && res?.question) {
        setCurrentQuestion(res.question);
        setQuestionIndex(0);
        setTimeout(() => {
          setShowAnalysisTransition(false);
          setShowDiagnostic(true);
          setRcaCalling(false);
          setTimeout(scrollToEnd, 50);
        }, 800);
      } else if (res?.status === 'complete') {
        setShowAnalysisTransition(false);
        setRcaCalling(false);
        handleStartPlaybook();
      } else {
        throw new Error('No diagnostic question available');
      }
    } catch {
      setShowAnalysisTransition(false);
      setRcaCalling(false);
      setError('Failed to start diagnostic.');
    } finally {
      setLoading(false);
    }
  }, [ensureSession, scaleAnswers, handleOnboardingFieldUpdate, waitForCrawlDone, handleStartPlaybook, setLoading, setShowAnalysisTransition, setShowDeeperDive, setRcaCalling, setCurrentQuestion, setQuestionIndex, setShowDiagnostic, setError, scrollToEnd]);

  // Diagnostic handlers
  const handleDiagnosticAnswer = useCallback(async (answer) => {
    if (loading) return;
    setLoading(true);
    try {
      const sid = await ensureSession();
      const res = await rcaNextQuestion({ onboarding_id: sid, answer });
      if (res?.status === 'complete') {
        const precData = await coreApi.onboardingPrecisionStart({ onboarding_id: sid });
        if (precData?.available && precData?.questions?.length) {
          setPrecisionQuestions(precData.questions);
          setPrecisionAnswers({});
          setPrecisionIndex(0);
          setCurrentQuestion(precData.questions[0]);
          setShowPrecision(true);
          setTimeout(scrollToEnd, 50);
          return;
        }
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
  }, [loading, ensureSession, handleStartPlaybook, setLoading, setPrecisionQuestions, setPrecisionAnswers, setPrecisionIndex, setCurrentQuestion, setShowPrecision, setQuestionIndex, setError, scrollToEnd]);

  const handlePrecisionAnswer = useCallback(async (answer) => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      const res = await coreApi.onboardingPrecisionAnswer({
        onboarding_id: sid,
        question_index: precisionIndex,
        answer,
      });
      if (res?.all_answered) {
        setShowPrecision(false);
        handleStartPlaybook();
        return;
      }
      if (res?.next_question) {
        setPrecisionIndex((i) => i + 1);
        setCurrentQuestion(res.next_question);
      }
    } catch {
      setError('Failed to submit precision answer.');
    } finally {
      setLoading(false);
    }
  }, [ensureSession, precisionIndex, handleStartPlaybook, setLoading, setShowPrecision, setPrecisionIndex, setCurrentQuestion, setError]);

  const handleBackToStep1 = useCallback(() => {
    setSelectedTask(null);
    clearPostTask();
    setUrlValue('');
    setGbpValue('');
  }, [setSelectedTask, clearPostTask, setUrlValue, setGbpValue]);

  return {
    startNewJourney,
    handleOnboardingFieldUpdate,
    handleOutcomeClick,
    handleDomainClick,
    handleTaskClick,
    handleUrlSubmit,
    handleUrlSkip,
    handleScaleSelect,
    handleScaleSubmit,
    handleStartPlaybook,
    handleTransitionComplete,
    handleGapAnswer,
    handleDiagnosticAnswer,
    handlePrecisionAnswer,
    handleBackToStep1,
    clearError,
    scheduleScrollToEnd,
  };
}

