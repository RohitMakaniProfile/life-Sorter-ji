import FlowNode from './FlowNode';
import BranchArrows from './BranchArrows';
import { OUTCOME_DOMAINS, DOMAIN_TASKS } from '../constants';

const colBase = 'flex shrink-0 items-center justify-center px-1.5';
const nodeCol = 'flex flex-col gap-2 items-stretch';
const nodeWrap = 'relative transition-[opacity,transform] duration-300 ease-out';
const nodeWrapDimmed = 'scale-[0.96] cursor-pointer opacity-30';
const hoverBranch =
  'pointer-events-none absolute left-[calc(100%+4px)] top-1/2 z-50 flex -translate-y-1/2 items-center animate-[ob-branch-in_0.2s_ease]';
const hoverNodes =
  'flex max-h-[calc(100vh-140px)] flex-col gap-1.5 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden [&>*]:w-[180px] [&>*]:origin-left [&>*]:scale-[0.82]';
const animCol = `${colBase} animate-[ob-fade-in_0.4s_cubic-bezier(0.25,0.46,0.45,0.94)] [&:not(:only-child)]:my-auto`;

export default function OnboardingJourneyCanvas({
  canvasRef,
  selectedOutcome,
  selectedDomain,
  selectedTask,
  hoveredOutcome,
  hoveredDomain,
  hoveredTask,
  onHoverOutcome,
  onHoverDomain,
  onHoverTask,
  onOutcomeClick,
  onDomainClick,
  onTaskClick,
  domains,
  tasks,
  outcomeOptions,
}) {
  return (
    <div
      ref={canvasRef}
      className="min-h-0 flex-1 overflow-x-auto overflow-y-auto [scrollbar-color:rgba(255,255,255,0.12)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10"
    >
      <div
        className={
          selectedOutcome
            ? 'flex min-h-full flex-row flex-wrap items-start justify-start py-6 pb-12 pl-[max(40px,5vw)] pr-[max(40px,5vw)] [&>.ob-col-mid]:my-auto'
            : 'grid min-h-full min-w-full place-items-center'
        }
      >
        <div className={colBase}>
          <div className={nodeCol}>
            {outcomeOptions.map((opt) => {
              const isSelected = selectedOutcome?.id === opt.id;
              const isHovered = hoveredOutcome === opt.id;
              return (
                <div
                  key={opt.id}
                  className={`${nodeWrap} ${selectedOutcome && !isSelected ? nodeWrapDimmed : ''}`}
                  onMouseEnter={() => !selectedOutcome && onHoverOutcome(opt.id)}
                  onMouseLeave={() => onHoverOutcome(null)}
                >
                  <FlowNode
                    label={opt.text}
                    subtext={opt.subtext}
                    variant={isSelected ? 'light' : 'dark'}
                    active={isSelected}
                    onClick={() => onOutcomeClick(opt)}
                  />
                  {isHovered && !selectedOutcome && OUTCOME_DOMAINS[opt.id] && (
                    <div className={hoverBranch}>
                      <div className="shrink-0">
                        <BranchArrows
                          count={OUTCOME_DOMAINS[opt.id].length}
                          sourceIndex={0}
                          srcLabels={[opt.text]}
                          srcHasSubtext
                          tgtLabels={OUTCOME_DOMAINS[opt.id]}
                        />
                      </div>
                      <div className={hoverNodes}>
                        {OUTCOME_DOMAINS[opt.id].map((d) => (
                          <FlowNode key={d} label={d} variant="dark" />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {selectedOutcome && (
          <>
            <div className={`${colBase} ob-col-mid flex shrink-0 items-center px-0.5`}>
              <BranchArrows
                count={domains.length}
                sourceIndex={outcomeOptions.findIndex((o) => o.id === selectedOutcome.id)}
                srcLabels={outcomeOptions.map((o) => o.text)}
                srcHasSubtext
                tgtLabels={domains}
              />
            </div>

            <div className={`ob-col-mid ${animCol}`}>
              <div className={nodeCol}>
                {domains.map((d) => {
                  const isSel = selectedDomain === d;
                  const isHov = hoveredDomain === d;
                  return (
                    <div
                      key={d}
                      className={`${nodeWrap} ${selectedDomain && !isSel ? nodeWrapDimmed : ''}`}
                      onMouseEnter={() => !selectedDomain && onHoverDomain(d)}
                      onMouseLeave={() => onHoverDomain(null)}
                    >
                      <FlowNode
                        label={d}
                        variant={isSel ? 'light' : 'dark'}
                        active={isSel}
                        onClick={() => onDomainClick(d)}
                      />
                      {isHov && !selectedDomain && DOMAIN_TASKS[d] && (
                        <div className={hoverBranch}>
                          <div className="shrink-0">
                            <BranchArrows
                              count={DOMAIN_TASKS[d].length}
                              sourceIndex={0}
                              srcLabels={[d]}
                              tgtLabels={DOMAIN_TASKS[d]}
                            />
                          </div>
                          <div className={hoverNodes}>
                            {DOMAIN_TASKS[d].map((t) => (
                              <FlowNode key={t} label={t} variant="dark" />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {selectedDomain && (
          <>
            {tasks.length <= 6 ? (
              <>
                <div className={`${colBase} ob-col-mid flex shrink-0 items-center px-0.5`}>
                  <BranchArrows
                    count={tasks.length}
                    sourceIndex={domains.indexOf(selectedDomain)}
                    srcLabels={domains}
                    tgtLabels={tasks}
                  />
                </div>

                <div className={`ob-col-mid ${animCol}`}>
                  <div className={nodeCol}>
                    {tasks.map((t) => {
                      const isSel = selectedTask === t;
                      return (
                        <div
                          key={t}
                          className={`${nodeWrap} ${selectedTask && !isSel ? nodeWrapDimmed : ''}`}
                          onMouseEnter={() => !selectedTask && onHoverTask(t)}
                          onMouseLeave={() => onHoverTask(null)}
                        >
                          <FlowNode
                            label={t}
                            variant={isSel ? 'light' : 'dark'}
                            active={isSel}
                            onClick={() => onTaskClick(t)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : (
              <>
                {(() => {
                  const leftCol = tasks.filter((_, i) => i % 2 === 0);
                  const rightCol = tasks.filter((_, i) => i % 2 === 1);
                  return (
                    <>
                      <div className={`${colBase} ob-col-mid flex shrink-0 items-center px-0.5`}>
                        <BranchArrows
                          count={leftCol.length}
                          sourceIndex={domains.indexOf(selectedDomain)}
                          srcLabels={domains}
                          tgtLabels={leftCol}
                        />
                      </div>

                      <div className={`ob-col-mid ${animCol}`}>
                        <div className={nodeCol}>
                          {leftCol.map((t) => {
                            const isSel = selectedTask === t;
                            return (
                              <div
                                key={t}
                                className={`${nodeWrap} ${selectedTask && !isSel ? nodeWrapDimmed : ''}`}
                                onMouseEnter={() => !selectedTask && onHoverTask(t)}
                                onMouseLeave={() => onHoverTask(null)}
                              >
                                <FlowNode
                                  label={t}
                                  variant={isSel ? 'light' : 'dark'}
                                  active={isSel}
                                  onClick={() => onTaskClick(t)}
                                />
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      <div className={`ob-col-mid ${animCol} -ml-0.5 p-0`}>
                        <div className={`${nodeCol} pt-6`}>
                          {rightCol.map((t) => {
                            const isSel = selectedTask === t;
                            return (
                              <div
                                key={t}
                                className={`${nodeWrap} ${selectedTask && !isSel ? nodeWrapDimmed : ''}`}
                                onMouseEnter={() => !selectedTask && onHoverTask(t)}
                                onMouseLeave={() => onHoverTask(null)}
                              >
                                <FlowNode
                                  label={t}
                                  variant={isSel ? 'light' : 'dark'}
                                  active={isSel}
                                  onClick={() => onTaskClick(t)}
                                />
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </>
                  );
                })()}
              </>
            )}
          </>
        )}

        <div className={`${colBase} min-w-[max(200px,20vw)]`} />
      </div>
    </div>
  );
}
