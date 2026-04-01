import React, { useMemo } from 'react';
import ReactFlow, { Background, Controls, MarkerType, useNodesState } from 'reactflow';
import type { Edge, Node } from 'reactflow';
import 'reactflow/dist/style.css';

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-slate-200 rounded-xl bg-white p-4">
      <div className="font-semibold text-slate-900 mb-3">{title}</div>
      {children}
    </div>
  );
}

function DiagramBox({
  x,
  y,
  w,
  h,
  fill,
  stroke = '#cbd5e1',
  text,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
  stroke?: string;
  text: string;
}) {
  // JSX attribute string literals sometimes end up containing the literal
  // characters "\n" instead of a real newline. Normalize both cases.
  const normalized = String(text || '')
    .replaceAll('\\n', '\n')
    .replaceAll('\\t', '\t');
  const lines = normalized.split('\n').filter((l) => l.trim() !== '');
  const lineHeight = 14;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={10} fill={fill} stroke={stroke} />
      <text
        x={x + 10}
        y={y + 20}
        fontSize={11}
        fontFamily="ui-sans-serif, system-ui"
        fill="#0f172a"
      >
        {lines.map((line, i) => (
          <tspan key={i} x={x + 10} dy={i === 0 ? 0 : lineHeight}>
            {line}
          </tspan>
        ))}
      </text>
    </g>
  );
}

function SmallNote({
  x,
  y,
  text,
}: {
  x: number;
  y: number;
  text: string;
}) {
  return (
    <text x={x} y={y} fontSize={12} fontFamily="ui-sans-serif, system-ui" fill="#334155">
      {text}
    </text>
  );
}

function Arrow({
  x1,
  y1,
  x2,
  y2,
  label,
  bend = 0,
  markerId = 'arrow',
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label?: string;
  bend?: number;
  markerId?: string;
}) {
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2 + bend;
  return (
    <g>
      <path
        d={`M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`}
        fill="none"
        stroke="#94a3b8"
        strokeWidth={2}
        markerEnd={`url(#${markerId})`}
      />
      {label ? (
        <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6 - bend / 2} fontSize={12} fill="#64748b" textAnchor="middle">
          {label}
        </text>
      ) : null}
    </g>
  );
}

function DiagramLegend() {
  return (
    <div className="flex flex-wrap gap-3 text-sm text-slate-700">
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded bg-violet-100 border border-violet-200" />
        LLM call / context building
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded bg-emerald-100 border border-emerald-200" />
        Tool call (skill subprocess)
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded bg-slate-100 border border-slate-200" />
        DB/SSE state
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-3 h-3 rounded bg-amber-100 border border-amber-200" />
        Conditions / decisions
      </div>
    </div>
  );
}

