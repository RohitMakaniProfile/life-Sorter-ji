import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createConversation } from '../../../api';

export default function Navbar() {
  const navigate = useNavigate();
  const [creatingChat, setCreatingChat] = useState(false);

  const handleNewChat = async () => {
    if (creatingChat) return;
    setCreatingChat(true);
    try {
      const { conversationId } = await createConversation({ agentId: 'business_problem_identifier' });
      navigate(`/chat/${conversationId}`);
    } catch {
      navigate('/new');
    } finally {
      setCreatingChat(false);
    }
  };

  return (
    <nav className="relative z-10 flex items-center justify-between border-b border-[rgb(45,45,45)] bg-[rgb(15,15,15)] px-6 py-1.5">
      <div className="flex gap-2">
        <button
          type="button"
          className="flex cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="9" y="1" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="1" y="9" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="9" y="9" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Our Products
        </button>
        <button
          type="button"
          onClick={handleNewChat}
          disabled={creatingChat}
          className="flex cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white disabled:opacity-50"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <line x1="8" y1="3" x2="8" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <line x1="3" y1="8" x2="13" y2="8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          {creatingChat ? '…' : 'New Chat'}
        </button>
        <button
          type="button"
          onClick={() => navigate('/conversations')}
          className="flex cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          History
        </button>
        <button
          type="button"
          className="flex cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="8" cy="6.5" r="0.75" fill="currentColor" />
            <line x1="8" y1="8.5" x2="8" y2="11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          How It Works
        </button>
      </div>
      <div>
        <span className="text-sm font-bold tracking-[0.2em] text-white/80">ONBOARDING</span>
      </div>
    </nav>
  );
}
