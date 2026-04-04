import { useNavigate } from 'react-router-dom';

const PRODUCTS = [
  {
    id: 'ecom-listing-seo',
    name: 'Ecom Listing SEO',
    description: 'Improve 30-40% Revenue',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="4" width="4" height="12" rx="1" />
        <rect x="8" y="8" width="4" height="8" rx="1" />
        <rect x="14" y="2" width="4" height="14" rx="1" />
      </svg>
    ),
  },
  {
    id: 'learn-from-competitors',
    name: 'Learn from Competitors',
    description: 'Best Growth Hacks',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polyline points="2,14 6,10 10,12 18,4" strokeLinecap="round" strokeLinejoin="round" />
        <polyline points="14,4 18,4 18,8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: 'b2b-lead-gen',
    name: 'B2B Lead Gen',
    description: 'Reddit and LinkedIn Hot Leads',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="10" cy="6" r="3" />
        <path d="M4 18v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" strokeLinecap="round" />
        <path d="M16 6l2 2-2 2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: 'youtube-helper',
    name: 'Youtube Helper',
    description: 'Script + Thumbnail + Keyword Analysis',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="4" width="16" height="12" rx="2" />
        <polygon points="8,7 8,13 13,10" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    id: 'ai-team-professionals',
    name: 'AI Team Professionals',
    description: 'Marketing / Ops / HR etc',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="7" cy="6" r="2.5" />
        <circle cx="13" cy="6" r="2.5" />
        <path d="M2 18v-1.5a3.5 3.5 0 0 1 3.5-3.5h3a3.5 3.5 0 0 1 3.5 3.5V18" strokeLinecap="round" />
        <path d="M11.5 13h3a3.5 3.5 0 0 1 3.5 3.5V18" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'content-creator',
    name: 'Content Creator',
    description: 'SEO / Insta / Blogs / LinkedIn',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3 17V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5" strokeLinecap="round" />
        <path d="M7 7h6M7 10h4" strokeLinecap="round" />
        <path d="M3 13l4 4" strokeLinecap="round" />
      </svg>
    ),
  },
];

export default function ProductsSidebar({ isOpen, onClose }) {
  const navigate = useNavigate();

  const handleProductClick = (productId) => {
    // Navigate to new chat with product context
    navigate('/new', {
      state: {
        agentId: 'business_problem_identifier',
        initialMessage: `I want to use the ${PRODUCTS.find(p => p.id === productId)?.name} tool`,
      },
    });
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
          <button
            type="button"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#857BFF] text-white text-sm font-medium"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 4h12M2 8h8M2 12h10" strokeLinecap="round" />
            </svg>
            Chat
          </button>
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

        {/* Products List */}
        <div className="flex-1 overflow-y-auto py-2">
          {PRODUCTS.map((product) => (
            <button
              key={product.id}
              type="button"
              onClick={() => handleProductClick(product.id)}
              className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-white/[0.04] transition-colors group"
            >
              <div className="w-10 h-10 rounded-xl bg-[#252525] border border-white/10 flex items-center justify-center text-white/60 group-hover:text-white/80 group-hover:border-[#857BFF]/30 transition-all">
                {product.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-white truncate">{product.name}</div>
                <div className="text-xs text-white/40 truncate">{product.description}</div>
              </div>
            </button>
          ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/10">
          <button
            type="button"
            onClick={() => {
              navigate('/new');
              onClose();
            }}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-[#857BFF] to-[#BF69A2] text-white text-sm font-semibold hover:brightness-110 transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <line x1="8" y1="3" x2="8" y2="13" strokeLinecap="round" />
              <line x1="3" y1="8" x2="13" y2="8" strokeLinecap="round" />
            </svg>
            Start New Chat
          </button>
        </div>
      </aside>
    </>
  );
}

