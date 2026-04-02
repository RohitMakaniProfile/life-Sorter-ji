import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import StageLayout from './components/StageLayout';
import ScreensaverPreview from './stages/ScreensaverPreview';
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
import { useOnboardingIdleScreensaver } from './hooks/useOnboardingIdleScreensaver';
import { useOnboardingCanvasScroll } from './hooks/useOnboardingCanvasScroll';
import { useOnboardingCrawlPolling } from './hooks/useOnboardingCrawlPolling';
import { outcomeOptions } from './constants';
import { getToolsForSelection } from './toolService';
import { apiPost } from '../../api/http';
import { API_ROUTES } from '../../api/routes';
import { coreApi } from '../../api/services/core';
import { runViewTransition } from './runViewTransition';

const upsertOnboarding = (body) => apiPost(API_ROUTES.onboarding.upsert, body ?? {});

const patchUrlSubmit = (sessionId, businessUrl, gbpUrl = '') =>
  coreApi.patchAgentSession(sessionId, { business_url: businessUrl, gbp_url: gbpUrl }).then((snapshot) => ({
    ...snapshot,
    crawl_started: snapshot?.crawl_status === 'in_progress',
  }));

const advanceSession = (sessionId, payload) =>
  coreApi.advanceAgentSession(sessionId, payload).then((res) => res?.result ?? res);

const RESEARCH_ORCHESTRATOR_AGENT_ID = 'business-research';
const phase2Path = (path) => `/phase2/${path}`;

