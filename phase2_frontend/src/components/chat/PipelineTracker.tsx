import { useState } from 'react';
import { PIPELINE_STAGES, STAGE_LABELS } from '../../api/client';
import type { AgentId, PipelineStage, ProgressEvent } from '../../api/client';
import ActivityLog from './ActivityLog';
import { downloadReportAsPdf } from '../../utils/downloadPdf';

export interface PipelineTrackerProps {
  currentStage: PipelineStage;
  agentId?: AgentId;
  stageOutputs?: Record<string, string>;
  progressEvents?: ProgressEvent[];
  outputFile?: string;
  error?: string;
  reportContent?: string;
  onRetry?: (fromStage: PipelineStage, stageOutputs: Record<string, string>) => void;
}

type StepStatus = 'pending' | 'active' | 'done' | 'error';

function getStepStatus(
  stepStage: PipelineStage,
  currentStage: PipelineStage,
  stages: PipelineStage[],
  hasError: boolean
): StepStatus {
  const stepIdx = stages.indexOf(stepStage);
  const currentIdx = stages.indexOf(currentStage);

  // Special-case: when the pipeline is done, the "done" step should render as done,
  // not as an active spinner.
  if (currentStage === 'done' && stepStage === 'done') return 'done';

  // If we don't recognise the current stage (e.g. mismatch between agent stages),
  // fall back to pending so we don't show an infinite spinner.
  if (currentIdx < 0) return 'pending';

  if (hasError && stepIdx === currentIdx) return 'error';
  if (stepIdx < currentIdx) return 'done';
  if (stepIdx === currentIdx) return 'active';
  return 'pending';
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'done') {
    return (
      <div className="w-6 h-6 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
        <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
    );
  }
  if (status === 'active') {
    return (
      <div className="w-6 h-6 rounded-full bg-violet-600 flex items-center justify-center flex-shrink-0">
        <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (status === 'error') {
    return (
      <div className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center flex-shrink-0">
        <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </div>
    );
  }
  return (
    <div className="w-6 h-6 rounded-full bg-slate-200 flex items-center justify-center flex-shrink-0">
      <div className="w-2 h-2 rounded-full bg-slate-400" />
    </div>
  );
}

export default function PipelineTracker({
  currentStage,
  agentId,
  stageOutputs = {},
  progressEvents = [],
  outputFile,
  error,
  reportContent,
  onRetry,
}: PipelineTrackerProps) {
  const [logExpanded, setLogExpanded] = useState(true);

  const stages: PipelineStage[] = PIPELINE_STAGES;
  const labels: Record<string, string> = STAGE_LABELS;

  const hasError = currentStage === 'error';
  const isDone = currentStage === 'done';
  const hasProgress = progressEvents.length > 0;

  // ─── Parallel nodes view (for orchestrator-style stages) ────────────────────
  const isParallelStage = currentStage === ('parallel-scrape' as PipelineStage);
  const parallelEvents = progressEvents.filter((e) => e.stage === ('parallel-scrape' as PipelineStage));
  const nodes = (() => {
    if (!isParallelStage) return [];
    const known = ['bs4', 'playwright', 'firecrawl', 'agentbrowser', 'social-intel'] as const;
    const state: Record<string, { name: string; status: 'pending' | 'running' | 'done' | 'error'; detail?: string }> =
      Object.fromEntries(
        known.map((k) => [k, { name: k, status: 'pending' as const }])
      );

    for (const ev of parallelEvents) {
      const msg = ev.message.toLowerCase();
      const hit =
        known.find((k) => msg.includes(k.replace('-', ''))) ??
        (msg.includes('social') ? 'social-intel' : undefined);
      if (!hit) continue;
      if (msg.includes('starting')) state[hit] = { ...state[hit], status: 'running', detail: ev.message };
      else if (ev.type === 'done' || msg.includes('pages')) state[hit] = { ...state[hit], status: 'done', detail: ev.message };
      else if (msg.includes('failed')) state[hit] = { ...state[hit], status: 'error', detail: ev.message };
    }

    return Object.entries(state).map(([id, v]) => ({ id, ...v }));
  })();

  // Find the last successfully completed stage for retry
  const lastDoneStage = (() => {
    if (!hasError) return null;
    for (let i = stages.length - 1; i >= 0; i--) {
      const s = stages[i]!;
      if (stageOutputs[s]) return s;
    }
    return null;
  })();

  const retryFromStage = (() => {
    if (!lastDoneStage) return stages[0]!;
    const idx = stages.indexOf(lastDoneStage);
    return stages[idx + 1] ?? stages[0]!;
  })();

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 overflow-hidden">
      {/* Header row with activity log toggle */}
      <div className="flex items-center justify-between px-3 pt-2.5 pb-1">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
          Pipeline
        </span>
        {hasProgress && (
          <button
            onClick={() => setLogExpanded((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-violet-600 hover:text-violet-800 font-medium transition-colors"
          >
            <span>{logExpanded ? '▾' : '▸'}</span>
            <span>Activity log ({progressEvents.length})</span>
          </button>
        )}
      </div>

      {/* Stage steps */}
      <div className="px-3 pb-2 space-y-2">
        {stages.map((stage, i) => {
          const status = getStepStatus(stage, currentStage, stages, hasError);
          const isLast = i === stages.length - 1;

          return (
            <div key={stage} className="flex items-start gap-2.5">
              <div className="flex flex-col items-center">
                <StepIcon status={status} />
                {!isLast && (
                  <div
                    className={`w-0.5 h-4 mt-1 rounded-full ${
                      status === 'done' ? 'bg-emerald-300' : 'bg-slate-200'
                    }`}
                  />
                )}
              </div>
              <div className="flex-1 pb-1">
                <span
                  className={`text-xs font-medium ${
                    status === 'done'
                      ? 'text-emerald-700'
                      : status === 'active'
                      ? 'text-violet-700'
                      : status === 'error'
                      ? 'text-red-600'
                      : 'text-slate-400'
                  }`}
                >
                  {labels[stage] ?? stage}
                </span>
                {status === 'active' && (
                  <span className="ml-2 text-[10px] text-violet-500 animate-pulse">running…</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Parallel node graph (simple) */}
      {isParallelStage && nodes.length > 0 && (
        <div className="px-3 pb-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-2">
            Parallel tasks
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {nodes.map((n) => (
              <div
                key={n.id}
                className={`rounded-lg border px-3 py-2 ${
                  n.status === 'done'
                    ? 'border-emerald-200 bg-emerald-50'
                    : n.status === 'running'
                    ? 'border-violet-200 bg-violet-50'
                    : n.status === 'error'
                    ? 'border-red-200 bg-red-50'
                    : 'border-slate-200 bg-white'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-slate-800">{n.name}</div>
                  <div className="text-[10px] font-medium text-slate-500">
                    {n.status === 'running' ? 'running…' : n.status}
                  </div>
                </div>
                {n.detail && <div className="mt-1 text-[10px] text-slate-500 line-clamp-2">{n.detail}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity log — collapsible */}
      {hasProgress && logExpanded && (
        <div className="px-3 pb-2">
          <ActivityLog
            events={progressEvents}
            currentStage={currentStage}
            stageLabels={labels}
          />
        </div>
      )}

      {/* Error banner with retry */}
      {hasError && (
        <div className="border-t border-red-200 bg-red-50 px-3 py-2.5 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-red-500 text-sm flex-shrink-0">⚠️</span>
            <p className="text-xs text-red-700 truncate">{error ?? 'Pipeline failed'}</p>
          </div>
          {onRetry && (
            <button
              onClick={() => onRetry(retryFromStage, stageOutputs)}
              className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg transition-colors"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Retry from &ldquo;{labels[retryFromStage] ?? retryFromStage}&rdquo;
            </button>
          )}
        </div>
      )}

      {/* Done banner with download (amazon-video) */}
      {isDone && outputFile && (
        <div className="border-t border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-emerald-600 text-sm">🎬</span>
            <div>
              <p className="text-xs font-semibold text-emerald-800">Video ready</p>
              <p className="text-[10px] text-emerald-600 font-mono truncate max-w-[200px]">{outputFile}</p>
            </div>
          </div>
          <a
            href={`/api/files/download?path=${encodeURIComponent(outputFile)}`}
            download
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-lg transition-colors no-underline"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Download MP4
          </a>
        </div>
      )}

      {/* Done without file — success + optional PDF download for business-research */}
      {isDone && !outputFile && (
        <div className="border-t border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-emerald-500 text-sm">✓</span>
            <p className="text-xs text-emerald-700 font-medium">
              {(agentId === 'business-research' || agentId === 'business-strategy') ? 'Research ready' : 'Completed successfully'}
            </p>
          </div>
          {(agentId === 'business-research' || agentId === 'business-strategy') && reportContent && (
            <button
              onClick={() => downloadReportAsPdf(reportContent)}
              className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 hover:bg-violet-700 active:scale-95 text-white text-xs font-semibold rounded-lg transition-all shadow-sm"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download PDF
            </button>
          )}
        </div>
      )}
    </div>
  );
}
