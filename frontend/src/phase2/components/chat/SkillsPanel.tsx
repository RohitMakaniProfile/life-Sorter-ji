import { PipelineState } from "../../types";

export default function SkillsPanel({
    pipeline,
  }: {
    pipeline: PipelineState | null;
  }) {
    const skills =
      pipeline?.progressEvents?.filter(
        (e) => e.meta?.kind === 'skill-call'
      ) ?? [];
  
    return (
      <div>
        <h3 className="text-sm font-semibold mb-2">Skills</h3>
  
        {skills.map((s, i) => (
          <div key={i} className="text-xs border p-2 rounded mb-2">
            {s.message}
          </div>
        ))}
      </div>
    );
  }