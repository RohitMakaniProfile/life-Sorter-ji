import { useEffect, useRef } from 'react';
import type { ProgressEvent, PipelineStage } from '../../api/client';

export interface ActivityLogProps {
  events: ProgressEvent[];
  currentStage: PipelineStage;
  stageLabels: Record<string, string>;
}

const TYPE_CONFIG: Record<
  ProgressEvent['type'],
  { icon: string; color: string; bg: string }
> = {
  url:    { icon: '🌐', color: 'text-blue-700',   bg: 'bg-blue-50'   },
  page:   { icon: '📄', color: 'text-slate-600',  bg: 'bg-slate-50'  },
  search: { icon: '🔍', color: 'text-violet-700', bg: 'bg-violet-50' },
  data:   { icon: '📊', color: 'text-emerald-700',bg: 'bg-emerald-50'},
  task:   { icon: '⚙️', color: 'text-amber-700',  bg: 'bg-amber-50'  },
  info:   { icon: 'ℹ️', color: 'text-slate-500',  bg: 'bg-slate-50'  },
  done:   { icon: '✓',  color: 'text-emerald-700',bg: 'bg-emerald-50'},
};

function truncate(s: string, max = 80): string {
  return s.length > max ? s.slice(0, max) + '…' : s;
}

export default function ActivityLog({ events, currentStage, stageLabels }: ActivityLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  if (events.length === 0) return null;

  // Group events by stage
  const grouped: { stage: PipelineStage; label: string; events: ProgressEvent[] }[] = [];
  for (const ev of events) {
    const last = grouped[grouped.length - 1];
    if (last && last.stage === ev.stage) {
      last.events.push(ev);
    } else {
      grouped.push({
        stage: ev.stage,
        label: stageLabels[ev.stage] ?? ev.stage,
        events: [ev],
      });
    }
  }

  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-100">
        <div className="w-1.5 h-1.5 bg-violet-500 rounded-full animate-pulse" />
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
          Live Activity
        </span>
        <span className="ml-auto text-[10px] text-slate-400">{events.length} events</span>
      </div>

      {/* Scrollable log */}
      <div className="max-h-52 overflow-y-auto">
        {grouped.map((group, gi) => (
          <div key={gi}>
            {/* Stage group header */}
            <div className="sticky top-0 z-10 flex items-center gap-1.5 px-3 py-1 bg-slate-100/80 backdrop-blur-sm border-b border-slate-200">
              <span className="text-[9px] font-bold uppercase tracking-widest text-slate-500">
                {group.label}
              </span>
              <span className="ml-auto text-[9px] text-slate-400">{group.events.length}</span>
            </div>

            {/* Events in this stage */}
            {group.events.map((ev, i) => {
              const cfg = TYPE_CONFIG[ev.type];
              return (
                <div
                  key={i}
                  className={`flex items-start gap-2 px-3 py-1.5 border-b border-slate-50 last:border-0 ${cfg.bg} hover:brightness-95 transition-all`}
                >
                  <span className="text-xs flex-shrink-0 mt-0.5 w-4 text-center">{cfg.icon}</span>
                  <div className="flex-1 min-w-0">
                    <span className={`text-[11px] leading-snug ${cfg.color} break-all`}>
                      {truncate(ev.message)}
                    </span>
                    {ev.value !== undefined && (
                      <span className="ml-2 text-[10px] font-semibold text-slate-500 tabular-nums">
                        {ev.value.toLocaleString()}{ev.unit ? ` ${ev.unit}` : ''}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Footer — currently active stage */}
      {currentStage !== 'done' && currentStage !== 'error' && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-violet-50 border-t border-violet-100">
          <div className="w-1.5 h-1.5 bg-violet-500 rounded-full animate-pulse flex-shrink-0" />
          <span className="text-[10px] text-violet-700 font-medium">
            {stageLabels[currentStage] ?? currentStage}…
          </span>
        </div>
      )}
    </div>
  );
}
