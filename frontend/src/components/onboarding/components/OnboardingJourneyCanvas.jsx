import { useEffect, useState } from 'react';
import FlowNode from './FlowNode';
import BranchArrows from './BranchArrows';
import { OUTCOME_DOMAINS, DOMAIN_TASKS } from '../constants';


const colBase = 'flex shrink-0 items-center justify-center px-1.5';
const nodeCol = 'flex flex-col gap-2 items-stretch';
const nodeWrap = 'relative transition-[opacity,transform] duration-300 ease-out';
const nodeWrapDimmed = 'scale-[0.96] cursor-pointer opacity-30';

/** Animates width when `open` toggles (flex `transition` cannot interpolate sibling reflow). */
function JourneyGrow({ open, children, className = '' }) {
  return (
    <div
      className={`grid min-h-0 min-w-0 overflow-hidden transition-[grid-template-columns] duration-300 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] ${className}`}
      style={{ gridTemplateColumns: open ? '1fr' : '0fr' }}
    >
      <div className="min-h-0 min-w-0">{children}</div>
    </div>
  );
}

const arrowCol = `${colBase} flex shrink-0 items-center px-0.5`;

function TaskArrowSegment({ branchDomains, branchDomainKey, tgtLabels }) {
  return (
    <div className={arrowCol}>
      <BranchArrows
        count={tgtLabels.length}
        sourceIndex={branchDomains.indexOf(branchDomainKey)}
        srcLabels={branchDomains}
        tgtLabels={tgtLabels}
      />
    </div>
  );
}

function TaskNodesColumn({
  tasks,
  selectedTask,
  onHoverTask,
  onTaskClick,
  previewOutcomeForTask,
  previewDomainForTask,
  colClassName = colBase,
  nodeColClassName = '',
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
              className={`${nodeWrap} ${selectedTask && !isSel ? nodeWrapDimmed : ''}`}
              onMouseEnter={() => !selectedTask && onHoverTask(t)}
            >
              <FlowNode
                label={t}
                variant={isSel ? 'light' : 'dark'}
                active={isSel}
                onClick={() => onTaskClick(t, previewOutcomeForTask, previewDomainForTask)}
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
}) {
  const previewOutcomeForTask =
    selectedOutcome == null && effectiveOutcome ? effectiveOutcome : undefined;
  const previewDomainForTask =
    selectedDomain == null && hoveredDomain ? hoveredDomain : undefined;

  const taskNodesProps = {
    selectedTask,
    onHoverTask,
    onTaskClick,
    previewOutcomeForTask,
    previewDomainForTask,
  };

  const taskSplit =
    branchTasks.length > 6
      ? {
          left: branchTasks.filter((_, i) => i % 2 === 0),
          right: branchTasks.filter((_, i) => i % 2 === 1),
        }
      : null;

  return (
    <>
      <div className={arrowCol}>
        <BranchArrows
          count={branchDomains.length}
          sourceIndex={outcomeOptions.findIndex((o) => o.id === effectiveOutcome.id)}
          srcLabels={outcomeOptions.map((o) => o.text)}
          srcHasSubtext
          tgtLabels={branchDomains}
        />
      </div>

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
                className={`${nodeWrap} ${dimDomain ? nodeWrapDimmed : ''}`}
                onMouseEnter={() => selectedOutcome != null && onHoverDomain(d)}
              >
                <FlowNode
                  label={d}
                  variant={domainLooksActive ? 'light' : 'dark'}
                  active={domainLooksActive}
                  onClick={() =>
                    onDomainClick(
                      d,
                      selectedOutcome == null && effectiveOutcome ? effectiveOutcome : undefined,
                    )
                  }
                />
              </div>
            );
          })}
        </div>
      </div>

      <JourneyGrow open={showTaskColumn}>
        {showTaskColumn &&
          (branchTasks.length <= 6 ? (
            <div className="flex flex-row flex-nowrap items-center">
              <TaskArrowSegment
                branchDomains={branchDomains}
                branchDomainKey={branchDomainKey}
                tgtLabels={branchTasks}
              />
              <TaskNodesColumn tasks={branchTasks} {...taskNodesProps} />
            </div>
          ) : (
            <div className="flex flex-row flex-nowrap items-center">
              <TaskArrowSegment
                branchDomains={branchDomains}
                branchDomainKey={branchDomainKey}
                tgtLabels={taskSplit.left}
              />
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

  const effectiveOutcome =
    selectedOutcome ??
    (hoveredOutcome != null ? outcomeOptions.find((o) => o.id === hoveredOutcome) ?? null : null);

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
          const isHovered = hoveredOutcome === opt.id;
          const outcomeLooksActive = isCommitted || (!selectedOutcome && isHovered);
          const dimOutcome =
            (selectedOutcome && !isCommitted) ||
            (!selectedOutcome && hoveredOutcome != null && hoveredOutcome !== opt.id);

          return (
            <div
              key={opt.id}
              className={`${nodeWrap} ${dimOutcome ? nodeWrapDimmed : ''}`}
              onMouseEnter={() => {
                setHoveredOutcome(opt.id);
                setHoveredDomain(null);
              }}
            >
              <FlowNode
                label={opt.text}
                subtext={opt.subtext}
                variant={outcomeLooksActive ? 'light' : 'dark'}
                active={outcomeLooksActive}
                onClick={() => onOutcomeClick(opt)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );

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
  };

  return (
    <div
      ref={canvasRef}
      className="min-h-0 flex-1 overflow-x-auto overflow-y-auto [scrollbar-color:rgba(255,255,255,0.12)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10"
      onMouseLeave={clearBranchHover}
    >
      <div className="flex h-full flex-row content-center items-center justify-center">
        <div className="flex shrink-0 flex-col items-center">{outcomesBlock}</div>
        <JourneyGrow open={showDomainColumn} className="max-w-full">
          {showDomainColumn ? (
            <div className="min-w-0 overflow-x-auto overflow-y-visible [scrollbar-width:thin]">
              <div className="flex flex-row flex-nowrap items-center" style={{ viewTransitionName: 'onb-branch' }}>
                <DomainAndTaskColumns {...branchProps} />
              </div>
            </div>
          ) : null}
        </JourneyGrow>
      </div>
    </div>
  );
}
