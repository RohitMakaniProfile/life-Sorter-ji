import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useUiAgents } from '../context/UiAgentsContext';

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { agents, activeAgentId } = useUiAgents();
  const agentDef = agents.find((a) => a.id === activeAgentId) ?? agents[0] ?? {
    id: 'amazon-video',
    name: 'Agent',
    emoji: '🤖',
    description: '',
    allowedSkillIds: [],
  };

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 no-underline ${
      isActive
        ? 'bg-violet-50 text-violet-700 font-semibold shadow-sm'
        : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
    }`;

  return (
    <div className="flex h-screen w-full bg-slate-50 overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`${sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'} bg-white border-r border-slate-200 flex flex-col z-20 transition-all duration-300 flex-shrink-0`}
      >
        {/* Brand */}
        <div className="p-5 flex items-center gap-3 border-b border-slate-100">
          <div
            className="w-9 h-9 bg-gray-200 rounded-xl flex items-center justify-center text-white text-lg flex-shrink-0"
          >
            {agentDef.emoji}
          </div>
          <div className="min-w-0">
            <p className="font-bold text-slate-800 text-sm leading-tight truncate">{agentDef.name}</p>
            <p className="text-xs text-slate-400">Ikshan Agent</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="px-3 pt-3 space-y-1">
          <NavLink to="/chat" className={navLinkClass} end>
            <span className="text-lg">💬</span>
            <span className="text-sm">Chat</span>
          </NavLink>
          <NavLink to="/conversations" className={navLinkClass}>
            <span className="text-lg">🕒</span>
            <span className="text-sm">History</span>
          </NavLink>
          <NavLink to="/agents" className={navLinkClass}>
            <span className="text-lg">🧩</span>
            <span className="text-sm">Agents</span>
          </NavLink>
          <NavLink to="/new" className={navLinkClass}>
            <span className="text-lg">✨</span>
            <span className="text-sm">New Chat</span>
          </NavLink>
        </nav>

        {/* Sidebar body (currently empty; Agents are managed on /agents page) */}
        <div className="flex-1 px-3 pt-5 overflow-y-auto" />

        {/* Footer */}
        <div className="p-4 border-t border-slate-100">
          <div className="flex items-center gap-2 px-2 py-2 rounded-lg bg-slate-50">
            <span className="text-lg">✨</span>
            <div>
              <p className="text-xs font-semibold text-slate-700">Ikshan AI</p>
              <p className="text-[10px] text-slate-400">Local agent active</p>
            </div>
            <span className="ml-auto w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
          </div>
        </div>
      </aside>

      {/* Toggle button */}
      <button
        onClick={() => setSidebarOpen((v) => !v)}
        className="absolute left-0 top-1/2 -translate-y-1/2 z-30 w-5 h-10 bg-white border border-slate-200 rounded-r-lg flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-all shadow-sm"
        style={{ left: sidebarOpen ? '288px' : '0px', transition: 'left 0.3s' }}
      >
        {sidebarOpen ? '‹' : '›'}
      </button>

      {/* Main */}
      <main className="flex-1 relative bg-white overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_#f5f3ff_0%,_transparent_60%)] pointer-events-none" />
        <div className="relative h-full w-full">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
