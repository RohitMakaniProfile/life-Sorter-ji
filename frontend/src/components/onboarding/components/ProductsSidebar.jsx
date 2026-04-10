import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getPlaybookHistory } from '../../../api';

export default function ProductsSidebar({ isOpen, onClose }) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [playbooks, setPlaybooks] = useState([]);

  useEffect(() => {
    if (!isOpen) return;
    let active = true;

    const load = async () => {
      setLoading(true);
      try {
        const res = await getPlaybookHistory();
        if (active) setPlaybooks(Array.isArray(res?.playbooks) ? res.playbooks : []);
      } catch {
        if (active) setPlaybooks([]);
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, [isOpen]);

  const handlePlaybookClick = (item) => {
    if (item?.runId) {
      navigate(`/playbook/${item.runId}`);
    } else {
      navigate('/');
    }
    onClose();
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity duration-300 ${
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />

      {/* Sidebar */}
      <aside
        className={`fixed top-0 left-0 z-50 h-full w-[300px] bg-[#1a1a1a] border-r border-white/10 flex flex-col transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#857BFF] text-white text-sm font-medium">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 4h12M2 8h8M2 12h10" strokeLinecap="round" />
            </svg>
            History
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center text-white/50 hover:text-white transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
              <line x1="5" y1="5" x2="15" y2="15" strokeLinecap="round" />
              <line x1="15" y1="5" x2="5" y2="15" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Playbook History */}
        <div className="flex-1 overflow-y-auto py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {loading ? (
            <div className="px-5 py-4 text-sm text-white/50">Loading playbook history...</div>
          ) : playbooks.length === 0 ? (
            <div className="px-5 py-8 text-sm text-white/40">
              No generated playbooks yet.
            </div>
          ) : (
            playbooks.map((item) => (
              <button
                key={item.runId}
                type="button"
                onClick={() => handlePlaybookClick(item)}
                className="w-full flex items-start gap-3 px-5 py-4 text-left hover:bg-white/[0.04] transition-colors group"
              >
                <div className="w-8 h-8 rounded-lg bg-[#252525] border border-white/10 flex items-center justify-center text-white/70 group-hover:border-[#857BFF]/30">
                  📘
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-white truncate">{item.companyName || item.title || 'Generated playbook'}</div>
                  <div className="text-xs text-white/40 truncate">
                    {item.task || item.domain || item.outcome || 'Playbook'}
                  </div>
                  <div className="text-[11px] text-white/30 mt-1">
                    {item.updatedAt ? new Date(item.updatedAt).toLocaleDateString() : ''}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/10">
          <button
            type="button"
            onClick={() => {
              navigate('/conversations');
              onClose();
            }}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-[#857BFF] to-[#BF69A2] text-white text-sm font-semibold hover:brightness-110 transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 4h12M2 8h8M2 12h10" strokeLinecap="round" />
            </svg>
            Chat history
          </button>
        </div>
      </aside>
    </>
  );
}

