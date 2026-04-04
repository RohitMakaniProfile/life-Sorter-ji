import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUiAgents } from '../../context/UiAgentsContext';
import { checkAgentAccess } from '../../api';
import type { AgentAccessResult } from '../../api/services/core';
import type { AgentId, UiAgent } from '../../api/types';

interface AgentSelectorProps {
  onSelect: (agentId: AgentId) => void;
}

export default function AgentSelector({ onSelect }: AgentSelectorProps) {
  const { agents, agentsLoading } = useUiAgents();
  const navigate = useNavigate();

  // Per-agent access info: undefined = still loading, null = error (treat as allowed)
  const [accessMap, setAccessMap] = useState<Record<string, AgentAccessResult | null>>({});
  const [accessLoading, setAccessLoading] = useState(true);
  const [checkingAgentId, setCheckingAgentId] = useState<string | null>(null);

  // Fetch access for every agent once the agent list is available
  useEffect(() => {
    if (agentsLoading || agents.length === 0) return;
    let cancelled = false;
    setAccessLoading(true);

    Promise.all(
      agents.map(async (agent) => {
        try {
          const result = await checkAgentAccess(agent.id);
          return [agent.id, result] as const;
        } catch {
          return [agent.id, null] as const; // network error → assume allowed
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      const map: Record<string, AgentAccessResult | null> = {};
      for (const [id, result] of entries) map[id] = result;
      setAccessMap(map);
      setAccessLoading(false);
    });

    return () => { cancelled = true; };
  }, [agents, agentsLoading]);

  const handleAgentClick = async (agent: UiAgent) => {
    const access = accessMap[agent.id];

    // If we already know access is denied, redirect to payment
    if (access && !access.allowed) {
      navigate('/payment', {
        state: {
          reason: access.reason || 'A paid plan is required to use this agent.',
          requiredPlanSlug: access.required_plan_slug,
          requiredPlanName: access.required_plan_name,
          requiredPlanPrice: access.required_plan_price,
          returnTo: '/new',
          returnState: { agentId: agent.id },
        },
      });
      return;
    }

    // If access info wasn't loaded yet, do a live check
    if (access === undefined) {
      setCheckingAgentId(agent.id);
      try {
        const result = await checkAgentAccess(agent.id);
        setAccessMap((prev) => ({ ...prev, [agent.id]: result }));
        if (!result.allowed) {
          navigate('/payment', {
            state: {
              reason: result.reason || 'A paid plan is required to use this agent.',
              requiredPlanSlug: result.required_plan_slug,
              requiredPlanName: result.required_plan_name,
              requiredPlanPrice: result.required_plan_price,
              returnTo: '/new',
              returnState: { agentId: agent.id },
            },
          });
          return;
        }
      } catch {
        // If access check fails, let backend enforce later
      } finally {
        setCheckingAgentId(null);
      }
    }

    onSelect(agent.id);
  };

  if (agentsLoading || accessLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading agents…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-12">
      {/* Header */}
      <div className="flex flex-col items-center mb-10 text-center">
        <div className="w-16 h-16 bg-gradient-to-br from-violet-500/30 to-indigo-500/30 rounded-2xl flex items-center justify-center text-3xl mb-4 border border-violet-500/20 shadow-lg">
          🤖
        </div>
        <h1 className="text-2xl font-bold text-slate-100 tracking-tight">
          Start a new conversation
        </h1>
        <p className="text-sm text-slate-400 mt-2 max-w-md">
          Choose an agent to get started. Each agent has unique capabilities tailored to different tasks.
        </p>
      </div>

      {/* Agent Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl">
        {agents.map((agent: UiAgent) => {
          const access = accessMap[agent.id];
          const isLocked = access ? !access.allowed : false;
          const isChecking = checkingAgentId === agent.id;
          const priceBadge = isLocked && access?.required_plan_price
            ? `₹${access.required_plan_price}`
            : null;

          return (
            <button
              key={agent.id}
              type="button"
              disabled={isChecking}
              onClick={() => void handleAgentClick(agent)}
              className={`group relative flex flex-col items-start gap-3 p-5 rounded-2xl border transition-all duration-200 text-left cursor-pointer shadow-sm
                ${isLocked
                  ? 'border-amber-500/40 bg-slate-900/60 hover:bg-slate-800/80 hover:border-amber-400/60 hover:shadow-md hover:shadow-amber-500/5'
                  : 'border-slate-700/60 bg-slate-900/60 hover:bg-slate-800/80 hover:border-violet-500/50 hover:shadow-md hover:shadow-violet-500/5'
                }
                ${isChecking ? 'opacity-70 pointer-events-none' : ''}
              `}
            >
              {/* Emoji icon */}
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-2xl border transition-all
                ${isLocked
                  ? 'bg-gradient-to-br from-amber-500/20 to-orange-500/20 border-amber-500/10 group-hover:from-amber-500/30 group-hover:to-orange-500/30 group-hover:border-amber-500/20'
                  : 'bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border-violet-500/10 group-hover:from-violet-500/30 group-hover:to-indigo-500/30 group-hover:border-violet-500/20'
                }
              `}>
                {agent.emoji}
              </div>

              {/* Text */}
              <div className="space-y-1">
                <h3 className="text-base font-semibold text-slate-100 group-hover:text-white transition-colors flex items-center gap-2">
                  {agent.name}
                  {isLocked && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-amber-500/20 text-amber-400 border border-amber-500/30">
                      🔒 {priceBadge ?? 'Upgrade'}
                    </span>
                  )}
                </h3>
                <p className="text-xs text-slate-400 group-hover:text-slate-300 transition-colors leading-relaxed line-clamp-2">
                  {agent.description}
                </p>
              </div>

              {/* Top-right indicator */}
              <div className={`absolute top-5 right-5 transition-colors
                ${isChecking
                  ? ''
                  : isLocked
                    ? 'text-amber-500/60 group-hover:text-amber-400'
                    : 'text-slate-600 group-hover:text-violet-400'
                }
              `}>
                {isChecking ? (
                  <div className="w-4 h-4 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
                ) : isLocked ? (
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="3" y="7" width="10" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                    <path d="M5 7V5a3 3 0 0 1 6 0v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M6 3L11 8L6 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Footer hint */}
      {agents.length > 0 && (
        <p className="text-xs text-slate-600 mt-8">
          You can switch agents later from the sidebar.
        </p>
      )}

      {agents.length === 0 && (
        <div className="text-center text-slate-500">
          <p className="text-sm">No agents available.</p>
          <p className="text-xs mt-1">Please contact your administrator.</p>
        </div>
      )}
    </div>
  );
}

