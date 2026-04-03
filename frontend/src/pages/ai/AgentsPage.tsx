import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUiAgents } from '../../context/UiAgentsContext';
import { getIsSuperAdmin } from '../../api/authSession';

export default function AgentsPage() {
  const navigate = useNavigate();
  const { agents, agentsLoading, skills, activeAgentId, setActiveAgentId, createAgent, updateAgent, deleteAgent } =
    useUiAgents();
  const isSuperAdmin = getIsSuperAdmin();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const isLocalEnv =
    Boolean((import.meta as any)?.env?.DEV) ||
    (typeof window !== 'undefined' &&
      (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'));
  const canCreateAgent = isLocalEnv || isSuperAdmin;

  const canEditAgent = (agent: any): boolean => {
    return isLocalEnv || isSuperAdmin;
  };

  const handleToggleSkill = (agentId: string, skillId: string) => {
    const agent = agents.find((a) => a.id === agentId);
    if (!agent) return;
    if (!canEditAgent(agent)) return;
    const exists = agent.allowedSkillIds.includes(skillId);
    const nextIds = exists
      ? agent.allowedSkillIds.filter((id) => id !== skillId)
      : [...agent.allowedSkillIds, skillId];
    updateAgent({ ...agent, allowedSkillIds: nextIds });
  };

  const handleCreate = async () => {
    if (!canCreateAgent) return;
    setCreateError(null);
    const id = `agent-${Date.now().toString(36)}`;
    try {
      await createAgent({
        id,
        name: 'New Agent',
        emoji: '🤖',
        description: 'Custom agent',
        visibility: 'private',
        allowedSkillIds: [],
      });
      setEditingId(id);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create agent');
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setDeleteError(null);
    try {
      await deleteAgent(id);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete agent');
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6 sm:p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-slate-100">Agents</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Create agents as groups of allowed skills. Agents are stored on the server; your active selection is stored in your browser.
            </p>
          </div>
          {canCreateAgent && (
            <button
              onClick={handleCreate}
              disabled={agentsLoading}
              className="flex items-center gap-2 px-4 py-2 bg-violet-600 text-white text-sm font-medium rounded-xl hover:bg-violet-700 transition-colors disabled:opacity-50"
            >
              <span>➕</span> New Agent
            </button>
          )}
        </div>

        {createError && (
          <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {createError}
          </div>
        )}
        {deleteError && (
          <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/15 text-red-300 text-sm border border-red-500/30">
            {deleteError}
          </div>
        )}

        {agentsLoading ? (
          <div className="text-center py-16 text-slate-500">
            <div className="inline-block w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin mb-3" />
            <p className="font-medium">Loading agents…</p>
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <div className="text-4xl mb-3">🤖</div>
            <p className="font-medium">No agents yet</p>
            <p className="text-sm mt-1">Create an agent and assign skills.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {agents.map((agent) => {
              const isActive = agent.id === activeAgentId;
              const canEdit = canEditAgent(agent);
              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => setActiveAgentId(agent.id)}
                  className={`text-left border rounded-xl shadow-sm p-4 w-full flex flex-col gap-3 transition-colors ${
                    isActive
                      ? 'border-violet-500 bg-violet-600 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-100 hover:border-violet-500/60 hover:bg-slate-800'
                  }`}
                >
                  <div className="flex items-center gap-3 pointer-events-none">
                    <div
                      className={`w-9 h-9 rounded-lg flex items-center justify-center text-lg border ${
                        isActive
                          ? 'bg-white/10 text-white border-white/30'
                          : 'bg-slate-800 text-slate-200 border-slate-700'
                      }`}
                    >
                      {agent.emoji}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p
                        className={`w-full text-sm font-semibold truncate ${
                          isActive ? 'text-white' : 'text-slate-100'
                        }`}
                      >
                        {agent.name}
                      </p>
                      <p
                        className={`w-full text-xs mt-0.5 line-clamp-2 ${
                          isActive ? 'text-violet-100' : 'text-slate-400'
                        }`}
                      >
                        {agent.description}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                      if (!canEdit) return;
                      setEditingId(agent.id);
                      }}
                      className={`px-3 py-1.5 text-[11px] font-medium rounded-lg border transition-colors pointer-events-auto ${
                        isActive
                          ? 'border-white/40 text-white hover:bg-white/10'
                          : 'border-violet-500/40 text-violet-300 hover:bg-violet-500/10'
                      }`}
                    disabled={!canEdit}
                    >
                    {!canEdit ? 'Read-only' : 'Edit skills'}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                      if (!canEdit) return;
                      navigate(`/admin/agents/${encodeURIComponent(agent.id)}/contexts`);
                      }}
                      className={`px-3 py-1.5 text-[11px] font-medium rounded-lg border transition-colors pointer-events-auto ${
                        isActive
                          ? 'border-white/40 text-white hover:bg-white/10'
                          : 'border-slate-600 text-slate-300 hover:bg-slate-800'
                      }`}
                    disabled={!canEdit}
                    >
                      Contexts
                    </button>
                    <button
                      type="button"
                      onClick={(e) => handleDelete(e, agent.id)}
                      className={`p-2 rounded-lg transition-colors pointer-events-auto ${
                        isActive
                          ? 'text-violet-100 hover:text-red-100 hover:bg-white/10'
                          : 'text-slate-500 hover:text-red-300 hover:bg-red-500/10'
                      }`}
                      title="Delete agent"
                    disabled={!canEdit}
                    >
                      ✕
                    </button>
                  </div>

                  <div
                    className={`flex items-center justify-between text-[11px] mt-1 ${
                      isActive ? 'text-violet-100' : 'text-slate-500'
                    }`}
                  >
                    <span>
                      ID:{' '}
                      <span
                        className={`font-mono ${
                          isActive ? 'text-violet-50' : 'text-slate-400'
                        }`}
                      >
                        {agent.id}
                      </span>
                    </span>
                    <span>
                      {agent.allowedSkillIds.length}{' '}
                      {agent.allowedSkillIds.length === 1 ? 'skill' : 'skills'} selected
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
      {/* Edit modal (name/description + skills) */}
      {editingId && (() => {
    const agent = agents.find((a) => a.id === editingId);
        if (!agent) return null;
    const canEdit = canEditAgent(agent);
        return (
          <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
            <div className="bg-slate-900 rounded-2xl shadow-xl max-w-3xl w-full max-h-[80vh] flex flex-col border border-slate-700">
              <div className="px-5 py-3 border-b border-slate-700 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <button
                    className="w-9 h-9 rounded-lg flex items-center justify-center text-lg bg-violet-600 text-white hover:bg-violet-700 transition-colors"
                    type="button"
                    onClick={() => {
                      if (!canEdit) return;
                      const next = window.prompt('Enter an emoji icon', agent.emoji || '🤖');
                      if (next && next.trim()) {
                        updateAgent({ ...agent, emoji: next.trim() });
                      }
                    }}
                    title="Change icon"
                  >
                    {agent.emoji}
                  </button>
                  <div className="min-w-0">
                    <input
                      className="w-full text-sm font-semibold text-slate-100 bg-transparent border-none focus:outline-none focus:ring-0"
                      value={agent.name}
                      onChange={(e) => {
                        if (!canEdit) return;
                        updateAgent({ ...agent, name: e.target.value });
                      }}
                      readOnly={!canEdit}
                    />
                    <input
                      className="w-full text-[11px] text-slate-400 bg-transparent border-none focus:outline-none focus:ring-0"
                      value={agent.description}
                      onChange={(e) => {
                        if (!canEdit) return;
                        updateAgent({ ...agent, description: e.target.value });
                      }}
                      readOnly={!canEdit}
                      placeholder="Short description"
                    />
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-[11px] font-semibold text-slate-300 select-none">
                    <span className="text-slate-400">Private</span>
                    <button
                      type="button"
                      disabled={!canEdit}
                      onClick={() => {
                        if (!canEdit) return;
                        const next = (agent.visibility || 'private') === 'public' ? 'private' : 'public';
                        updateAgent({ ...agent, visibility: next });
                      }}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full border transition-colors ${
                        (agent.visibility || 'private') === 'public'
                          ? 'bg-emerald-500 border-emerald-600'
                          : 'bg-slate-700 border-slate-600'
                      } ${!canEdit ? 'opacity-60 cursor-not-allowed' : ''}`}
                      aria-label="Toggle visibility"
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                          (agent.visibility || 'private') === 'public' ? 'translate-x-4' : 'translate-x-0.5'
                        }`}
                      />
                    </button>
                    <span className="text-slate-400">Public</span>
                  </label>
                </div>
                <button
                  onClick={() => setEditingId(null)}
                  className="p-2 text-slate-500 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
                >
                  ✕
                </button>
              </div>
              <div className="p-4 overflow-y-auto flex-1 space-y-4">
                {/* Skills selector */}
                <div>
                    <p className="text-[11px] uppercase tracking-widest text-slate-500 font-semibold mb-2">
                    Allowed Skills
                  </p>
                  {!canEdit ? (
                    <p className="text-xs text-slate-400">
                      This agent is locked: only super-admin can edit skills/contexts.
                    </p>
                  ) : skills.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      No skills loaded yet. Ensure backend is running and `/api/v1/ai-chat/skills` is reachable.
                    </p>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {skills.map((skill) => {
                        const checked = agent.allowedSkillIds.includes(skill.id);
                        return (
                          <label
                            key={skill.id}
                            className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-xs cursor-pointer transition-colors ${
                              checked
                                ? 'border-violet-500/50 bg-violet-500/10'
                                : 'border-slate-700 hover:border-violet-500/40 hover:bg-slate-800'
                            }`}
                          >
                              <input
                              type="checkbox"
                              className="mt-0.5 h-3 w-3 text-violet-600 border-slate-300 rounded"
                              checked={checked}
                                onChange={() => handleToggleSkill(agent.id, skill.id)}
                            />
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-sm">{skill.emoji}</span>
                                <span className="font-semibold text-slate-100 truncate">
                                  {skill.name}
                                </span>
                              </div>
                              <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">
                                {skill.description}
                              </p>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
              <div className="px-5 py-3 border-t border-slate-700 flex items-center justify-end gap-2">
                <button
                  onClick={() => setEditingId(null)}
                  className="px-3 py-1.5 text-[11px] rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        );
      })()}

    </div>
  );
}

