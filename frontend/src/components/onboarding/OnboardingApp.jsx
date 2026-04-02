import { useState, useRef, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import StageLayout from './components/StageLayout';
import UrlStage from './stages/UrlStage';
import DeeperDiveStage from './stages/DeeperDiveStage';
import DiagnosticStage from './stages/DiagnosticStage';
import PlaybookStage from './stages/PlaybookStage';
import CompleteStage from './stages/CompleteStage';
import OtpModal from './components/OtpModal';
import OnboardingHero from './components/OnboardingHero';
import OnboardingJourneyCanvas from './components/OnboardingJourneyCanvas';
import OnboardingErrorToast from './components/OnboardingErrorToast';
import { useOnboardingSession } from './hooks/useOnboardingSession';
import { useOnboardingJourneyIdleOutcomeDemo } from './hooks/useOnboardingJourneyIdleOutcomeDemo';
import { useOnboardingCanvasScroll } from './hooks/useOnboardingCanvasScroll';
import { useOnboardingCrawlPolling } from './hooks/useOnboardingCrawlPolling';
import { outcomeOptions } from './constants';
import { getToolsForSelection, mapToolsToEarlyTools } from './toolService';
import { apiPost } from '../../api/http';
import { API_ROUTES } from '../../api/routes';
import { coreApi } from '../../api/services/core';
const upsertOnboarding = (body) => apiPost(API_ROUTES.onboarding.upsert, body ?? {});

const ONBOARDING_PATCH_KEYS = ['outcome', 'domain', 'task', 'website_url', 'gbp_url'];

function buildOnboardingPatch(fields) {
  const o = {};
  for (const k of ONBOARDING_PATCH_KEYS) {
    if (Object.prototype.hasOwnProperty.call(fields, k)) o[k] = fields[k];
  }
  return o;
}

/** Backend sanitizes URLs; only send fields the user filled in. */
const patchSessionUrls = (sessionId, { websiteInput, gbpInput } = {}) => {
  const body = {};
  if (websiteInput) body.business_url = websiteInput;
  if (gbpInput) body.gbp_url = gbpInput;
  return coreApi.patchAgentSession(sessionId, body).then((snapshot) => ({
    ...snapshot,
    crawl_started: snapshot?.crawl_status === 'in_progress',
  }));
};

const advanceSession = (sessionId, payload) =>
  coreApi.advanceAgentSession(sessionId, payload).then((res) => res?.result ?? res);

const RESEARCH_ORCHESTRATOR_AGENT_ID = 'business-research';
const phase2Path = (path) => `/phase2/${path}`;

export default function OnboardingApp() {
  const navigate = useNavigate();
  const { sessionIdRef, ensureSession } = useOnboardingSession();
  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);

  const outcomeIds = useMemo(() => outcomeOptions.map((o) => o.id), []);
  const { programmaticHoveredOutcomeId, onJourneyDirectInteraction } = useOnboardingJourneyIdleOutcomeDemo(
    !selectedOutcome,
    outcomeIds,
  );
  const { canvasRef, scrollToEnd } = useOnboardingCanvasScroll();
  const { setCrawlStatus, startCrawlPolling, waitForCrawl } = useOnboardingCrawlPolling(sessionIdRef);

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
  const [diagnosticData, setDiagnosticData] = useState(null);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [loading, setLoading] = useState(false);

  const [showPrecision, setShowPrecision] = useState(false);
  const [precisionQuestions, setPrecisionQuestions] = useState([]);
  const [precisionIndex, setPrecisionIndex] = useState(0);

  const [showComplete, setShowComplete] = useState(false);
  const [error, setError] = useState(null);

  const [showPlaybook, setShowPlaybook] = useState(false);
  const [playbookStreaming, setPlaybookStreaming] = useState(false);
  const [playbookText, setPlaybookText] = useState('');
  const [playbookDone, setPlaybookDone] = useState(false);
  const [playbookResult, setPlaybookResult] = useState(null);
  const [gapQuestions, setGapQuestions] = useState([]);
  const [gapAnswers, setGapAnswers] = useState({});
  const [showGapQuestions, setShowGapQuestions] = useState(false);

  const [showOtpModal, setShowOtpModal] = useState(false);
  const [otpVerified, setOtpVerified] = useState(false);

  const pendingStreamSidRef = useRef(null);

  const clearPostTask = () => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setEarlyTools([]);
  };

  /** After layout/paint so wide journey content (domains/tasks) is measurable for scroll width. */
  const scheduleScrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollToEnd());
    });
  }, [scrollToEnd]);

  /**
   * Single path for onboarding row fields: POST `/api/v1/onboarding` with `session_id` + any of
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
        taskSetupAdvance,
        toolContext,
      } = ui;

      if (nextOutcome !== undefined) setSelectedOutcome(nextOutcome);
      if (nextDomain !== undefined) setSelectedDomain(nextDomain);
      if (nextTask !== undefined) setSelectedTask(nextTask);
      if (clearPostTaskStages) clearPostTask();
      if (openUrlForm) {
        setShowUrlForm(true);
        setShowDeeperDive(false);
        setShowDiagnostic(false);
        setShowPrecision(false);
        setShowComplete(false);
        setToolPage(0);
      }
      if (toolContext) {
        const { tools } = getToolsForSelection(
          toolContext.outcomeId,
          toolContext.domain,
          toolContext.task,
        );
        setEarlyTools(mapToolsToEarlyTools(tools));
      }

      scheduleScrollToEnd();

      const patch = buildOnboardingPatch(fields);
      if (Object.keys(patch).length === 0) return;

      try {
        const sid = await ensureSession();
        await upsertOnboarding({ session_id: sid, ...patch });
        if (taskSetupAdvance && fields.task != null) {
          advanceSession(sid, { action: 'task_setup', task: fields.task })
            .then((data) => setDiagnosticData(data))
            .catch(() => {});
        }
      } catch (err) {
        console.warn('Onboarding update:', err?.message || err);
      }
    },
    [ensureSession, scheduleScrollToEnd],
  );

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
    const fields = { task };
    if (previewOutcome) fields.outcome = previewOutcome.id;
    if (previewDomain) fields.domain = previewDomain;
    handleOnboardingFieldUpdate(fields, {
      ...(previewOutcome ? { nextOutcome: previewOutcome } : {}),
      ...(previewDomain != null ? { nextDomain: previewDomain } : {}),
      nextTask: task,
      clearPostTaskStages: true,
      openUrlForm: true,
      taskSetupAdvance: true,
      toolContext: { outcomeId: effectiveOutcome.id, domain: effectiveDomain, task },
    });
  };

  const handleUrlSubmit = async (e) => {
    e.preventDefault();
    if (!urlValue.trim() && !gbpValue.trim()) return;
    setUrlSubmitting(true);
    try {
      const sid = await ensureSession();
      const web = urlValue.trim();
      const gbp = gbpValue.trim();
      if (web || gbp) {
        const res = await patchSessionUrls(sid, { websiteInput: web || undefined, gbpInput: gbp || undefined });
        if (web && res?.crawl_started) {
          setCrawlStatus('in_progress');
          startCrawlPolling();
        }
        const patch = { session_id: sid };
        if (web) patch.website_url = web;
        if (gbp) patch.gbp_url = gbp;
        upsertOnboarding(patch).catch((e) => console.warn('onboarding DB', e));
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
      const sid = await ensureSession();
      await coreApi.patchAgentSession(sid, { skip_url: true });
      setCrawlStatus('skipped');
    } catch (err) {
      console.warn('Skip URL:', err.message);
    }
    await moveToScaleQuestions();
    setUrlSubmitting(false);
  };

  const moveToScaleQuestions = async () => {
    try {
      const sid = await ensureSession();
      const data = await advanceSession(sid, { action: 'scale_questions' });
      setScaleQuestions(data.questions || []);
    } catch {
      setScaleQuestions([]);
    }
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

  const streamPlaybook = async (sid) => {
    await coreApi.playbookGenerateStream(
      { session_id: sid },
      {
        onToken: (token) => setPlaybookText((t) => t + token),
        onDone: (result) => {
          setPlaybookResult(result);
          setPlaybookDone(true);
          setPlaybookStreaming(false);
        },
        onError: (msg) => {
          setError(msg);
          setPlaybookStreaming(false);
        },
      },
    );
  };

  const gateBeforeStream = (sid) => {
    if (otpVerified) {
      streamPlaybook(sid);
    } else {
      pendingStreamSidRef.current = sid;
      setShowOtpModal(true);
    }
  };

  const handleStartPlaybook = async () => {
    setShowPlaybook(true);
    setPlaybookStreaming(true);
    setPlaybookText('');
    setPlaybookDone(false);
    setPlaybookResult(null);
    setTimeout(scrollToEnd, 50);
    try {
      const sid = await ensureSession();
      await waitForCrawl();
      const startData = await coreApi.playbookStart({ session_id: sid });
      if (startData.gap_questions?.length) {
        setGapQuestions(startData.gap_questions_parsed || startData.gap_questions);
        setShowGapQuestions(true);
        setPlaybookStreaming(false);
        return;
      }
      gateBeforeStream(sid);
    } catch {
      setError('Failed to start playbook.');
      setPlaybookStreaming(false);
    }
  };

  const handleOtpVerified = () => {
    setOtpVerified(true);
    setShowOtpModal(false);
    const sid = pendingStreamSidRef.current;
    if (sid) streamPlaybook(sid);
  };

  const handleGapSubmit = async () => {
    setShowGapQuestions(false);
    setPlaybookStreaming(true);
    try {
      const sid = await ensureSession();
      const answersStr = gapQuestions
        .map((q, i) => {
          const qNum = typeof q === 'object' && q.id ? q.id : `Q${i + 1}`;
          return `${qNum}-${gapAnswers[i] || ''}`;
        })
        .join(', ');
      await coreApi.playbookGapAnswers({ session_id: sid, answers: answersStr });
      setPlaybookStreaming(false);
      gateBeforeStream(sid);
    } catch {
      setError('Failed to submit answers.');
      setPlaybookStreaming(false);
    }
  };

  const handleScaleSubmit = async () => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      await coreApi.patchAgentSession(sid, { scale_answers: scaleAnswers });
      const diagData = await advanceSession(sid, { action: 'start_diagnostic' });
      if (diagData.question) {
        setCurrentQuestion(diagData.question);
        setQuestionIndex(0);
      } else if (diagnosticData?.questions?.length) {
        setCurrentQuestion(diagnosticData.questions[0]);
        setQuestionIndex(0);
      }
      setShowDiagnostic(true);
      setTimeout(scrollToEnd, 50);
    } catch {
      setError('Failed to start diagnostic.');
    } finally {
      setLoading(false);
    }
  };

  const handleDiagnosticAnswer = async (answer) => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      const data = await advanceSession(sid, {
        action: 'submit_answer',
        question_index: questionIndex,
        answer,
      });
      if (data.all_answered) {
        const precData = await advanceSession(sid, { action: 'precision_questions' });
        if (precData.available && precData.questions?.length) {
          setPrecisionQuestions(precData.questions);
          setPrecisionIndex(0);
          setCurrentQuestion(precData.questions[0]);
          setShowPrecision(true);
          setTimeout(scrollToEnd, 50);
        } else {
          handleStartPlaybook();
        }
      } else if (data.next_question) {
        setCurrentQuestion(data.next_question);
        setQuestionIndex((i) => i + 1);
      }
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
      await advanceSession(sid, {
        action: 'submit_answer',
        question_index: precisionIndex,
        answer,
      });
      const nextIdx = precisionIndex + 1;
      if (nextIdx < precisionQuestions.length) {
        setPrecisionIndex(nextIdx);
        setCurrentQuestion(precisionQuestions[nextIdx]);
      } else {
        handleStartPlaybook();
      }
    } catch {
      setError('Failed to submit answer.');
    } finally {
      setLoading(false);
    }
  };

  const getWebsiteUrl = () => (urlValue || '').trim();

  const handleDeepAnalysis = () => {
    const url = getWebsiteUrl();
    const userLine = url ? `${url}\n\nDo deep analysis.` : '';
    navigate(phase2Path('new'), {
      state: {
        agentId: RESEARCH_ORCHESTRATOR_AGENT_ID,
        ...(userLine ? { initialMessage: userLine } : {}),
      },
    });
  };

  const handleBackToStep1 = () => {
    setSelectedTask(null);
    clearPostTask();
    setUrlValue('');
    setGbpValue('');
  };

  const clearError = () => setError(null);

  if (showOtpModal) {
    return <OtpModal sessionId={sessionIdRef.current || ''} onVerified={handleOtpVerified} />;
  }

  if (showPlaybook) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <PlaybookStage
          showGapQuestions={showGapQuestions}
          gapQuestions={gapQuestions}
          gapAnswers={gapAnswers}
          setGapAnswers={setGapAnswers}
          onGapSubmit={handleGapSubmit}
          playbookStreaming={playbookStreaming}
          playbookText={playbookText}
          playbookDone={playbookDone}
          playbookResult={playbookResult}
          onDeepAnalysis={handleDeepAnalysis}
        />
      </StageLayout>
    );
  }

  if (showComplete) {
    return <CompleteStage error={error} onClearError={clearError} onDeepAnalysis={handleDeepAnalysis} />;
  }

  if (showDiagnostic && currentQuestion) {
    const answerHandler = showPrecision ? handlePrecisionAnswer : handleDiagnosticAnswer;
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DiagnosticStage
          currentQuestion={currentQuestion}
          questionIndex={showPrecision ? precisionIndex : questionIndex}
          scaleAnswers={scaleAnswers}
          onAnswer={(opt) => {
            setScaleAnswers((prev) => ({ ...prev, [questionIndex]: opt }));
            answerHandler(opt);
          }}
          loading={loading}
        />
      </StageLayout>
    );
  }

  if (showDeeperDive) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeeperDiveStage
          scaleQuestions={scaleQuestions}
          scaleAnswers={scaleAnswers}
          onSelect={handleScaleSelect}
          scalePage={scalePage}
          onPageChange={setScalePage}
          onSubmit={handleScaleSubmit}
          loading={loading}
        />
      </StageLayout>
    );
  }

  if (showUrlForm) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <UrlStage
          selectedDomain={selectedDomain}
          urlValue={urlValue}
          gbpValue={gbpValue}
          onUrlChange={setUrlValue}
          onGbpChange={setGbpValue}
          urlTab={urlTab}
          onTabChange={setUrlTab}
          onSubmit={handleUrlSubmit}
          onSkip={handleUrlSkip}
          urlSubmitting={urlSubmitting}
          earlyTools={earlyTools}
          toolPage={toolPage}
          onToolPageChange={setToolPage}
          onBack={handleBackToStep1}
        />
      </StageLayout>
    );
  }

  return (
    <div className="flex h-screen max-h-screen flex-col overflow-hidden bg-[#111] bg-[radial-gradient(circle,rgba(255,255,255,0.18)_1px,transparent_1px)] bg-[length:14px_14px] font-sans text-white [&_button]:font-inherit [&_input]:font-inherit">
      <Navbar />
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
