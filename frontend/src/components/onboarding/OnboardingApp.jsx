import { useState, useRef, useMemo, useCallback, useLayoutEffect, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import StageLayout from './components/StageLayout';
import TransitionMessages from './components/TransitionMessages';
import UrlStage from './stages/UrlStage';
import DeeperDiveStage from './stages/DeeperDiveStage';
import DiagnosticStage from './stages/DiagnosticStage';
import PlaybookStage from './stages/PlaybookStage';
import CompleteStage from './stages/CompleteStage';
import OtpModal from './components/OtpModal';
import OnboardingHero from './components/OnboardingHero';
import OnboardingJourneyCanvas from './components/OnboardingJourneyCanvas';
import OnboardingErrorToast from './components/OnboardingErrorToast';
import AnalysisTransitionMessages from './components/AnalysisTransitionMessages';
import DeveloperTaskStreamsPanel from './components/DeveloperTaskStreamsPanel';
import { useOnboardingSession } from './hooks/useOnboardingSession';
import { useOnboardingJourneyIdleOutcomeDemo } from './hooks/useOnboardingJourneyIdleOutcomeDemo';
import { useOnboardingCanvasScroll } from './hooks/useOnboardingCanvasScroll';
import { useCrawlTaskStream } from './hooks/useCrawlTaskStream';
import { outcomeOptions } from './onboardingJourneyData';
import { mapToolsToEarlyTools } from './toolService';
import { apiGet, apiPost } from '../../api/http';
import { API_ROUTES } from '../../api/routes';
import { coreApi } from '../../api/services/core';
import { usePlaybookTaskStream } from './hooks/usePlaybookTaskStream';
import { PAYMENT_CONTINUE_WEBSITE_URL_KEY, canUseDeepAnalysisReport } from '../../lib/paymentAccess';
import { getUserIdFromJwt } from '../../api/authSession';
import FlowNode from './components/FlowNode';
import STATIC_SCALE_QUESTIONS from './data/scale_questions.json';
const rcaNextQuestion = (body) => apiPost(API_ROUTES.onboarding.rcaNextQuestion, body ?? {});

const ONBOARDING_PATCH_KEYS = ['outcome', 'domain', 'task', 'website_url', 'gbp_url', 'scale_answers'];

function buildOnboardingPatch(fields) {
  const o = {};
  for (const k of ONBOARDING_PATCH_KEYS) {
    if (Object.prototype.hasOwnProperty.call(fields, k)) o[k] = fields[k];
  }
  return o;
}

const TASK_KEY_SEP = '|||';

const toRectObj = (r) => ({ top: r.top, left: r.left, width: r.width, height: r.height });

export default function OnboardingApp() {
  const navigate = useNavigate();

  /**
   * JusPay return hits `FRONTEND_URL` (often `/`). Record premium server-side and open the global payment page.
   */
  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '');
    const orderId = params.get('order_id');
    if (!orderId) return;

    const uid = getUserIdFromJwt();

    const stripPaymentQuery = () => {
      try {
        window.history.replaceState({}, '', window.location.pathname);
      } catch {
        /* ignore */
      }
    };

    (async () => {
      if (!uid) {
        stripPaymentQuery();
        if (!cancelled) {
          navigate('/payment', {
            replace: true,
            state: {
              paymentError: 'Sign in with your mobile number to finish confirming payment.',
            },
          });
        }
        return;
      }
      try {
        await apiPost(API_ROUTES.payments.complete, { order_id: orderId });
        stripPaymentQuery();
        if (!cancelled) navigate('/payment', { replace: true });
      } catch (err) {
        stripPaymentQuery();
        const msg = err?.message || 'Could not confirm payment.';
        if (!cancelled) navigate('/payment', { replace: true, state: { paymentError: msg } });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [navigate]);
  const { sessionIdRef: onboardingIdRef, ensureSession, updateOnboarding, getSessionState, clearSession } = useOnboardingSession();
  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);

  const outcomeIds = useMemo(() => outcomeOptions.map((o) => o.id), []);
  const { programmaticHoveredOutcomeId, onJourneyDirectInteraction } = useOnboardingJourneyIdleOutcomeDemo(
    !selectedOutcome,
    outcomeIds,
  );
  const { canvasRef, scrollToEnd } = useOnboardingCanvasScroll();

  const [showUrlForm, setShowUrlForm] = useState(false);
  const [toolPage, setToolPage] = useState(0);
  const [urlValue, setUrlValue] = useState('');
  const [gbpValue, setGbpValue] = useState('');
  const [urlTab, setUrlTab] = useState('website');
  const [urlSubmitting, setUrlSubmitting] = useState(false);
  const [earlyTools, setEarlyTools] = useState([]);

  const [showDeeperDive, setShowDeeperDive] = useState(false);
  const [scaleQuestions, setScaleQuestions] = useState([]);
  const [scaleAnswers, setScaleAnswers] = useState({});
  const [scalePage, setScalePage] = useState(0);

  const [showDiagnostic, setShowDiagnostic] = useState(false);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [showPrecision, setShowPrecision] = useState(false);
  const [_precisionQuestions, setPrecisionQuestions] = useState([]);
  const [precisionIndex, setPrecisionIndex] = useState(0);
  const [precisionAnswers, setPrecisionAnswers] = useState({});

  const [showComplete, setShowComplete] = useState(false);
  const [error, setError] = useState(null);

  const [showPlaybook, setShowPlaybook] = useState(false);
  const [gapQuestions, setGapQuestions] = useState([]);
  const [gapAnswers, setGapAnswers] = useState({});
  const [gapCurrentIndex, setGapCurrentIndex] = useState(0);
  const [gapSavingIndex, setGapSavingIndex] = useState(null);
  const [showGapQuestions, setShowGapQuestions] = useState(false);
  const [showTransitionMessages, setShowTransitionMessages] = useState(false);
  const [checkingGapQuestions, setCheckingGapQuestions] = useState(false);

  // Analysis transition state (between scale questions and RCA)
  const [showAnalysisTransition, setShowAnalysisTransition] = useState(false);
  const [rcaCalling, setRcaCalling] = useState(false);

  const [showOtpModal, setShowOtpModal] = useState(false);
  const [otpVerified, setOtpVerified] = useState(() => Boolean(getUserIdFromJwt()));
  const pendingPlaybookLaunchRef = useRef(false);

  const {
    playbookStreaming,
    playbookText,
    playbookDone,
    playbookResult,
    needsManualRetry,
    prepareStreaming,
    markRetryNeeded,
    stopStreaming,
    startForSession,
    clearStepReached,
    clearResumeArtifacts,
  } = usePlaybookTaskStream({
    ensureSession,
    otpVerified,
    onRequestOtp: () => setShowOtpModal(true),
    onShowPlaybook: () => setShowPlaybook(true),
    setError,
  });

  const { crawlStreaming, crawlLabel, crawlProgress, startForSession: startCrawlForSession, waitForCrawl, waitForCrawlDone } = useCrawlTaskStream({
    ensureSession,
    setError,
  });

  const pendingTaskNodeTransitionRef = useRef(null);
  const urlStageTaskNodeRef = useRef(null);
  const [taskNodeTransition, setTaskNodeTransition] = useState(null);
  const taskToolsCacheRef = useRef(new Map());
  const sessionRestoredRef = useRef(false);

  const resetJourneyUiState = useCallback(() => {
    setSelectedOutcome(null);
    setSelectedDomain(null);
    setSelectedTask(null);
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setShowPlaybook(false);
    setShowGapQuestions(false);
    setShowTransitionMessages(false);
    setCheckingGapQuestions(false);
    setScaleAnswers({});
    setPrecisionAnswers({});
    setGapAnswers({});
    setGapCurrentIndex(0);
    setGapSavingIndex(null);
    setCurrentQuestion(null);
    setQuestionIndex(0);
    setPrecisionIndex(0);
  }, []);

  const clearOnboardingClientStorage = useCallback(() => {
    try {
      const keep = new Set(['ikshan-auth-token', 'luna_user_id']);
      const toDelete = [];
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (!key || keep.has(key)) continue;
        if (key.startsWith('life-sorter') || key.startsWith('doable-claw') || key.startsWith('ikshan-taskstream')) {
          toDelete.push(key);
        }
      }
      toDelete.forEach((k) => localStorage.removeItem(k));
    } catch {
      // ignore storage failures
    }
  }, []);

  const startNewJourney = useCallback(() => {
    clearStepReached();
    clearResumeArtifacts();
    clearSession();
    resetJourneyUiState();
    clearOnboardingClientStorage();
    window.location.href = '/?reset=1';
  }, [clearStepReached, clearResumeArtifacts, clearSession, resetJourneyUiState, clearOnboardingClientStorage]);

  const clearPostTask = () => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setShowTransitionMessages(false);
    setCheckingGapQuestions(false);
    setEarlyTools([]);
  };

  /**
   * Session restoration on mount: fetch saved state and restore UI to the appropriate stage.
   * Only runs once on mount.
   * If stage is "complete", clears session and starts fresh.
   */
  useEffect(() => {
    // Prevent running multiple times
    if (sessionRestoredRef.current) return;
    sessionRestoredRef.current = true;

    const restoreSession = async () => {
      // If ?reset=1 is in URL, skip restoration and start fresh
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('reset') === '1') {
        try { window.history.replaceState({}, '', window.location.pathname); } catch { /* ignore */ }
        return;
      }
      try {
        const state = await getSessionState();
        console.log('[Onboarding Restore] State received:', state);
        if (!state) {
          console.log('[Onboarding Restore] No state to restore');
          return;
        }

        // If onboarding is complete, show the completed playbook
        if (state.stage === 'complete') {
          if (state.outcome) {
            const outcome = outcomeOptions.find((o) => o.id === state.outcome);
            if (outcome) setSelectedOutcome(outcome);
          }
          if (state.domain) setSelectedDomain(state.domain);
          if (state.task) setSelectedTask(state.task);
          setShowPlaybook(true);
          clearStepReached();
          prepareStreaming();
          const sid = state.onboarding_id;
          if (sid) {
            onboardingIdRef.current = sid;
            startForSession(sid, { fresh: false }).catch(() => {});
          }
          return;
        }

        // Restore outcome
        if (state.outcome) {
          const outcome = outcomeOptions.find((o) => o.id === state.outcome);
          if (outcome) setSelectedOutcome(outcome);
        }

        // Restore domain and task
        if (state.domain) setSelectedDomain(state.domain);
        if (state.task) setSelectedTask(state.task);

        // Restore URL values
        if (state.website_url) setUrlValue(state.website_url);
        if (state.gbp_url) setGbpValue(state.gbp_url);

        // Restore scale answers
        if (state.scale_answers && typeof state.scale_answers === 'object') {
          // Convert id-based answers to index-based for UI
          const indexedAnswers = {};
          for (let i = 0; i < STATIC_SCALE_QUESTIONS.length; i++) {
            const q = STATIC_SCALE_QUESTIONS[i];
            if (state.scale_answers[q.id] !== undefined) {
              indexedAnswers[i] = state.scale_answers[q.id];
            }
          }
          setScaleAnswers(indexedAnswers);
        }

        // Restore to the appropriate stage based on backend state
        switch (state.stage) {
          case 'url':
            clearResumeArtifacts();
            // Task selected, show URL form directly
            console.log('[Onboarding Restore] Restoring to URL stage', { outcome: state.outcome, domain: state.domain, task: state.task });
            setShowUrlForm(true);
            // Load tools for the task (async, don't block UI)
            if (state.outcome && state.domain && state.task) {
              apiPost(API_ROUTES.onboarding.toolsByQ1Q2Q3, {
                outcome: state.outcome,
                domain: state.domain,
                task: state.task,
              })
                .then((res) => {
                  if (res?.tools) {
                    setEarlyTools(mapToolsToEarlyTools(res.tools));
                  }
                })
                .catch(() => {
                  // ignore tool fetch errors
                });
            }
            break;

          case 'questions':
            clearResumeArtifacts();
            // URL submitted, show scale questions
            // But first check if scale_answers already exist - if so, we should move to diagnostic
            if (state.scale_answers && Object.keys(state.scale_answers).length > 0) {
              setScaleQuestions(STATIC_SCALE_QUESTIONS);
              // Ensure onboardingIdRef is set for subsequent API calls.
              if (state.onboarding_id) {
                onboardingIdRef.current = state.onboarding_id;
              }
              // Keep restore non-mutating: do not call RCA-next API while restoring.
              // User can continue from the diagnostic launcher, which performs a single explicit fetch.
              setShowDeeperDive(true);
            } else {
              setScaleQuestions(STATIC_SCALE_QUESTIONS);
              setShowDeeperDive(true);
            }
            break;

          case 'diagnostic':
            clearResumeArtifacts();
            // Scale questions done, show diagnostic
            setScaleQuestions(STATIC_SCALE_QUESTIONS);
            // Ensure onboardingIdRef is set for subsequent API calls.
            if (state.onboarding_id) {
              onboardingIdRef.current = state.onboarding_id;
            }
            if (state.current_rca_question) {
              setCurrentQuestion(state.current_rca_question);
              // Count answered questions
              const answeredCount = state.rca_qa?.filter((qa) => qa.answer)?.length || 0;
              setQuestionIndex(answeredCount);
              setShowDiagnostic(true);
            } else {
              // Keep restore non-mutating when backend doesn't have a current RCA question.
              // We intentionally avoid firing rcaNextQuestion during restore to prevent loops/duplicates.
              setShowDeeperDive(true);
            }
            break;

          case 'precision':
            clearResumeArtifacts();
            // Show precision questions
            if (state.precision_questions?.length) {
              setPrecisionQuestions(state.precision_questions);
              const answeredCount = state.precision_answers?.length || 0;
              setPrecisionIndex(answeredCount);
              if (answeredCount < state.precision_questions.length) {
                setCurrentQuestion(state.precision_questions[answeredCount]);
              }
              setShowPrecision(true);
              setShowDiagnostic(true);
            }
            break;

          case 'playbook':
            // Playbook stage - check if gap questions needed
            if (state.playbook_status === 'awaiting_gap_answers' && state.gap_questions?.length) {
              setGapQuestions(state.gap_questions);
              const restored = state.gap_answers_parsed && typeof state.gap_answers_parsed === 'object' ? state.gap_answers_parsed : {};
              const indexed = {};
              Object.entries(restored).forEach(([k, v]) => {
                const idx = Number(String(k).replace(/^Q/i, '')) - 1;
                if (Number.isFinite(idx) && idx >= 0) indexed[idx] = String(v);
              });
              setGapAnswers(indexed);
              let next = 0;
              while (next < state.gap_questions.length && indexed[next]) next += 1;
              setGapCurrentIndex(next);
              setShowGapQuestions(true);
            }
            setShowPlaybook(true);
            if (state.playbook_status === 'error') {
              markRetryNeeded();
            } else if (state.playbook_status === 'generating' || state.playbook_status === 'started') {
              prepareStreaming();
              const sid = onboardingIdRef.current;
              if (sid) {
                startForSession(sid, { fresh: false }).catch(() => {});
              }
            } else if (state.playbook_status === 'complete') {
              // Playbook done — clear auto-resume flag, then reconnect once to fetch result
              clearStepReached();
              prepareStreaming();
              const sid = onboardingIdRef.current;
              if (sid) {
                startForSession(sid, { fresh: false }).catch(() => {});
              }
            }
            break;

          case 'complete':
            // Onboarding fully complete — playbook is done, show it
            setShowPlaybook(true);
            clearStepReached();
            prepareStreaming();
            {
              const sid = onboardingIdRef.current;
              if (sid) {
                startForSession(sid, { fresh: false }).catch(() => {});
              }
            }
            break;

          default:
            clearResumeArtifacts();
            // Start stage - nothing to restore
            break;
        }
      } catch (err) {
        console.warn('Session restoration failed:', err);
      }
    };

    restoreSession();
  }, [clearResumeArtifacts, clearStepReached, getSessionState, markRetryNeeded, onboardingIdRef, prepareStreaming, startForSession]); // Empty behavior with stable deps

  /** After layout/paint so wide journey content (domains/tasks) is measurable for scroll width. */
  const scheduleScrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollToEnd());
    });
  }, [scrollToEnd]);

  /**
   * Single path for onboarding row fields: POST `/api/v1/onboarding` with `onboarding_id` + any of
   * outcome, domain, task, website_url, gbp_url. `fields` uses only keys you intend to write (including `null` to clear).
   */
  const handleOnboardingFieldUpdate = useCallback(
    async (fields, ui = {}) => {
      const {
        nextOutcome,
        nextDomain,
        nextTask,
        clearPostTaskStages,
        openUrlForm,
        toolContext,
      } = ui;

      if (nextOutcome !== undefined) setSelectedOutcome(nextOutcome);
      if (nextDomain !== undefined) setSelectedDomain(nextDomain);
      if (nextTask !== undefined) setSelectedTask(nextTask);
      if (clearPostTaskStages) clearPostTask();
      if (openUrlForm) {
        const pending = pendingTaskNodeTransitionRef.current;
        if (pending) {
          const rawKey = `${pending.domain}${TASK_KEY_SEP}${pending.task}`;
          const safeKey =
            typeof window !== 'undefined' && window.CSS && typeof window.CSS.escape === 'function'
              ? window.CSS.escape(rawKey)
              : rawKey.replace(/"/g, '\\"');
          const anchorEl = document.querySelector(
            `[data-journey-anchor="task"][data-journey-key="${safeKey}"]`,
          );
          const fromRect = anchorEl?.getBoundingClientRect?.();
          if (fromRect && fromRect.width > 0 && fromRect.height > 0) {
            setTaskNodeTransition({
              fromRect: toRectObj(fromRect),
              toRect: null,
              phase: 'enter',
              label: pending.task,
            });
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
    [ensureSession, updateOnboarding, scheduleScrollToEnd],
  );

  // When switching into UrlStage via a task click, animate the selected task node
  // from its position in `OnboardingJourneyCanvas` into the UrlStage header.
  useLayoutEffect(() => {
    if (!showUrlForm) return;
    const pending = taskNodeTransition;
    if (!pending || pending.toRect) return;
    const el = urlStageTaskNodeRef.current;
    if (!el?.getBoundingClientRect) return;

    const toRect = toRectObj(el.getBoundingClientRect());
    setTaskNodeTransition((prev) => (prev ? { ...prev, toRect, phase: 'enter' } : prev));
    requestAnimationFrame(() => {
      setTaskNodeTransition((prev) => (prev ? { ...prev, phase: 'animate' } : prev));
    });
  }, [showUrlForm, taskNodeTransition]);

  useLayoutEffect(() => {
    if (!taskNodeTransition || taskNodeTransition.phase !== 'animate') return;
    const t = setTimeout(() => setTaskNodeTransition(null), 820);
    return () => clearTimeout(t);
  }, [taskNodeTransition?.phase]);

  const handleOutcomeClick = (outcome) => {
    handleOnboardingFieldUpdate(
      { outcome: outcome.id, domain: null, task: null },
      {
        nextOutcome: outcome,
        nextDomain: null,
        nextTask: null,
        clearPostTaskStages: true,
      },
    );
  };

  /** `previewOutcome` when the user picks a domain while only hovering an outcome (not committed). */
  const handleDomainClick = (domain, previewOutcome) => {
    handleOnboardingFieldUpdate(
      previewOutcome
        ? { outcome: previewOutcome.id, domain, task: null }
        : { domain, task: null },
      {
        ...(previewOutcome ? { nextOutcome: previewOutcome } : {}),
        nextDomain: domain,
        nextTask: null,
        clearPostTaskStages: true,
      },
    );
  };

  const handleTaskClick = (task, previewOutcome, previewDomain) => {
    const effectiveOutcome = selectedOutcome ?? previewOutcome;
    const effectiveDomain = selectedDomain ?? previewDomain;
    if (!effectiveOutcome || !effectiveDomain) {
      console.warn('Task click: missing outcome or domain');
      return;
    }
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
  };

  const handleUrlSubmit = async (e) => {
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
  };

  const handleUrlSkip = async () => {
    setUrlSubmitting(true);
    try {
      // No crawl will be started; proceed to next step.
    } catch (err) {
      console.warn('Skip URL:', err.message);
    }
    await moveToScaleQuestions();
    setUrlSubmitting(false);
  };

  const moveToScaleQuestions = async () => {
    setScaleQuestions(STATIC_SCALE_QUESTIONS);
    setShowDeeperDive(true);
    setTimeout(scrollToEnd, 50);
  };

  const handleScaleSelect = (qId, option, multiSelect) => {
    setScaleAnswers((prev) => {
      if (multiSelect) {
        const cur = prev[qId] || [];
        return {
          ...prev,
          [qId]: cur.includes(option) ? cur.filter((o) => o !== option) : [...cur, option],
        };
      }
      return { ...prev, [qId]: option };
    });
  };

  const handleStartPlaybook = async ({ forceVerified = false } = {}) => {
    if (!forceVerified && !otpVerified) {
      pendingPlaybookLaunchRef.current = true;
      setShowOtpModal(true);
      return;
    }

    // Step 1: Check gap questions first
    setCheckingGapQuestions(true);
    try {
      const sid = await ensureSession();
      await waitForCrawl();

      // Call the new gap questions API
      const gapData = await coreApi.onboardingGapQuestionsStart({ onboarding_id: sid });
      const parsedGap = gapData.questions || [];

      if (Array.isArray(parsedGap) && parsedGap.length > 0) {
        // Gap questions exist - show them and wait for answers
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

      // No gap questions - show transition messages and launch playbook in parallel
      setCheckingGapQuestions(false);
      setShowTransitionMessages(true);
      setShowPlaybook(true);
      prepareStreaming();

      // Launch playbook immediately (parallel execution)
      try {
        await coreApi.onboardingPlaybookLaunch({ onboarding_id: sid });
        await startForSession(sid, { fresh: false });
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
  };

  const handleOtpVerified = () => {
    setOtpVerified(true);
    setShowOtpModal(false);
  };

  // Called when transition messages animation completes
  const handleTransitionComplete = useCallback(() => {
    setShowTransitionMessages(false);
    setTimeout(scrollToEnd, 50);
  }, [scrollToEnd]);

  useEffect(() => {
    if (!otpVerified || !pendingPlaybookLaunchRef.current) return;
    pendingPlaybookLaunchRef.current = false;
    handleStartPlaybook({ forceVerified: true }).catch(() => {});
  }, [otpVerified]);

  useEffect(() => {
    if (gapSavingIndex == null) return undefined;
    const t = setTimeout(() => setGapSavingIndex(null), 3000);
    return () => clearTimeout(t);
  }, [gapSavingIndex]);

  const handleGapAnswer = async (index, answerKey, answerText) => {
    if (!otpVerified) {
      pendingPlaybookLaunchRef.current = true;
      setShowOtpModal(true);
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
  };

  const handleScaleSubmit = async () => {
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

      // Show analysis transition while waiting for crawl and RCA
      setShowAnalysisTransition(true);
      setShowDeeperDive(false);

      // Wait until the crawl task stream has finished successfully.
      await waitForCrawlDone(90000);

      // Now calling RCA API
      setRcaCalling(true);
      const res = await rcaNextQuestion({ onboarding_id: sid });

      if (res?.status === 'question' && res?.question) {
        setCurrentQuestion(res.question);
        setQuestionIndex(0);
        // Keep transition showing briefly then show diagnostic
        setTimeout(() => {
          setShowAnalysisTransition(false);
          setShowDiagnostic(true);
          setRcaCalling(false);
          setTimeout(scrollToEnd, 50);
        }, 800);
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
  };

  const handleDiagnosticAnswer = async (answer) => {
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
  };
  const handlePrecisionAnswer = async (answer) => {
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
  };

  const getWebsiteUrl = () => (urlValue || '').trim();

  const handleDeepAnalysis = async () => {
    const url = getWebsiteUrl();
    try {
      if (url) sessionStorage.setItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY, url);
      else sessionStorage.removeItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY);
    } catch {
      // ignore
    }

    if (!getUserIdFromJwt()) {
      setError('Verify your mobile number (playbook unlock step) before deep analysis.');
      return;
    }

    try {
      const ent = await apiGet(API_ROUTES.payments.entitlements);
      if (canUseDeepAnalysisReport(ent)) {
        const userLine = url ? `${url}\n\nDo deep analysis.` : '';
        navigate('/new', {
          state: {
            agentId: 'business-research',
            ...(userLine ? { initialMessage: userLine } : {}),
          },
        });
        return;
      }
    } catch (err) {
      setError(err?.message || 'Could not load plan entitlements.');
      return;
    }

    navigate('/payment', { state: { intent: 'deep-analysis', websiteUrl: url || undefined } });
  };

  const handleBackToStep1 = () => {
    setSelectedTask(null);
    clearPostTask();
    setUrlValue('');
    setGbpValue('');
  };

  const clearError = () => setError(null);

  if (showOtpModal) {
    return <OtpModal onboardingId={onboardingIdRef.current || ''} onVerified={handleOtpVerified} />;
  }

  // Show loading state while checking gap questions
  if (checkingGapQuestions) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        <div className="flex min-h-[50vh] flex-col items-center justify-center px-4">
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-violet-500" />
            <p className="text-sm text-white/60">Analyzing your responses...</p>
          </div>
        </div>
      </StageLayout>
    );
  }

  if (showPlaybook) {
    // Show transition messages if active (playbook generating in background)
    if (showTransitionMessages) {
      return (
        <StageLayout error={error} onClearError={clearError}>
          <DeveloperTaskStreamsPanel
            onboardingId={onboardingIdRef.current}
            userId={null}
            taskTypes={['crawl', 'playbook/onboarding-generate']}
          />
          <TransitionMessages
            onComplete={handleTransitionComplete}
            isComplete={playbookDone}
          />
        </StageLayout>
      );
    }

    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        <PlaybookStage
          showGapQuestions={showGapQuestions}
          gapQuestions={gapQuestions}
          gapAnswers={gapAnswers}
          gapCurrentIndex={gapCurrentIndex}
          gapSavingIndex={gapSavingIndex}
          onGapAnswer={handleGapAnswer}
          playbookStreaming={playbookStreaming}
          playbookText={playbookText}
          playbookDone={playbookDone}
          playbookResult={playbookResult}
          onDeepAnalysis={handleDeepAnalysis}
          onGoHome={startNewJourney}
          showRetry={!showGapQuestions && !playbookStreaming && !playbookDone && needsManualRetry}
          onRetry={() => handleStartPlaybook()}
          retryLabel="Retry Playbook"
          onRetryPlaybook={() => handleStartPlaybook()}
          onCancel={startNewJourney}
        />
      </StageLayout>
    );
  }

  if (showComplete) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        <CompleteStage error={error} onClearError={clearError} onDeepAnalysis={handleDeepAnalysis} />
      </StageLayout>
    );
  }

  if (showDiagnostic && currentQuestion) {
    const answerHandler = showPrecision ? handlePrecisionAnswer : handleDiagnosticAnswer;
    const activeIndex = showPrecision ? precisionIndex : questionIndex;
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        <DiagnosticStage
          currentQuestion={currentQuestion}
          questionIndex={activeIndex}
          scaleAnswers={showPrecision ? precisionAnswers : scaleAnswers}
          onAnswer={(opt) => {
            if (showPrecision) {
              setPrecisionAnswers((prev) => ({ ...prev, [activeIndex]: opt }));
            } else {
              setScaleAnswers((prev) => ({ ...prev, [questionIndex]: opt }));
            }
            answerHandler(opt);
          }}
          loading={loading}
          onBack={() => {
            setShowDiagnostic(false);
            setShowDeeperDive(true);
          }}
        />
      </StageLayout>
    );
  }

  // Analysis transition (between scale questions and diagnostic)
  if (showAnalysisTransition) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        <AnalysisTransitionMessages
          crawlStreaming={crawlStreaming}
          crawlProgress={crawlProgress}
          rcaCalling={rcaCalling}
          isComplete={false}
          onComplete={() => {}}
        />
      </StageLayout>
    );
  }

  if (showDeeperDive) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        <DeeperDiveStage
          scaleQuestions={scaleQuestions}
          scaleAnswers={scaleAnswers}
          onSelect={handleScaleSelect}
          scalePage={scalePage}
          onPageChange={setScalePage}
          onSubmit={handleScaleSubmit}
          onBack={() => {
            setShowDeeperDive(false);
            setShowUrlForm(true);
          }}
          loading={loading}
          crawlStreaming={crawlStreaming}
          crawlLabel={crawlLabel}
          crawlProgress={crawlProgress}
        />
      </StageLayout>
    );
  }

  if (showUrlForm) {
    const from = taskNodeTransition?.fromRect;
    const to = taskNodeTransition?.toRect;
    const phase = taskNodeTransition?.phase || 'enter';
    const dx = from && to ? to.left - from.left : 0;
    const dy = from && to ? to.top - from.top : 0;
    const sx = from && to && from.width > 0 ? to.width / from.width : 1;
    const sy = from && to && from.height > 0 ? to.height / from.height : 1;

    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel
          onboardingId={onboardingIdRef.current}
          userId={null}
          taskTypes={['crawl', 'playbook/onboarding-generate']}
        />
        {taskNodeTransition && from ? (
          <div
            aria-hidden
            className="pointer-events-none fixed left-0 top-0 z-[60]"
            style={{
              width: from.width,
              height: from.height,
              transform: `translate(${from.left}px, ${from.top}px) translate(${phase === 'animate' ? dx : 0}px, ${
                phase === 'animate' ? dy : 0
              }px) scale(${phase === 'animate' ? sx : 1}, ${phase === 'animate' ? sy : 1})`,
              transformOrigin: 'top left',
              transition: phase === 'animate' ? 'transform 820ms cubic-bezier(0.25,0.46,0.45,0.94)' : 'none',
              willChange: 'transform',
            }}
          >
            <FlowNode label={taskNodeTransition.label} variant="light" active />
          </div>
        ) : null}
        <div className={taskNodeTransition ? 'opacity-0 pointer-events-none' : 'opacity-100'}>
          <UrlStage
            selectedDomain={selectedDomain}
            selectedTask={selectedTask}
            taskNodeContainerRef={urlStageTaskNodeRef}
            urlValue={urlValue}
            gbpValue={gbpValue}
            onUrlChange={setUrlValue}
            onGbpChange={setGbpValue}
            urlTab={urlTab}
            onTabChange={setUrlTab}
            onSubmit={handleUrlSubmit}
            onSkip={handleUrlSkip}
            urlSubmitting={urlSubmitting}
            crawlRunning={crawlStreaming}
            earlyTools={earlyTools}
            toolPage={toolPage}
            onToolPageChange={setToolPage}
            onBack={handleBackToStep1}
          />
        </div>
      </StageLayout>
    );
  }

  return (
    <div className="flex h-screen max-h-screen flex-col overflow-hidden bg-[#111] bg-[radial-gradient(circle,rgba(255,255,255,0.18)_1px,transparent_1px)] bg-[length:14px_14px] font-sans text-white [&_button]:font-inherit [&_input]:font-inherit">
      <Navbar />
      <DeveloperTaskStreamsPanel
        onboardingId={onboardingIdRef.current}
        userId={null}
        taskTypes={['crawl', 'playbook/onboarding-generate']}
      />
      <OnboardingHero />

      <OnboardingJourneyCanvas
        canvasRef={canvasRef}
        selectedOutcome={selectedOutcome}
        selectedDomain={selectedDomain}
        selectedTask={selectedTask}
        onOutcomeClick={handleOutcomeClick}
        onDomainClick={handleDomainClick}
        onTaskClick={handleTaskClick}
        outcomeOptions={outcomeOptions}
        programmaticHoveredOutcomeId={programmaticHoveredOutcomeId}
        onJourneyUserActivity={onJourneyDirectInteraction}
      />

      <OnboardingErrorToast error={error} onClear={clearError} />
    </div>
  );
}
