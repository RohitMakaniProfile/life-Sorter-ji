import { useState, useEffect } from 'react';
import { Monitor, Smartphone } from 'lucide-react';

/**
 * Shows a full-screen overlay on mobile devices recommending desktop usage.
 * User can dismiss and continue on mobile if they choose.
 */
export default function MobileBlocker() {
  const [isMobile, setIsMobile] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  useEffect(() => {
    if (sessionStorage.getItem('mobile-blocker-dismissed') === 'true') {
      setDismissed(true);
    }
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    sessionStorage.setItem('mobile-blocker-dismissed', 'true');
  };


  if (!isMobile || dismissed) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[9999] bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-6">
      <div className="max-w-sm w-full text-center space-y-6">
        {/* Logo and Brand */}
        <div className="flex flex-col items-center gap-3">
          <img src="/ikshan-logo.svg" alt="Doable Claw" className="w-16 h-16" />
          <h2 className="text-xl font-bold bg-gradient-to-r from-amber-400 to-violet-400 bg-clip-text text-transparent">
            DOABLE CLAW
          </h2>
        </div>

        {/* Icon */}
        <div className="flex justify-center gap-4 items-center">
          <div className="p-4 bg-slate-700/50 rounded-2xl">
            <Smartphone className="w-10 h-10 text-slate-400" />
          </div>
          <div className="text-slate-500 text-2xl">→</div>
          <div className="p-4 bg-violet-500/20 rounded-2xl ring-2 ring-violet-500/40">
            <Monitor className="w-10 h-10 text-violet-400" />
          </div>
        </div>

        {/* Message */}
        <div className="space-y-3">
          <h1 className="text-2xl font-bold text-white">
            Best on Desktop
          </h1>
          <p className="text-slate-400 text-sm leading-relaxed">
            This app is designed for desktop use. For the best experience with
            our AI research tools and detailed reports, please visit on a
            laptop or desktop computer.
          </p>
        </div>

        {/* Continue anyway button */}
        <div className="pt-4 space-y-3">
          <button
            onClick={handleDismiss}
            className="w-full px-6 py-3 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-xl text-sm font-medium transition-colors"
          >
            Continue on Mobile Anyway
          </button>
          <p className="text-xs text-slate-500">
            Some features may not work as expected
          </p>
        </div>
      </div>
    </div>
  );
}

