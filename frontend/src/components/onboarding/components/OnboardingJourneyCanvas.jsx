import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import FlowNode from './FlowNode';
import JourneyConnectors from './JourneyConnectors';
import { OUTCOME_DOMAINS, DOMAIN_TASKS } from '../onboardingJourneyData';

const TASK_KEY_SEP = '|||';

/** Task lists longer than this use two staggered columns to limit vertical height. */
const TASK_SINGLE_COLUMN_MAX = 8;

const colBase = 'flex shrink-0 items-center justify-center px-1.5';
const nodeCol = 'flex flex-col gap-2 items-stretch';
const nodeWrap = 'relative transition-[opacity,transform] duration-[700ms] ease-out';
const nodeWrapDimmed = 'scale-[0.96] cursor-pointer opacity-0';

/** Animates width when `open` toggles (flex `transition` cannot interpolate sibling reflow). */
const JourneyGrow = forwardRef(function JourneyGrow({ open, children, className = '' }, ref) {
  return (
    <div
      ref={ref}
      className={`grid min-h-0 min-w-0 self-stretch overflow-hidden transition-[grid-template-columns] duration-[700ms] ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${className}`}
      style={{ gridTemplateColumns: open ? '1fr' : '0fr' }}
    >
      <div className="flex h-full min-h-0 min-w-0 items-center">{children}</div>
    </div>
  );
});
JourneyGrow.displayName = 'JourneyGrow';

const arrowCol = `${colBase} flex shrink-0 items-center px-0.5`;

function TaskArrowSpacer() {
  return <div className={`${arrowCol} w-[70px] min-w-[70px]`} aria-hidden />;
}

