import { useCallback, useRef } from 'react';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { mapToolsToEarlyTools } from '../toolService';

// Keys that can be patched to onboarding endpoint
const ONBOARDING_PATCH_KEYS = ['outcome', 'domain', 'task', 'website_url', 'gbp_url', 'scale_answers'];

function buildOnboardingPatch(fields) {
  const o = {};
  for (const k of ONBOARDING_PATCH_KEYS) {
    if (Object.prototype.hasOwnProperty.call(fields, k)) o[k] = fields[k];
  }
  return o;
}

const TASK_KEY_SEP = '|||';

/**
 * Hook to manage journey selection (outcome -> domain -> task)
 * and the transition animations between them.
 */
export function useJourneySelection({
  selectedOutcome,
  selectedDomain,
  setSelectedOutcome,
  setSelectedDomain,
  setSelectedTask,
  setShowUrlForm,
  setShowDeeperDive,
  setShowDiagnostic,
  setShowComplete,
  setShowTransitionMessages,
  setEarlyTools,
  setToolPage,
  setTaskNodeTransition,
  updateOnboarding,
  scrollToEnd,
}) {
  const pendingTaskNodeTransitionRef = useRef(null);
  const taskToolsCacheRef = useRef(new Map());

  const toRectObj = (r) => ({ top: r.top, left: r.left, width: r.width, height: r.height });

  const clearPostTask = useCallback(() => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowComplete(false);
    setShowTransitionMessages(false);
    setEarlyTools([]);
  }, [setShowUrlForm, setShowDeeperDive, setShowDiagnostic, setShowComplete, setShowTransitionMessages, setEarlyTools]);

  const scheduleScrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollToEnd());
    });
  }, [scrollToEnd]);

  /**
   * Single path for onboarding row field updates
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
    [updateOnboarding, scheduleScrollToEnd, clearPostTask, setSelectedOutcome, setSelectedDomain, setSelectedTask, setShowUrlForm, setShowDeeperDive, setShowDiagnostic, setShowComplete, setToolPage, setEarlyTools, setTaskNodeTransition],
  );

  const handleOutcomeClick = useCallback((outcome) => {
    handleOnboardingFieldUpdate(
      { outcome: outcome.id, domain: null, task: null },
      {
        nextOutcome: outcome,
        nextDomain: null,
        nextTask: null,
        clearPostTaskStages: true,
      },
    );
  }, [handleOnboardingFieldUpdate]);

  const handleDomainClick = useCallback((domain, previewOutcome) => {
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
  }, [handleOnboardingFieldUpdate]);

  const handleTaskClick = useCallback((task, previewOutcome, previewDomain) => {
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
  }, [selectedOutcome, selectedDomain, handleOnboardingFieldUpdate]);

  const handleBackToStep1 = useCallback(() => {
    setSelectedTask(null);
    clearPostTask();
  }, [setSelectedTask, clearPostTask]);

  return {
    pendingTaskNodeTransitionRef,
    handleOnboardingFieldUpdate,
    handleOutcomeClick,
    handleDomainClick,
    handleTaskClick,
    handleBackToStep1,
    clearPostTask,
  };
}

