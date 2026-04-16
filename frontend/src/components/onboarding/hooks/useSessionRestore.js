import { useEffect, useRef } from 'react';
import { outcomeOptions, OUTCOME_DOMAINS } from '../onboardingJourneyData';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { mapToolsToEarlyTools } from '../toolService';
import STATIC_SCALE_QUESTIONS from '../data/scale_questions.json';
import { buildScaleQuestions } from '../utils/scaleQuestions';

/**
 * Hook to handle session restoration from backend on mount.
 * Restores UI to the appropriate stage based on saved onboarding state.
 */
export function useSessionRestore({
  onboardingIdRef,
  getSessionState,

  // State setters for restoration
  setSelectedOutcome,
  setSelectedDomain,
  setSelectedTask,
  setUrlValue,
  setGbpValue,
  setScaleAnswers,
  setScaleQuestions,
  setShowUrlForm,
  setShowDeeperDive,
  setShowDiagnostic,
  setShowPlaybook,
  setShowGapQuestions,
  setCurrentQuestion,
  setQuestionIndex,
  setGapQuestions,
  setGapAnswers,
  setGapCurrentIndex,
  setEarlyTools,
  setShowWebsiteAudit,
  setWebsiteAuditText,
  startWebsiteAuditStream,

  // Playbook stream controls
  clearResumeArtifacts,
  clearStepReached,
  prepareStreaming,
  startForSession,
  markRetryNeeded,
}) {
  const sessionRestoredRef = useRef(false);

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

      // If ?task=...&domain=... is in URL, pre-select that task and open URL form
      const preTask = urlParams.get('task');
      const preDomain = urlParams.get('domain');
      if (preTask && preDomain) {
        try { window.history.replaceState({}, '', window.location.pathname); } catch { /* ignore */ }
        const outcomeEntry = Object.entries(OUTCOME_DOMAINS).find(([, domains]) => domains.includes(preDomain));
        if (outcomeEntry) {
          const outcomeObj = outcomeOptions.find((o) => o.id === outcomeEntry[0]);
          if (outcomeObj) {
            setSelectedOutcome(outcomeObj);
            setSelectedDomain(preDomain);
            setSelectedTask(preTask);
            setShowUrlForm(true);
          }
        }
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

        let restoredEarlyTools = [];
        if (state.outcome && state.domain && state.task) {
          try {
            const toolsRes = await apiPost(API_ROUTES.onboarding.toolsByQ1Q2Q3, {
              outcome: state.outcome,
              domain: state.domain,
              task: state.task,
            });
            restoredEarlyTools = mapToolsToEarlyTools(toolsRes?.tools || []);
            if (restoredEarlyTools.length) setEarlyTools(restoredEarlyTools);
          } catch {
            // ignore tool fetch errors during restore
          }
        }
        const scaleQuestions = buildScaleQuestions(restoredEarlyTools);

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

        // Restore to the appropriate stage based on backend state
        switch (state.stage) {
          case 'url':
            clearResumeArtifacts();
            console.log('[Onboarding Restore] Restoring to URL stage', { outcome: state.outcome, domain: state.domain, task: state.task });
            setShowUrlForm(true);
            break;

          case 'questions':
            clearResumeArtifacts();
            if (state.scale_answers && Object.keys(state.scale_answers).length > 0) {
              setScaleQuestions(scaleQuestions);
              if (state.onboarding_id) {
                onboardingIdRef.current = state.onboarding_id;
              }
              setShowDeeperDive(true);
            } else {
              setScaleQuestions(scaleQuestions);
              setShowDeeperDive(true);
            }
            break;

          case 'diagnostic':
            clearResumeArtifacts();
            setScaleQuestions(scaleQuestions);
            if (state.onboarding_id) {
              onboardingIdRef.current = state.onboarding_id;
            }
            if (state.current_rca_question) {
              setCurrentQuestion(state.current_rca_question);
              const answeredCount = state.rca_qa?.filter((qa) => qa.answer)?.length || 0;
              setQuestionIndex(answeredCount);
              setShowDiagnostic(true);
            } else {
              setShowDeeperDive(true);
            }
            break;

          case 'precision':
            // Precision questions removed — restore to website_audit stage instead
            clearResumeArtifacts();
            if (state.onboarding_id) onboardingIdRef.current = state.onboarding_id;
            startWebsiteAuditStream(state.onboarding_id);
            break;

          case 'website_audit':
            clearResumeArtifacts();
            if (state.onboarding_id) onboardingIdRef.current = state.onboarding_id;
            if (state.website_audit) {
              // Audit already in DB — restore it directly
              setWebsiteAuditText(state.website_audit);
              setShowWebsiteAudit(true);
            } else {
              // Audit not yet generated — stream it
              startWebsiteAuditStream(state.onboarding_id);
            }
            break;

          case 'playbook':
          case 'complete':
            // Handled above by the early redirect check — should not reach here.
            break;

          default:
            clearResumeArtifacts();
            break;
        }
      } catch (err) {
        console.warn('Session restoration failed:', err);
      }
    };

    restoreSession();
  }, [
    clearResumeArtifacts,
    clearStepReached,
    getSessionState,
    markRetryNeeded,
    onboardingIdRef,
    prepareStreaming,
    startForSession,
    setSelectedOutcome,
    setSelectedDomain,
    setSelectedTask,
    setUrlValue,
    setGbpValue,
    setScaleAnswers,
    setScaleQuestions,
    setShowUrlForm,
    setShowDeeperDive,
    setShowDiagnostic,
    setShowPlaybook,
    setShowGapQuestions,
    setCurrentQuestion,
    setQuestionIndex,
    setGapQuestions,
    setGapAnswers,
    setGapCurrentIndex,
    setEarlyTools,
    setShowWebsiteAudit,
    setWebsiteAuditText,
    startWebsiteAuditStream,
  ]);
}