function TaskNodesColumn({
  tasks,
  branchDomainKey,
  selectedTask,
  onHoverTask,
  onTaskClick,
  previewOutcomeForTask,
  previewDomainForTask,
  colClassName = colBase,
  nodeColClassName = '',
  onJourneyUserActivity,
}) {
  const innerCol = nodeColClassName ? `${nodeCol} ${nodeColClassName}` : nodeCol;
  return (
    <div className={colClassName}>
      <div className={innerCol}>
        {tasks.map((t) => {
          const isSel = selectedTask === t;
          return (
            <div
              key={t}
              data-journey-anchor="task"
              data-journey-key={`${branchDomainKey}${TASK_KEY_SEP}${t}`}
              className={`${nodeWrap} ${selectedTask && !isSel ? nodeWrapDimmed : ''}`}
              onMouseEnter={() => {
                onJourneyUserActivity?.();
                if (!selectedTask) onHoverTask(t);
              }}
            >
              <FlowNode
                label={t}
                variant={isSel ? 'light' : 'dark'}
                active={isSel}
                onClick={() => {
                  onJourneyUserActivity?.();
                  onTaskClick(t, previewOutcomeForTask, previewDomainForTask);
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DomainAndTaskColumns({
  showTaskColumn,
  effectiveOutcome,
  branchDomains,
  branchDomainKey,
  branchTasks,
  outcomeOptions,
  selectedOutcome,
  selectedDomain,
  selectedTask,
  hoveredDomain,
  onHoverDomain,
  onHoverTask,
  onDomainClick,
  onTaskClick,
  onJourneyUserActivity,
}) {
  const previewOutcomeForTask =
    selectedOutcome == null && effectiveOutcome ? effectiveOutcome : undefined;
  const previewDomainForTask =
    selectedDomain == null && hoveredDomain ? hoveredDomain : undefined;

  const taskNodesProps = {
    branchDomainKey,
    selectedTask,
    onHoverTask,
    onTaskClick,
    previewOutcomeForTask,
    previewDomainForTask,
    onJourneyUserActivity,
  };

  const taskSplit =
    branchTasks.length > TASK_SINGLE_COLUMN_MAX
      ? {
          left: branchTasks.filter((_, i) => i % 2 === 0),
          right: branchTasks.filter((_, i) => i % 2 === 1),
        }
      : null;

  return (
    <>
      <div className={`${arrowCol} w-[70px] min-w-[70px]`} aria-hidden />

      <div className={colBase}>
        <div className={nodeCol}>
          {branchDomains.map((d) => {
            const isCommitted = selectedDomain === d;
            const isHovered = hoveredDomain === d;
            const domainLooksActive = isCommitted || (!selectedDomain && isHovered);
            const dimDomain =
              (selectedDomain && !isCommitted) ||
              (!selectedDomain && hoveredDomain != null && hoveredDomain !== d);

            return (
              <div
                key={d}
                data-journey-anchor="domain"
                data-journey-key={d}
                className={`${nodeWrap} ${dimDomain ? nodeWrapDimmed : ''}`}
                onMouseEnter={() => {
                  onJourneyUserActivity?.();
                  if (selectedOutcome != null) onHoverDomain(d);
                }}
              >
                <FlowNode
                  label={d}
                  variant={domainLooksActive ? 'light' : 'dark'}
                  active={domainLooksActive}
                  onClick={() => {
                    onJourneyUserActivity?.();
                    onDomainClick(
                      d,
                      selectedOutcome == null && effectiveOutcome ? effectiveOutcome : undefined,
                    );
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>

      <JourneyGrow open={showTaskColumn}>
        {showTaskColumn &&
          (branchTasks.length <= TASK_SINGLE_COLUMN_MAX ? (
            <div className="flex flex-row flex-nowrap items-center">
              <TaskArrowSpacer />
              <TaskNodesColumn tasks={branchTasks} {...taskNodesProps} />
            </div>
          ) : (
            <div className="flex flex-row flex-nowrap items-center">
              <TaskArrowSpacer />
              <TaskNodesColumn tasks={taskSplit.left} {...taskNodesProps} />
              <TaskNodesColumn
                tasks={taskSplit.right}
                colClassName={`${colBase} -ml-0.5 p-0`}
                nodeColClassName="pt-6"
                {...taskNodesProps}
              />
            </div>
          ))}
      </JourneyGrow>
    </>
  );
}

export default function OnboardingJourneyCanvas({
  canvasRef,
  selectedOutcome,
  selectedDomain,
  selectedTask,
  onOutcomeClick,
  onDomainClick,
  onTaskClick,
  outcomeOptions,
  programmaticHoveredOutcomeId = null,
  onJourneyUserActivity,
}) {
  const [hoveredOutcome, setHoveredOutcome] = useState(null);
  const [hoveredDomain, setHoveredDomain] = useState(null);
  const [, setHoveredTask] = useState(null);

  useEffect(() => {
    setHoveredOutcome(null);
  }, [selectedOutcome]);

  useEffect(() => {
    setHoveredDomain(null);
  }, [selectedDomain]);

  useEffect(() => {
    setHoveredTask(null);
  }, [selectedTask]);

  const mergedHoveredOutcomeId = hoveredOutcome ?? programmaticHoveredOutcomeId;

  const effectiveOutcome =
    selectedOutcome ??
    (mergedHoveredOutcomeId != null
      ? outcomeOptions.find((o) => o.id === mergedHoveredOutcomeId) ?? null
      : null);

  const branchDomains = effectiveOutcome ? OUTCOME_DOMAINS[effectiveOutcome.id] || [] : [];

  const branchDomainKey =
    selectedDomain || (!selectedDomain && hoveredDomain ? hoveredDomain : null);

  const branchTasks = branchDomainKey ? DOMAIN_TASKS[branchDomainKey] || [] : [];

  const showDomainColumn = !!(effectiveOutcome && branchDomains.length > 0);
  const showTaskColumn = !!(branchDomainKey && branchTasks.length > 0);

  const clearBranchHover = (e) => {
    const next = e.relatedTarget;
    if (next instanceof Node && e.currentTarget.contains(next)) return;
    setHoveredOutcome(null);
    setHoveredDomain(null);
    setHoveredTask(null);
  };

  const outcomesBlock = (
    <div className={colBase} style={{ viewTransitionName: 'onb-outcomes' }}>
      <div className={nodeCol}>
        {outcomeOptions.map((opt) => {
          const isCommitted = selectedOutcome?.id === opt.id;
          const isHovered = mergedHoveredOutcomeId === opt.id;
          const outcomeLooksActive = isCommitted || (!selectedOutcome && isHovered);
          const dimOutcome =
            (selectedOutcome && !isCommitted) ||
            (!selectedOutcome && mergedHoveredOutcomeId != null && mergedHoveredOutcomeId !== opt.id);

          return (
            <div
              key={opt.id}
              data-journey-anchor="outcome"
              data-journey-key={opt.id}
              className={`${nodeWrap} ${dimOutcome ? nodeWrapDimmed : ''}`}
              onMouseEnter={() => {
                onJourneyUserActivity?.();
                setHoveredOutcome(opt.id);
                setHoveredDomain(null);
              }}
            >
              <FlowNode
                label={opt.text}
                subtext={opt.subtext}
                variant={outcomeLooksActive ? 'light' : 'dark'}
                active={outcomeLooksActive}
                onClick={() => {
                  onJourneyUserActivity?.();
                  onOutcomeClick(opt);
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );

  const journeyLayoutRef = useRef(null);
  const journeyGrowRef = useRef(null);

  const journeyConnectorSegments = useMemo(() => {
    const segments = [];
    if (showDomainColumn && effectiveOutcome?.id && branchDomains.length > 0) {
      // After domain is committed: single arrow to selected domain only
      const domainTargets = selectedDomain ? [selectedDomain] : branchDomains;
      segments.push({
        key: 'outcome-domain',
        show: true,
        sourceType: 'outcome',
        sourceKey: effectiveOutcome.id,
        targetType: 'domain',
        targetKeys: domainTargets,
      });
    }
    if (showTaskColumn && branchDomainKey && branchTasks.length > 0) {
      // After task is committed: single arrow to selected task only
      if (selectedTask) {
        segments.push({
          key: 'domain-task',
          show: true,
          sourceType: 'domain',
          sourceKey: branchDomainKey,
          targetType: 'task',
          targetKeys: [`${branchDomainKey}${TASK_KEY_SEP}${selectedTask}`],
        });
      } else {
        const tasksWithArrows =
          branchTasks.length > TASK_SINGLE_COLUMN_MAX
            ? branchTasks.filter((_, i) => i % 2 === 0)
            : branchTasks;
        segments.push({
          key: 'domain-task',
          show: true,
          sourceType: 'domain',
          sourceKey: branchDomainKey,
          targetType: 'task',
          targetKeys: tasksWithArrows.map((t) => `${branchDomainKey}${TASK_KEY_SEP}${t}`),
        });
      }
    }
    return segments;
  }, [
    showDomainColumn,
    effectiveOutcome?.id,
    branchDomains,
    selectedDomain,
    showTaskColumn,
    branchDomainKey,
    branchTasks,
    selectedTask,
  ]);

  const branchProps = {
    showDomainColumn,
    showTaskColumn,
    effectiveOutcome,
    branchDomains,
    branchDomainKey,
    branchTasks,
    outcomeOptions,
    selectedOutcome,
    selectedDomain,
    selectedTask,
    hoveredDomain,
    onHoverDomain: setHoveredDomain,
    onHoverTask: setHoveredTask,
    onDomainClick,
    onTaskClick,
    onJourneyUserActivity,
  };

  return (
    <div
      ref={canvasRef}
      className="min-h-0 flex-1 overflow-x-auto overflow-y-auto [scrollbar-color:rgba(255,255,255,0.12)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10"
      onMouseLeave={clearBranchHover}
      onPointerDownCapture={() => onJourneyUserActivity?.()}
    >
      <div
        ref={journeyLayoutRef}
        className="relative flex min-h-full w-max min-w-full flex-1 flex-row items-stretch justify-center py-6"
      >
        <div className="relative z-10 flex shrink-0 flex-col items-center justify-center px-1.5">
          {outcomesBlock}
        </div>
        <JourneyGrow ref={journeyGrowRef} open={showDomainColumn} className="relative z-10 max-w-full">
          {showDomainColumn ? (
            <div className="min-w-0 overflow-x-auto overflow-y-visible [scrollbar-width:thin]">
              <div className="flex flex-row flex-nowrap items-center" style={{ viewTransitionName: 'onb-branch' }}>
                <DomainAndTaskColumns {...branchProps} />
              </div>
            </div>
          ) : null}
        </JourneyGrow>
        <JourneyConnectors
          rootRef={journeyLayoutRef}
          scrollRef={canvasRef}
          branchTransitionRef={journeyGrowRef}
          segments={journeyConnectorSegments}
        />
      </div>
    </div>
  );
}
