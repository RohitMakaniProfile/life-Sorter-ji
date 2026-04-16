import { useState, useRef, useEffect, useCallback } from 'react';
import { getUserIdFromJwt } from '../../../api/authSession';

/**
 * All onboarding UI state consolidated into a single hook.
 * Returns state + setters for the entire onboarding flow.
 */
export function useOnboardingFlowState() {
  // Journey selection
  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);

  // URL stage
  const [showUrlForm, setShowUrlForm] = useState(false);
  const [toolPage, setToolPage] = useState(0);
  const [urlValue, setUrlValue] = useState('');
  const [gbpValue, setGbpValue] = useState('');
  const [urlTab, setUrlTab] = useState('website');
  const [urlSubmitting, setUrlSubmitting] = useState(false);
  const [earlyTools, setEarlyTools] = useState([]);

  // Scale questions
  const [showDeeperDive, setShowDeeperDive] = useState(false);
  const [scaleQuestions, setScaleQuestions] = useState([]);
  const [scaleAnswers, setScaleAnswers] = useState({});
  const [scalePage, setScalePage] = useState(0);

  // Diagnostic/RCA
  const [showDiagnostic, setShowDiagnostic] = useState(false);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [loading, setLoading] = useState(false);

  // Playbook
  const [showPlaybook, setShowPlaybook] = useState(false);
  const [showTransitionMessages, setShowTransitionMessages] = useState(false);

  // Analysis transition
  const [showAnalysisTransition, setShowAnalysisTransition] = useState(false);
  const [rcaCalling, setRcaCalling] = useState(false);

  // Website audit
  const [showWebsiteAudit, setShowWebsiteAudit] = useState(false);
  const [websiteAuditText, setWebsiteAuditText] = useState('');
  const [websiteAuditLoading, setWebsiteAuditLoading] = useState(false);

  // Other
  const [showComplete, setShowComplete] = useState(false);
  const [error, setError] = useState(null);
  const [otpVerified, setOtpVerified] = useState(() => Boolean(getUserIdFromJwt()));

  // History view
  const [viewingRunId, setViewingRunId] = useState(null);

  // Refs
  const pendingPlaybookLaunchRef = useRef(false);
  const pendingTaskNodeTransitionRef = useRef(null);
  const urlStageTaskNodeRef = useRef(null);
  const taskToolsCacheRef = useRef(new Map());

  // Task node transition
  const [taskNodeTransition, setTaskNodeTransition] = useState(null);

  // History playbook event listener
  useEffect(() => {
    const handler = (e) => setViewingRunId(e.detail?.runId || null);
    window.addEventListener('playbook-history-select', handler);
    return () => window.removeEventListener('playbook-history-select', handler);
  }, []);

  // Reset all UI state
  const resetAll = useCallback(() => {
    setSelectedOutcome(null);
    setSelectedDomain(null);
    setSelectedTask(null);
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowComplete(false);
    setShowPlaybook(false);
    setShowTransitionMessages(false);
    setShowWebsiteAudit(false);
    setWebsiteAuditText('');
    setScaleAnswers({});
    setCurrentQuestion(null);
    setQuestionIndex(0);
  }, []);

  // Clear post-task stages only
  const clearPostTask = useCallback(() => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowComplete(false);
    setShowTransitionMessages(false);
    setShowWebsiteAudit(false);
    setWebsiteAuditText('');
    setEarlyTools([]);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    // Journey
    selectedOutcome, setSelectedOutcome,
    selectedDomain, setSelectedDomain,
    selectedTask, setSelectedTask,

    // URL stage
    showUrlForm, setShowUrlForm,
    toolPage, setToolPage,
    urlValue, setUrlValue,
    gbpValue, setGbpValue,
    urlTab, setUrlTab,
    urlSubmitting, setUrlSubmitting,
    earlyTools, setEarlyTools,

    // Scale
    showDeeperDive, setShowDeeperDive,
    scaleQuestions, setScaleQuestions,
    scaleAnswers, setScaleAnswers,
    scalePage, setScalePage,

    // Diagnostic
    showDiagnostic, setShowDiagnostic,
    currentQuestion, setCurrentQuestion,
    questionIndex, setQuestionIndex,
    loading, setLoading,

    // Playbook
    showPlaybook, setShowPlaybook,
    showTransitionMessages, setShowTransitionMessages,

    // Analysis
    showAnalysisTransition, setShowAnalysisTransition,
    rcaCalling, setRcaCalling,

    // Website audit
    showWebsiteAudit, setShowWebsiteAudit,
    websiteAuditText, setWebsiteAuditText,
    websiteAuditLoading, setWebsiteAuditLoading,

    // Other
    showComplete, setShowComplete,
    error, setError,
    otpVerified, setOtpVerified,
    viewingRunId, setViewingRunId,

    // Refs
    pendingPlaybookLaunchRef,
    pendingTaskNodeTransitionRef,
    urlStageTaskNodeRef,
    taskToolsCacheRef,
    taskNodeTransition, setTaskNodeTransition,

    // Actions
    resetAll,
    clearPostTask,
    clearError,
  };
}
