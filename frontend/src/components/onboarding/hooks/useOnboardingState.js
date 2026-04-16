import { useState, useCallback, useRef, useEffect } from 'react';
import { outcomeOptions } from '../onboardingJourneyData';
import STATIC_SCALE_QUESTIONS from '../data/scale_questions.json';

/**
 * Initial state for the onboarding flow
 */
export const INITIAL_ONBOARDING_STATE = {
  // Journey selection
  selectedOutcome: null,
  selectedDomain: null,
  selectedTask: null,

  // URL stage
  showUrlForm: false,
  urlValue: '',
  gbpValue: '',
  urlTab: 'website',
  urlSubmitting: false,
  earlyTools: [],
  toolPage: 0,

  // Scale questions
  showDeeperDive: false,
  scaleQuestions: [],
  scaleAnswers: {},
  scalePage: 0,

  // Diagnostic/RCA
  showDiagnostic: false,
  currentQuestion: null,
  questionIndex: 0,
  loading: false,

  // Gap questions
  showGapQuestions: false,
  gapQuestions: [],
  gapAnswers: {},
  gapCurrentIndex: 0,
  gapSavingIndex: null,

  // Playbook
  showPlaybook: false,
  showTransitionMessages: false,
  checkingGapQuestions: false,

  // Analysis transition
  showAnalysisTransition: false,
  rcaCalling: false,

  // Complete
  showComplete: false,

  // Error
  error: null,
};

/**
 * Hook to manage onboarding UI state with clear reset/restore capabilities
 */
export function useOnboardingState() {
  // Journey selection
  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);

  // URL stage
  const [showUrlForm, setShowUrlForm] = useState(false);
  const [urlValue, setUrlValue] = useState('');
  const [gbpValue, setGbpValue] = useState('');
  const [urlTab, setUrlTab] = useState('website');
  const [urlSubmitting, setUrlSubmitting] = useState(false);
  const [earlyTools, setEarlyTools] = useState([]);
  const [toolPage, setToolPage] = useState(0);

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

  // Complete
  const [showComplete, setShowComplete] = useState(false);

  // Error
  const [error, setError] = useState(null);

  // Clear gap saving index after timeout
  useEffect(() => {
    if (gapSavingIndex == null) return undefined;
    const t = setTimeout(() => setGapSavingIndex(null), 3000);
    return () => clearTimeout(t);
  }, [gapSavingIndex]);

  /**
   * Reset all journey UI state to initial values
   */
  const resetJourneyUiState = useCallback(() => {
    setSelectedOutcome(null);
    setSelectedDomain(null);
    setSelectedTask(null);
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowComplete(false);
    setShowPlaybook(false);
    setShowGapQuestions(false);
    setShowTransitionMessages(false);
    setCheckingGapQuestions(false);
    setScaleAnswers({});
    setGapAnswers({});
    setGapCurrentIndex(0);
    setGapSavingIndex(null);
    setCurrentQuestion(null);
    setQuestionIndex(0);
  }, []);

  /**
   * Clear post-task stages (everything after task selection)
   */
  const clearPostTaskStages = useCallback(() => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowComplete(false);
    setShowTransitionMessages(false);
    setCheckingGapQuestions(false);
    setEarlyTools([]);
  }, []);

  /**
   * Restore state from backend session data
   */
  const restoreFromState = useCallback((state) => {
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
      const indexedAnswers = {};
      for (let i = 0; i < STATIC_SCALE_QUESTIONS.length; i++) {
        const q = STATIC_SCALE_QUESTIONS[i];
        if (state.scale_answers[q.id] !== undefined) {
          indexedAnswers[i] = state.scale_answers[q.id];
        }
      }
      setScaleAnswers(indexedAnswers);
    }
  }, []);

  return {
    // Journey selection
    selectedOutcome, setSelectedOutcome,
    selectedDomain, setSelectedDomain,
    selectedTask, setSelectedTask,

    // URL stage
    showUrlForm, setShowUrlForm,
    urlValue, setUrlValue,
    gbpValue, setGbpValue,
    urlTab, setUrlTab,
    urlSubmitting, setUrlSubmitting,
    earlyTools, setEarlyTools,
    toolPage, setToolPage,

    // Scale questions
    showDeeperDive, setShowDeeperDive,
    scaleQuestions, setScaleQuestions,
    scaleAnswers, setScaleAnswers,
    scalePage, setScalePage,

    // Diagnostic/RCA
    showDiagnostic, setShowDiagnostic,
    currentQuestion, setCurrentQuestion,
    questionIndex, setQuestionIndex,
    loading, setLoading,

    // Gap questions
    showGapQuestions, setShowGapQuestions,
    gapQuestions, setGapQuestions,
    gapAnswers, setGapAnswers,
    gapCurrentIndex, setGapCurrentIndex,
    gapSavingIndex, setGapSavingIndex,

    // Playbook
    showPlaybook, setShowPlaybook,
    showTransitionMessages, setShowTransitionMessages,
    checkingGapQuestions, setCheckingGapQuestions,

    // Analysis transition
    showAnalysisTransition, setShowAnalysisTransition,
    rcaCalling, setRcaCalling,

    // Complete
    showComplete, setShowComplete,

    // Error
    error, setError,

    // Actions
    resetJourneyUiState,
    clearPostTaskStages,
    restoreFromState,
  };
}

