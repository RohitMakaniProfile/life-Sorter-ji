import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useUiAgents } from '../../context/UiAgentsContext';
import { IKSHAN_AUTH_TOKEN_KEY } from '../../config/authStorage';
import { getIsSuperAdmin } from '../../api/authSession';

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { agents, activeAgentId } = useUiAgents();
  const isSuperAdmin = getIsSuperAdmin();
  const AUTH_JWT_STORAGE_KEY = IKSHAN_AUTH_TOKEN_KEY;
  const ACTIVE_KEY = 'ikshan-active-agent-id';
  const agentDef = agents.find((a) => a.id === activeAgentId) ?? agents[0] ?? {
    id: 'amazon-video',
    name: 'Agent',
    emoji: '🤖',
    description: '',
    allowedSkillIds: [],
  };

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `group flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 no-underline ${
      isActive
        ? 'bg-violet-500/25 text-violet-200 font-semibold shadow-sm'
        : 'text-slate-200 hover:bg-slate-800 hover:text-white'
    }`;

  return (
    <div className="flex h-screen w-full bg-slate-950 overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`${sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'} bg-slate-900 border-r border-slate-800 flex flex-col z-20 transition-all duration-300 flex-shrink-0`}
      >
        {/* Brand */}
        <div className="p-5 flex items-center gap-3 border-b border-slate-800">
          <div
            className="w-9 h-9 bg-violet-500/25 rounded-xl flex items-center justify-center text-violet-100 text-lg flex-shrink-0"
          >
            {agentDef.emoji}
          </div>
          <div className="min-w-0">
            <p className="font-bold text-slate-100 text-sm leading-tight truncate">{agentDef.name}</p>
            <p className="text-xs text-slate-400">Ikshan Agent</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="px-3 pt-3 space-y-1">
          <NavLink to="/chat" className={navLinkClass} end>
            <span className="text-lg text-slate-200 group-hover:text-white">💬</span>
            <span className="text-sm text-slate-200 group-hover:text-white">Chat</span>
          </NavLink>
          <NavLink to="/conversations" className={navLinkClass}>
            <span className="text-lg text-slate-200 group-hover:text-white">🕒</span>
            <span className="text-sm text-slate-200 group-hover:text-white">History</span>
          </NavLink>
          <NavLink to="/account" className={navLinkClass}>
            <span className="text-lg text-slate-200 group-hover:text-white">👤</span>
            <span className="text-sm text-slate-200 group-hover:text-white">Account</span>
          </NavLink>
          {isSuperAdmin && (
            <NavLink to="/admin/agents" className={navLinkClass}>
              <span className="text-lg text-slate-200 group-hover:text-white">🧩</span>
              <span className="text-sm text-slate-200 group-hover:text-white">Agents (Edit)</span>
            </NavLink>
          )}
          {isSuperAdmin && (
            <NavLink to="/admin/observability" className={navLinkClass}>
              <span className="text-lg text-slate-200 group-hover:text-white">📈</span>
              <span className="text-sm text-slate-200 group-hover:text-white">Observability</span>
            </NavLink>
          )}
          {isSuperAdmin && (
            <NavLink to="/admin/config" className={navLinkClass}>
              <span className="text-lg text-slate-200 group-hover:text-white">⚙️</span>
              <span className="text-sm text-slate-200 group-hover:text-white">System Config</span>
            </NavLink>
          )}
          <NavLink to="/new" className={navLinkClass}>
            <span className="text-lg text-slate-200 group-hover:text-white">✨</span>
            <span className="text-sm text-slate-200 group-hover:text-white">New Chat</span>
          </NavLink>
        </nav>

        {/* Sidebar body (currently empty; Agents are managed on /agents page) */}
        <div className="flex-1 px-3 pt-5 overflow-y-auto" />

        {/* Footer */}
        <div className="p-4 border-t border-slate-800">
          <div className="flex items-center gap-2 px-2 py-2 rounded-lg bg-slate-800">
            <span className="text-lg">✨</span>
            <div>
              <p className="text-xs font-semibold text-slate-100">Ikshan AI</p>
              <p className="text-[10px] text-slate-500">Local agent active</p>
            </div>
            <span className="ml-auto w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
          </div>
          <div className="mt-3">
            <button
              type="button"
              onClick={() => {
                try {
                  window.localStorage.removeItem(AUTH_JWT_STORAGE_KEY);
                  window.localStorage.removeItem(ACTIVE_KEY);
                } catch {
                  // ignore
                }
                window.location.href = '/admin/login?mode=internal';
              }}
              className="w-full px-3 py-2 text-xs font-semibold rounded-lg border border-slate-700 text-slate-200 hover:bg-slate-800"
            >
              Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Toggle button */}
      <button
        onClick={() => setSidebarOpen((v) => !v)}
        className="absolute left-0 top-1/2 -translate-y-1/2 z-30 w-5 h-10 bg-slate-900 border border-slate-700 rounded-r-lg flex items-center justify-center text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-all shadow-sm"
        style={{ left: sidebarOpen ? '288px' : '0px', transition: 'left 0.3s' }}
      >
        {sidebarOpen ? '‹' : '›'}
      </button>

      {/* Main */}
      <main className="flex-1 relative bg-slate-950 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(139,92,246,0.18)_0%,_transparent_55%)] pointer-events-none" />
        <div className="relative h-full w-full">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
