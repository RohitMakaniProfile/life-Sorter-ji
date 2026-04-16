import StageLayout from '../components/StageLayout';
import TransitionMessages from '../components/TransitionMessages';
import UrlStage from '../stages/UrlStage';
import DeeperDiveStage from '../stages/DeeperDiveStage';
import DiagnosticStage from '../stages/DiagnosticStage';
import WebsiteAuditStage from '../stages/WebsiteAuditStage';
import PlaybookStage from '../stages/PlaybookStage';
import HistoryPlaybookStage from '../stages/HistoryPlaybookStage';
import CompleteStage from '../stages/CompleteStage';
import PreAuditTransitionMessages from '../components/PreAuditTransitionMessages';
import PreRcaTransitionMessages from '../components/PreRcaTransitionMessages';
import DeveloperTaskStreamsPanel from '../components/DeveloperTaskStreamsPanel';
import FlowNode from '../components/FlowNode';

/**
 * Renders the appropriate onboarding stage based on current state.
 * This extracts all the conditional rendering logic from OnboardingApp.
 */
export function OnboardingStageRenderer({
  // State
  state,
  // Streaming
  playbook,
  crawl,
  // Session
  onboardingIdRef,
  // Handlers
  handlers,
  // Deep analysis
  handleDeepAnalysis,
}) {
  const {
    viewingRunId, setViewingRunId,
    showPlaybook,
    showTransitionMessages,
    showComplete,
    showDiagnostic,
    currentQuestion,
    questionIndex,
    scaleAnswers,
    showAnalysisTransition,
    rcaCalling,
    showDeeperDive,
    scaleQuestions,
    scalePage, setScalePage,
    showUrlForm,
    selectedDomain,
    selectedTask,
    urlStageTaskNodeRef,
    urlValue, setUrlValue,
    gbpValue, setGbpValue,
    urlTab, setUrlTab,
    urlSubmitting,
    earlyTools,
    toolPage, setToolPage,
    taskNodeTransition,
    loading,
    error,
    showWebsiteAudit,
    websiteAuditText,
    websiteAuditLoading,
  } = state;

  const {
    playbookStreaming,
    playbookText,
    playbookDone,
    playbookResult,
    needsManualRetry,
  } = playbook;

  const {
    crawlStreaming,
    crawlLabel,
    crawlProgress,
    crawlProgressEvents,
  } = crawl;

  const {
    startNewJourney,
    handleTransitionComplete,
    handleStartPlaybook,
    handleScaleSelect,
    handleScaleSubmit,
    handleDiagnosticAnswer,
    handleWebsiteAuditContinue,
    handleUrlSubmit,
    handleUrlSkip,
    handleBackToStep1,
    clearError,
  } = handlers;

  // History playbook view
  if (viewingRunId) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <HistoryPlaybookStage
          runId={viewingRunId}
          onBack={() => setViewingRunId(null)}
          onStartNewJourney={() => setViewingRunId(null)}
        />
      </StageLayout>
    );
  }

  // Playbook stage
  if (showPlaybook) {
    if (showTransitionMessages) {
      return (
        <StageLayout error={error} onClearError={clearError}>
          <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
          <TransitionMessages onComplete={handleTransitionComplete} isComplete={playbookDone} />
        </StageLayout>
      );
    }

    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        <PlaybookStage
          task={selectedTask}
          playbookStreaming={playbookStreaming}
          playbookText={playbookText}
          playbookDone={playbookDone}
          playbookResult={playbookResult}
          onGoHome={startNewJourney}
          showRetry={!playbookStreaming && !playbookDone && needsManualRetry}
          onRetry={() => handleStartPlaybook()}
          retryLabel="Retry Playbook"
          onRetryPlaybook={() => handleStartPlaybook()}
          onCancel={startNewJourney}
        />
      </StageLayout>
    );
  }

  // Complete stage
  if (showComplete) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        <CompleteStage error={error} onClearError={clearError} onDeepAnalysis={handleDeepAnalysis} />
      </StageLayout>
    );
  }

  // Website audit stage (after RCA)
  if (showWebsiteAudit) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        <WebsiteAuditStage
          auditText={websiteAuditText}
          loading={websiteAuditLoading}
          onContinue={handleWebsiteAuditContinue}
        />
      </StageLayout>
    );
  }

  // Diagnostic stage
  if (showDiagnostic && currentQuestion) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        <DiagnosticStage
          currentQuestion={currentQuestion}
          questionIndex={questionIndex}
          scaleAnswers={scaleAnswers}
          onAnswer={(opt) => {
            state.setScaleAnswers((prev) => ({ ...prev, [questionIndex]: opt }));
            handleDiagnosticAnswer(opt);
          }}
          loading={loading}
          onBack={() => {
            state.setShowDiagnostic(false);
            state.setShowDeeperDive(true);
          }}
        />
      </StageLayout>
    );
  }

  // Pre-audit transition (crawl running after scale submit)
  if (showAnalysisTransition) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        <PreAuditTransitionMessages crawlStreaming={crawlStreaming} crawlProgress={crawlProgress} crawlProgressEvents={crawlProgressEvents} />
      </StageLayout>
    );
  }

  // Pre-RCA transition (after audit continue click, while rcaNextQuestion API call is in flight)
  if (rcaCalling) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <PreRcaTransitionMessages />
      </StageLayout>
    );
  }

  // Deeper dive stage
  if (showDeeperDive) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        <DeeperDiveStage
          scaleQuestions={scaleQuestions}
          scaleAnswers={scaleAnswers}
          onSelect={handleScaleSelect}
          scalePage={scalePage}
          onPageChange={setScalePage}
          onSubmit={handleScaleSubmit}
          onBack={() => { state.setShowDeeperDive(false); state.setShowUrlForm(true); }}
          loading={loading}
          crawlStreaming={crawlStreaming}
          crawlLabel={crawlLabel}
          crawlProgress={crawlProgress}
        />
      </StageLayout>
    );
  }

  // URL stage
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
        <DeveloperTaskStreamsPanel onboardingId={onboardingIdRef.current} userId={null} taskTypes={['crawl', 'playbook/onboarding-generate']} />
        {taskNodeTransition && from ? (
          <div
            aria-hidden
            className="pointer-events-none fixed left-0 top-0 z-60"
            style={{
              width: from.width,
              height: from.height,
              transform: `translate(${from.left}px, ${from.top}px) translate(${phase === 'animate' ? dx : 0}px, ${phase === 'animate' ? dy : 0}px) scale(${phase === 'animate' ? sx : 1}, ${phase === 'animate' ? sy : 1})`,
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

  // Default: return null (main journey canvas will be rendered by parent)
  return null;
}
