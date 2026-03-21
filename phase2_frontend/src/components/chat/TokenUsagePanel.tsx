import { PipelineState } from "../../types";

export default function TokenUsagePanel({
    pipeline,
  }: {
    pipeline: PipelineState | null;
  }) {
    if (!pipeline) return null;
  
    return (
      <div>
        <h3 className="text-sm font-semibold mb-2">Token Usage</h3>
        <p className="text-xs text-slate-500">
          (attach from backend if needed)
        </p>
      </div>
    );
  }