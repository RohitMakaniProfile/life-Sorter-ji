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

  // Precision
  const [showPrecision, setShowPrecision] = useState(false);
  const [precisionQuestions, setPrecisionQuestions] = useState([]);
  const [precisionIndex, setPrecisionIndex] = useState(0);
  const [precisionAnswers, setPrecisionAnswers] = useState({});

  // Gap questions
  const [showGapQuestions, setShowGapQuestions] = useState(false);
  const [gapQuestions, setGapQuestions] = useState([]);
  const [gapAnswers, setGapAnswers] = useState({});
  const [gapCurrentIndex, setGapCurrentIndex] = useState(0);
  const [gapSavingIndex, setGapSavingIndex] = useState(null);

  // Playbook
  const [showPlaybook, setShowPlaybook] = useState(false);
  const [showTransitionMessages, setShowTransitionMessages] = useState(false);
  const [checkingGapQuestions, setCheckingGapQuestions] = useState(false);

  // Analysis transition
  const [showAnalysisTransition, setShowAnalysisTransition] = useState(false);
  const [rcaCalling, setRcaCalling] = useState(false);

  // Other
  const [showComplete, setShowComplete] = useState(false);
  const [error, setError] = useState(null);
  const [showOtpModal, setShowOtpModal] = useState(false);
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

  // Clear gap saving index after timeout
  useEffect(() => {
    if (gapSavingIndex == null) return;
    const t = setTimeout(() => setGapSavingIndex(null), 3000);
    return () => clearTimeout(t);
  }, [gapSavingIndex]);

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

  // Clear post-task stages only
  const clearPostTask = useCallback(() => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setShowTransitionMessages(false);
    setCheckingGapQuestions(false);
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

    // Precision
    showPrecision, setShowPrecision,
    precisionQuestions, setPrecisionQuestions,
    precisionIndex, setPrecisionIndex,
    precisionAnswers, setPrecisionAnswers,

    // Gap
    showGapQuestions, setShowGapQuestions,
    gapQuestions, setGapQuestions,
    gapAnswers, setGapAnswers,
    gapCurrentIndex, setGapCurrentIndex,
    gapSavingIndex, setGapSavingIndex,

    // Playbook
    showPlaybook, setShowPlaybook,
    showTransitionMessages, setShowTransitionMessages,
    checkingGapQuestions, setCheckingGapQuestions,

    // Analysis
    showAnalysisTransition, setShowAnalysisTransition,
    rcaCalling, setRcaCalling,

    // Other
    showComplete, setShowComplete,
    error, setError,
    showOtpModal, setShowOtpModal,
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

