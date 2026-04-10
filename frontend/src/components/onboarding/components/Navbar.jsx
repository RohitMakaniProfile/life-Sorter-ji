import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { coreApi } from '../../../api/services/core';
import ProductsSidebar from './ProductsSidebar';

const ONBOARDING_SESSION_KEY = 'doable-claw-onboarding-id';

function clearOnboardingStorage() {
  try {
    const toDelete = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key) continue;
      if (key.startsWith('life-sorter') || key.startsWith('doable-claw') || key.startsWith('ikshan-taskstream')) {
        toDelete.push(key);
      }
    }
    toDelete.forEach((k) => localStorage.removeItem(k));
  } catch {
    // ignore storage failures
  }
}

export default function Navbar() {
  const navigate = useNavigate();
  const [resetting, setResetting] = useState(false);
  const [productsOpen, setProductsOpen] = useState(false);

  const handleNewJourney = async () => {
    if (resetting) return;
    setResetting(true);
    try {
      const onboardingId = localStorage.getItem(ONBOARDING_SESSION_KEY);
      if (onboardingId) {
        try {
          await coreApi.onboardingReset({ onboarding_id: onboardingId });
        } catch {
          // ignore reset errors — still clear local state and restart
        }
      }
      clearOnboardingStorage();
    } catch {
      // ignore
    } finally {
      window.location.href = '/?reset=1';
    }
  };

  return (
    <>
      <ProductsSidebar isOpen={productsOpen} onClose={() => setProductsOpen(false)} />
      <nav className="relative z-10 border-b border-[rgb(45,45,45)] bg-[rgb(15,15,15)] px-2 py-1.5 md:px-6">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 flex-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <div className="flex w-max items-center gap-2 pr-1">
              <button
                type="button"
                onClick={() => setProductsOpen(true)}
                className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white"
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
                onClick={handleNewJourney}
                disabled={resetting}
                className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white disabled:opacity-50"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M13 8A5 5 0 1 1 8 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <polyline points="11,1 13,3 11,5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {resetting ? '…' : 'New Journey'}
              </button>
              <button
                type="button"
                onClick={() => navigate('/conversations')}
                className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
                History
              </button>
              <button
                type="button"
                onClick={() => navigate('/how-it-works')}
                className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-2xl border border-[rgb(40,40,40)] bg-[rgb(15,15,15)] px-2 py-1 text-[11px] whitespace-nowrap text-white/70 transition-colors hover:bg-white/[0.08] hover:text-white"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
                  <circle cx="8" cy="6.5" r="0.75" fill="currentColor" />
                  <line x1="8" y1="8.5" x2="8" y2="11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
                How It Works
              </button>
            </div>
          </div>
          <div className="hidden items-center gap-2 md:flex">
            <img src="/Doable%20Claw.svg" alt="Ikshan" className="h-6 w-auto" />
            <span className="text-sm font-bold tracking-[0.2em] text-white/80">DOABLE CLAW</span>
          </div>
        </div>
      </nav>
    </>
  );
}
