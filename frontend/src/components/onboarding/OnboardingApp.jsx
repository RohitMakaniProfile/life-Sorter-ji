import { useMemo, useCallback, useLayoutEffect, useEffect } from 'react';
import Navbar from './components/Navbar';
import OnboardingHero from './components/OnboardingHero';
import OnboardingJourneyCanvas from './components/OnboardingJourneyCanvas';
import OnboardingErrorToast from './components/OnboardingErrorToast';
import DeveloperTaskStreamsPanel from './components/DeveloperTaskStreamsPanel';
import { OnboardingStageRenderer } from './components/OnboardingStageRenderer';

import {
  useOnboardingSession,
  useOnboardingJourneyIdleOutcomeDemo,
  useOnboardingCanvasScroll,
  useCrawlTaskStream,
  usePlaybookTaskStream,
  usePaymentRedirect,
  useDeepAnalysis,
  useClearOnboardingStorage,
  useSessionRestore,
  useOnboardingFlowState,
  useOnboardingHandlers,
} from './hooks';

import { outcomeOptions } from './onboardingJourneyData';
import { toRectObj } from './utils/onboardingUtils';

export default function OnboardingApp() {
  // Payment redirect handling
  usePaymentRedirect();

  // Session management
  const { sessionIdRef: onboardingIdRef, ensureSession, updateOnboarding, getSessionState, clearSession } = useOnboardingSession();

  // All UI state consolidated
  const state = useOnboardingFlowState();

  // Journey idle demo
  const outcomeIds = useMemo(() => outcomeOptions.map((o) => o.id), []);
  const { programmaticHoveredOutcomeId, onJourneyDirectInteraction } = useOnboardingJourneyIdleOutcomeDemo(
    !state.selectedOutcome,
    outcomeIds,
  );

  // Canvas scroll
  const { canvasRef, scrollToEnd } = useOnboardingCanvasScroll();

  // Playbook streaming
  const playbook = usePlaybookTaskStream({
    ensureSession,
    otpVerified: state.otpVerified,
    onRequestOtp: () => state.setShowOtpModal(true),
    onShowPlaybook: () => state.setShowPlaybook(true),
    setError: state.setError,
  });

  // Crawl streaming
  const crawl = useCrawlTaskStream({ ensureSession, setError: state.setError });

  // Storage cleanup
  const { clearOnboardingClientStorage } = useClearOnboardingStorage();

  // Deep analysis
  const getWebsiteUrl = useCallback(() => (state.urlValue || '').trim(), [state.urlValue]);
  const { handleDeepAnalysis } = useDeepAnalysis({ getWebsiteUrl, setError: state.setError });

  // All handlers consolidated
  const handlers = useOnboardingHandlers({
    onboardingIdRef,
    ensureSession,
    updateOnboarding,
    clearSession,
    state,
    playbook,
    crawl,
    scrollToEnd,
    clearOnboardingClientStorage,
  });

  // Session restoration
  useSessionRestore({
    onboardingIdRef,
    getSessionState,
    setSelectedOutcome: state.setSelectedOutcome,
    setSelectedDomain: state.setSelectedDomain,
    setSelectedTask: state.setSelectedTask,
    setUrlValue: state.setUrlValue,
    setGbpValue: state.setGbpValue,
    setScaleAnswers: state.setScaleAnswers,
    setScaleQuestions: state.setScaleQuestions,
    setShowUrlForm: state.setShowUrlForm,
    setShowDeeperDive: state.setShowDeeperDive,
    setShowDiagnostic: state.setShowDiagnostic,
    setShowPrecision: state.setShowPrecision,
    setShowPlaybook: state.setShowPlaybook,
    setShowGapQuestions: state.setShowGapQuestions,
    setCurrentQuestion: state.setCurrentQuestion,
    setQuestionIndex: state.setQuestionIndex,
    setPrecisionQuestions: state.setPrecisionQuestions,
    setPrecisionIndex: state.setPrecisionIndex,
    setGapQuestions: state.setGapQuestions,
    setGapAnswers: state.setGapAnswers,
    setGapCurrentIndex: state.setGapCurrentIndex,
    setEarlyTools: state.setEarlyTools,
    clearResumeArtifacts: playbook.clearResumeArtifacts,
    clearStepReached: playbook.clearStepReached,
    prepareStreaming: playbook.prepareStreaming,
    startForSession: playbook.startForSession,
    markRetryNeeded: playbook.markRetryNeeded,
  });

  // OTP verified effect
  useEffect(() => {
    if (!state.otpVerified || !state.pendingPlaybookLaunchRef.current) return;
    state.pendingPlaybookLaunchRef.current = false;
    handlers.handleStartPlaybook({ forceVerified: true }).catch(() => {});
  }, [state.otpVerified, handlers]);

  // Task node transition animations
  useLayoutEffect(() => {
    if (!state.showUrlForm) return;
    const pending = state.taskNodeTransition;
    if (!pending || pending.toRect) return;
    const el = state.urlStageTaskNodeRef.current;
    if (!el?.getBoundingClientRect) return;

    const toRect = toRectObj(el.getBoundingClientRect());
    state.setTaskNodeTransition((prev) => (prev ? { ...prev, toRect, phase: 'enter' } : prev));
    requestAnimationFrame(() => {
      state.setTaskNodeTransition((prev) => (prev ? { ...prev, phase: 'animate' } : prev));
    });
  }, [state.showUrlForm, state.taskNodeTransition, state]);

  useLayoutEffect(() => {
    if (!state.taskNodeTransition || state.taskNodeTransition.phase !== 'animate') return;
    const t = setTimeout(() => state.setTaskNodeTransition(null), 820);
    return () => clearTimeout(t);
  }, [state.taskNodeTransition?.phase, state]);

  // Try to render a stage
  const stageContent = OnboardingStageRenderer({
    state,
    playbook,
    crawl,
    onboardingIdRef,
    handlers,
    handleDeepAnalysis,
  });

  // If a stage was rendered, return it
  if (stageContent) return stageContent;

  // Default: render main journey canvas
  return (
    <div className="flex h-screen max-h-screen flex-col overflow-hidden bg-[#111] bg-[radial-gradient(circle,rgba(255,255,255,0.18)_1px,transparent_1px)] bg-size-[14px_14px] font-sans text-white [&_button]:font-inherit [&_input]:font-inherit">
      <Navbar />
      <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
      <OnboardingHero />

      <OnboardingJourneyCanvas
        canvasRef={canvasRef}
        selectedOutcome={state.selectedOutcome}
        selectedDomain={state.selectedDomain}
        selectedTask={state.selectedTask}
        onOutcomeClick={handlers.handleOutcomeClick}
        onDomainClick={handlers.handleDomainClick}
        onTaskClick={handlers.handleTaskClick}
        outcomeOptions={outcomeOptions}
        programmaticHoveredOutcomeId={programmaticHoveredOutcomeId}
        onJourneyUserActivity={onJourneyDirectInteraction}
      />

      <OnboardingErrorToast error={state.error} onClear={handlers.clearError} />
    </div>
  );
}