export default function PlanFlowPage() {
  const makeNodeLabel = (lines: string[]) => {
    return (
      <div
        style={{
          whiteSpace: 'pre-wrap',
          fontSize: 12,
          lineHeight: 1.25,
          color: '#0f172a',
          maxWidth: '100%',
          wordBreak: 'break-word',
        }}
      >
        {lines.join('\n')}
      </div>
    );
  };

  const draftNodes = useMemo<Node[]>(
    () =>
      [
      {
        id: 'draft-user',
        position: { x: 0, y: 200 },
        data: { label: makeNodeLabel(['User message']) },
        style: { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 12, padding: 8, width: 220 },
      },
      {
        id: 'draft-plan-stream',
        position: { x: 260, y: 120 },
        data: {
          label: makeNodeLabel(['Plan create API call']),
        },
        style: { background: '#ddd6fe', border: '1px solid #c4b5fd', borderRadius: 12, padding: 8, width: 320 },
      },
      {
        id: 'draft-setup',
        position: { x: 520, y: 210 },
        data: {
          label: makeNodeLabel([
            'Resolve agent +',
            'get/create conversation',
            'append user message',
            '(create plan_run: draft)',
          ]),
        },
        style: { background: '#d1fae5', border: '1px solid #86efac', borderRadius: 12, padding: 8, width: 340 },
      },
      {
        id: 'draft-url',
        position: { x: 860, y: 205 },
        data: { label: makeNodeLabel(['URL detected?']) },
        style: { background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 12, padding: 8, width: 220 },
      },
      {
        id: 'draft-evidence',
        position: { x: 860, y: 330 },
        data: {
          label: makeNodeLabel(['YES → evidence pass (parallel)', 'business-scan', 'scrape-playwright (maxPages=1)']),
        },
        style: { background: '#d1fae5', border: '1px solid #86efac', borderRadius: 12, padding: 8, width: 340 },
      },
      {
        id: 'draft-platform-scout',
        position: { x: 630, y: 330 },
        data: { label: makeNodeLabel(['platform-scout', '(region/scope + queries)']) },
        style: { background: '#ddd6fe', border: '1px solid #c4b5fd', borderRadius: 12, padding: 8, width: 260 },
      },
      {
        id: 'draft-build-context',
        position: { x: 340, y: 430 },
        data: {
          label: makeNodeLabel([
            'Build <plan-generation-context>',
            'user request',
            'business-scan summary',
            'crawl excerpts (scrape-playwright)',
            'platform-scout JSON excerpt (when URL exists)',
          ]),
        },
        style: { background: '#ddd6fe', border: '1px solid #c4b5fd', borderRadius: 12, padding: 8, width: 520 },
      },
      {
        id: 'draft-web-search',
        position: { x: 340, y: 520 },
        data: { label: makeNodeLabel(['web-search', '(candidate URLs for plan)']) },
        style: { background: '#dbeafe', border: '1px solid #93c5fd', borderRadius: 12, padding: 8, width: 320 },
      },
      {
        id: 'draft-llm',
        position: { x: 120, y: 560 },
        data: { label: makeNodeLabel(['LLM call → planMarkdown + planJson']) },
        style: { background: '#ddd6fe', border: '1px solid #c4b5fd', borderRadius: 12, padding: 8, width: 320 },
      },
      {
        id: 'draft-persist',
        position: { x: 0, y: 560 },
        data: { label: makeNodeLabel(['Persist plan_run + update plan message', 'SSE: plan-ready']) },
        style: { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 12, padding: 8, width: 320 },
      },
      ].map((n) => ({ ...n, draggable: true, selectable: true })),
    []
  );

  const [draftNodesState, , onDraftNodesChange] = useNodesState(draftNodes);

  const draftEdges = useMemo<Edge[]>(
    () => [
      { id: 'd1', source: 'draft-user', target: 'draft-plan-stream', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'd2', source: 'draft-plan-stream', target: 'draft-setup', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'd3', source: 'draft-setup', target: 'draft-url', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'd4', source: 'draft-url', target: 'draft-evidence', markerEnd: { type: MarkerType.ArrowClosed }, label: 'YES', style: { stroke: '#86efac', strokeWidth: 2 } },
      // URL exists: evidence pass → platform-scout → build context
      { id: 'd5', source: 'draft-evidence', target: 'draft-platform-scout', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'd6', source: 'draft-platform-scout', target: 'draft-build-context', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },

      // URL missing: skip evidence/platform-scout but still build context from prompt/defaults
      { id: 'd7', source: 'draft-url', target: 'draft-build-context', markerEnd: { type: MarkerType.ArrowClosed }, label: 'NO', style: { stroke: '#f59e0b', strokeWidth: 2, strokeDasharray: '6 4' } },

      // web-search runs for candidate URLs (based on context/queries)
      { id: 'd8', source: 'draft-build-context', target: 'draft-web-search', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },

      { id: 'd9', source: 'draft-web-search', target: 'draft-llm', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'd10', source: 'draft-llm', target: 'draft-persist', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
    ],
    []
  );

  const execNodes = useMemo<Node[]>(
    () =>
      [
      {
        id: 'a-stream',
        position: { x: 0, y: 40 },
        data: { label: makeNodeLabel(['p2 chat: /api/chat/stream', 'run_agent_turn_stream']) },
        style: { background: '#dbeafe', border: '1px solid #93c5fd', borderRadius: 12, padding: 8, width: 360 },
      },
      {
        id: 'a-checklist',
        position: { x: 420, y: 40 },
        data: { label: makeNodeLabel(['Parse checklist items', 'from planMarkdown or message']) },
        style: { background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 12, padding: 8, width: 320 },
      },
      {
        id: 'a-load',
        position: { x: 0, y: 230 },
        data: { label: makeNodeLabel(['Load prior skill_calls', 'build_calls_summary (LLM)']) },
        style: { background: '#e0f2fe', border: '1px solid #38bdf8', borderRadius: 12, padding: 8, width: 440 },
      },
      {
        id: 'a-parallel',
        position: { x: 420, y: 230 },
        data: { label: makeNodeLabel(['unchecked items + parallel_limit', 'parallel_limit: 1–3']) },
        style: { background: '#d1fae5', border: '1px solid #86efac', borderRadius: 12, padding: 8, width: 380 },
      },
      {
        id: 'a-gemini-plan',
        position: { x: 860, y: 230 },
        data: { label: makeNodeLabel(['Gemini planning (LLM JSON)', 'choose parallel skillIds']) },
        style: { background: '#f5f3ff', border: '1px solid #c4b5fd', borderRadius: 12, padding: 8, width: 380 },
      },
      {
        id: 'a-extract-run',
        position: { x: 820, y: 420 },
        data: { label: makeNodeLabel(['Parallel round:', 'extract_skill_args → create_skill_call', 'run_skill → stream progress']) },
        style: { background: '#d1fae5', border: '1px solid #86efac', borderRadius: 12, padding: 8, width: 460 },
      },
      {
        id: 'a-evidence',
        position: { x: 820, y: 600 },
        data: { label: makeNodeLabel(['Skill summary LLM:', 'postprocessSummary', 'Evidence matcher → mark checklist (success only)']) },
        style: { background: '#e9d5ff', border: '1px solid #c4b5fd', borderRadius: 12, padding: 8, width: 420 },
      },
      {
        id: 'a-fallback',
        position: { x: 420, y: 420 },
        data: { label: makeNodeLabel(['No GEMINI key?', 'fallback: run_single_skill_fallback']) },
        style: { background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 12, padding: 8, width: 320 },
      },
      {
        id: 'a-final',
        position: { x: 380, y: 780 },
        data: { label: makeNodeLabel(['format_final_answer (LLM)', 'persist token usage + stage outputs', 'SSE: final text']) },
        style: { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 12, padding: 8, width: 520 },
      },
      ].map((n) => ({ ...n, draggable: true, selectable: true })),
    []
  );

  const [execNodesState, , onExecNodesChange] = useNodesState(execNodes);

  const execEdges = useMemo<Edge[]>(
    () => [
      { id: 'a1', source: 'a-stream', target: 'a-checklist', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'a2', source: 'a-checklist', target: 'a-load', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'a3', source: 'a-load', target: 'a-parallel', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
      { id: 'a4', source: 'a-parallel', target: 'a-gemini-plan', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },

      // Gemini planning: run selected skills in parallel this round
      {
        id: 'a5',
        source: 'a-gemini-plan',
        target: 'a-extract-run',
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed },
        label: 'skillIds',
        style: { stroke: '#86efac', strokeWidth: 2 },
        labelBgStyle: { fill: 'rgba(255,255,255,0.9)' },
      },

      // Gemini planning: done or no skills -> formatter
      {
        id: 'a6',
        source: 'a-gemini-plan',
        target: 'a-final',
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed },
        label: 'done / no skills',
        style: { stroke: '#94a3b8', strokeWidth: 2, strokeDasharray: '4 4' },
        labelBgStyle: { fill: 'rgba(255,255,255,0.9)' },
      },

      // Parallel skill execution
      { id: 'a7', source: 'a-extract-run', target: 'a-evidence', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },

      // Loop repeat
      { id: 'a8', source: 'a-evidence', target: 'a-gemini-plan', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, label: 'repeat', style: { stroke: '#94a3b8', strokeWidth: 2 }, labelBgStyle: { fill: 'rgba(255,255,255,0.9)' } },

      // Fallback path when GEMINI is unavailable
      {
        id: 'a9',
        source: 'a-stream',
        target: 'a-fallback',
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed },
        label: 'no GEMINI key',
        style: { stroke: '#f59e0b', strokeWidth: 2, strokeDasharray: '6 4' },
        labelBgStyle: { fill: 'rgba(255,255,255,0.9)' },
      },
      { id: 'a10', source: 'a-fallback', target: 'a-final', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 2 } },
    ],
    []
  );

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-6xl mx-auto space-y-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Plan Flow (React Flow)</h1>
          <p className="text-sm text-slate-500 mt-1">Static graphs for plan generation and agentic execution streaming flow.</p>
        </div>

        <Card title="Draft Plan — POST /api/chat/plan/stream">
          <DiagramLegend />
          <div className="mt-4" style={{ height: 520 }}>
            <ReactFlow
              nodes={draftNodesState}
              edges={draftEdges}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable
              onNodesChange={onDraftNodesChange}
              zoomOnScroll={false}
              panOnScroll={false}
              panOnDrag={false}
              fitView
            >
              <Background gap={24} size={1} />
              <Controls />
            </ReactFlow>
          </div>
        </Card>

        <Card title="Agentic Loop (Skill Extraction + Parallel Checklist) — /api/chat/stream">
          <DiagramLegend />
          <div className="mt-4" style={{ height: 760 }}>
            <ReactFlow
              nodes={execNodesState}
              edges={execEdges}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable
              onNodesChange={onExecNodesChange}
              zoomOnScroll={false}
              panOnScroll={false}
              panOnDrag={false}
              fitView
            >
              <Background gap={24} size={1} />
              <Controls />
            </ReactFlow>
          </div>
        </Card>

        <Card title="Notes">
          <div className="text-sm text-slate-700 whitespace-pre-wrap">
            {'• Draft diagram matches the plan SSE endpoint.\n'}
            {'• Agentic loop diagram matches `run_agent_turn_stream` in the backend orchestrator.\n'}
            {'• Parallel skills are selected per round from `uncheckedItems` and `parallel_limit`.\n'}
            {'• No API calls in this page (static diagrams only).'}
          </div>
        </Card>
      </div>
    </div>
  );
}