export default function OnboardingApp() {
  const navigate = useNavigate();
  const { sessionIdRef, ensureSession } = useOnboardingSession();
  const { showScreensaver, setShowScreensaver } = useOnboardingIdleScreensaver();
  const { canvasRef, scrollToEnd } = useOnboardingCanvasScroll();
  const { setCrawlStatus, startCrawlPolling, waitForCrawl } = useOnboardingCrawlPolling(sessionIdRef);

  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);

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

  const handleOutcomeClick = async (outcome) => {
    runViewTransition(() => {
      setSelectedOutcome(outcome);
      setSelectedDomain(null);
      setSelectedTask(null);
      clearPostTask();
    });
    setTimeout(scrollToEnd, typeof document !== 'undefined' && document.startViewTransition ? 320 : 50);
    try {
      const sid = await ensureSession();
      await coreApi.patchAgentSession(sid, {
        outcome: outcome.id,
        outcome_label: `${outcome.text} (${outcome.subtext})`,
      });
      upsertOnboarding({ session_id: sid, outcome: outcome.id }).catch((e) => console.warn('onboarding DB', e));
    } catch (err) {
      console.warn('Outcome submit:', err.message);
    }
  };

  /** `previewOutcome` is set when the user clicks a domain from the outcome-hover preview without selecting the outcome first. */
  const handleDomainClick = async (domain, previewOutcome) => {
    runViewTransition(() => {
      if (previewOutcome) {
        setSelectedOutcome(previewOutcome);
      }
      setSelectedDomain(domain);
      setSelectedTask(null);
      clearPostTask();
    });
    setTimeout(scrollToEnd, typeof document !== 'undefined' && document.startViewTransition ? 320 : 50);
    try {
      const sid = await ensureSession();
      if (previewOutcome) {
        await coreApi.patchAgentSession(sid, {
          outcome: previewOutcome.id,
          outcome_label: `${previewOutcome.text} (${previewOutcome.subtext})`,
        });
        upsertOnboarding({ session_id: sid, outcome: previewOutcome.id }).catch((e) =>
          console.warn('onboarding DB', e),
        );
      }
      await coreApi.patchAgentSession(sid, { domain });
      upsertOnboarding({ session_id: sid, domain }).catch((e) => console.warn('onboarding DB', e));
    } catch (err) {
      console.warn('Domain submit:', err.message);
    }
  };

  /** Optional preview args when the user clicks a task from hover previews without committing outcome/domain first. */
  const handleTaskClick = async (task, previewOutcome, previewDomain) => {
    const outcome = selectedOutcome ?? previewOutcome;
    const domain = selectedDomain ?? previewDomain;
    if (!outcome || !domain) {
      console.warn('Task click: missing outcome or domain');
      return;
    }

    runViewTransition(() => {
      if (previewOutcome) setSelectedOutcome(previewOutcome);
      if (previewDomain) setSelectedDomain(previewDomain);
      setSelectedTask(task);
      setShowUrlForm(true);
      setShowDeeperDive(false);
      setShowDiagnostic(false);
      setShowPrecision(false);
      setShowComplete(false);
      setToolPage(0);
    });
    setTimeout(scrollToEnd, typeof document !== 'undefined' && document.startViewTransition ? 320 : 50);

    const { tools } = getToolsForSelection(outcome.id, domain, task);
    if (tools.length > 0) {
      setEarlyTools(
        tools.map((t) => {
          const rawDesc = t.best_use_case || t.description || '';
          const desc = rawDesc.length > 120 ? `${rawDesc.slice(0, 117)}...` : rawDesc;
          let bullets = [];
          if (t.key_pros) {
            const raw = Array.isArray(t.key_pros)
              ? t.key_pros
              : t.key_pros
                  .split('\n')
                  .map((s) => s.replace(/^[•\-\s]+/, '').trim())
                  .filter(Boolean);
            bullets = raw.slice(0, 3).map((b) => (b.length > 70 ? `${b.slice(0, 67)}...` : b));
          }
          return {
            name: t.name,
            rating: t.rating || null,
            description: desc,
            bullets,
            tag: t.category || 'RECOMMENDED',
            url: t.url,
          };
        }),
      );
    } else {
      setEarlyTools([]);
    }

    try {
      const sid = await ensureSession();
      if (previewOutcome) {
        await coreApi.patchAgentSession(sid, {
          outcome: previewOutcome.id,
          outcome_label: `${previewOutcome.text} (${previewOutcome.subtext})`,
        });
        upsertOnboarding({ session_id: sid, outcome: previewOutcome.id }).catch((e) =>
          console.warn('onboarding DB', e),
        );
      }
      if (previewDomain) {
        await coreApi.patchAgentSession(sid, { domain: previewDomain });
        upsertOnboarding({ session_id: sid, domain: previewDomain }).catch((e) =>
          console.warn('onboarding DB', e),
        );
      }
      advanceSession(sid, { action: 'task_setup', task })
        .then((data) => setDiagnosticData(data))
        .catch(() => {});
      upsertOnboarding({ session_id: sid, task }).catch((e) => console.warn('onboarding DB', e));
    } catch (err) {
      console.warn('Task submit:', err.message);
    }
    setTimeout(scrollToEnd, 100);
  };

  const handleUrlSubmit = async (e) => {
    e.preventDefault();
    if (!urlValue.trim() && !gbpValue.trim()) return;
    setUrlSubmitting(true);
    try {
      const sid = await ensureSession();
      let websiteNorm = '';
      let gbpNorm = '';
      if (urlValue.trim()) {
        let finalUrl = urlValue.trim();
        if (!/^https?:\/\//i.test(finalUrl)) finalUrl = `https://${finalUrl}`;
        websiteNorm = finalUrl;
        const res = await patchUrlSubmit(sid, finalUrl);
        if (res?.crawl_started) {
          setCrawlStatus('in_progress');
          startCrawlPolling();
        }
      }
      if (gbpValue.trim()) {
        let finalGbp = gbpValue.trim();
        if (!/^https?:\/\//i.test(finalGbp)) finalGbp = `https://${finalGbp}`;
        gbpNorm = finalGbp;
        await patchUrlSubmit(sid, finalGbp);
      }
      if (websiteNorm || gbpNorm) {
        const patch = { session_id: sid };
        if (websiteNorm) patch.website_url = websiteNorm;
        if (gbpNorm) patch.gbp_url = gbpNorm;
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

  const getWebsiteUrl = () => {
    let u = (urlValue || '').trim();
    if (u && !/^https?:\/\//i.test(u)) u = `https://${u}`;
    return u;
  };

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
      />

      <OnboardingErrorToast error={error} onClear={clearError} />
    </div>
  );
}
