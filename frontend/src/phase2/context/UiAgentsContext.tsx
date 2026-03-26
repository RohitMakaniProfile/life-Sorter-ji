import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { AgentId, SkillMeta, UiAgent } from '../api/client';
import {
  fetchSkills,
  getAgents,
  createAgent as apiCreateAgent,
  updateAgent as apiUpdateAgent,
  deleteAgent as apiDeleteAgent,
  getPhase2IsAdmin,
  getPhase2IsSuperAdmin,
  getPhase2JwtPayload,
  getPhase2JwtTokenPrefix,
} from '../api/client';

interface UiAgentsState {
  agents: UiAgent[];
  agentsLoading: boolean;
  skills: SkillMeta[];
  activeAgentId: AgentId;
  setActiveAgentId: (id: AgentId) => void;
  createAgent: (agent: UiAgent) => Promise<void>;
  updateAgent: (agent: UiAgent) => Promise<void>;
  deleteAgent: (id: AgentId) => Promise<void>;
}

const ACTIVE_KEY = 'ikshan-active-agent-id';

const UiAgentsContext = createContext<UiAgentsState | undefined>(undefined);

export type { UiAgent };

async function loadAgentsFromApi(): Promise<UiAgent[]> {
  try {
    const { agents } = await getAgents();
    return Array.isArray(agents) ? agents : [];
  } catch (error) {
    console.error('Failed to load agents:', error);
    return [];
  }
}

export function UiAgentsProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<UiAgent[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [skills, setSkills] = useState<SkillMeta[]>([]);

  const [activeAgentId, setActiveAgentIdState] = useState<AgentId>(() => {
    if (typeof window === 'undefined') return 'amazon-video';
    const stored = window.localStorage.getItem(ACTIVE_KEY);
    return (stored as AgentId) || 'amazon-video';
  });

  useEffect(() => {
    void (async () => {
      try {
        const list = await loadAgentsFromApi();
        setAgents(list);
      } finally {
        setAgentsLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    // Debug: verify role flags from the Phase2 JWT used for permission checks.
    // eslint-disable-next-line no-console
    console.log('[phase2 auth flags]', {
      isAdmin: getPhase2IsAdmin(),
      isSuperAdmin: getPhase2IsSuperAdmin(),
      jwtPayload: getPhase2JwtPayload(),
      tokenPrefix: getPhase2JwtTokenPrefix(),
    });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!agents || agentsLoading) return;
    if (!agents.length) return;
    if (!agents.some((a) => a.id === activeAgentId)) {
      const first = agents[0]?.id;
      if (first) {
        setActiveAgentIdState(first);
      }
    }
  }, [agents, agentsLoading, activeAgentId]);

  useEffect(() => {
    void (async () => {
      try {
        const list = await fetchSkills();
        setSkills(list);
      } catch (error) {
        console.error('Failed to load skills:', error);
        setSkills([]);
      }
    })();
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(ACTIVE_KEY, activeAgentId);
  }, [activeAgentId]);

  const setActiveAgentId = (id: AgentId) => {
    setActiveAgentIdState(id);
  };

  const createAgent = async (agent: UiAgent) => {
    const { agent: created } = await apiCreateAgent(agent);
    setAgents((prev) => [...prev, created]);
  };

  const updateAgent = async (agent: UiAgent) => {
    const { agent: updated } = await apiUpdateAgent(agent.id, agent);
    setAgents((prev) => prev.map((a) => (a.id === agent.id ? updated : a)));
  };

  const deleteAgent = async (id: AgentId) => {
    await apiDeleteAgent(id);
    setAgents((prev) => prev.filter((a) => a.id !== id));
    setActiveAgentIdState((current) => {
      if (current !== id) return current;
      const remaining = agents.filter((a) => a.id !== id);
      return remaining[0]?.id ?? 'amazon-video';
    });
  };

  const value: UiAgentsState = useMemo(
    () => ({
      agents,
      agentsLoading,
      skills,
      activeAgentId,
      setActiveAgentId,
      createAgent,
      updateAgent,
      deleteAgent,
    }),
    [agents, agentsLoading, skills, activeAgentId]
  );

  return <UiAgentsContext.Provider value={value}>{children}</UiAgentsContext.Provider>;
}

export function useUiAgents(): UiAgentsState {
  const ctx = useContext(UiAgentsContext);
  if (!ctx) throw new Error('useUiAgents must be used within UiAgentsProvider');
  return ctx;
}

