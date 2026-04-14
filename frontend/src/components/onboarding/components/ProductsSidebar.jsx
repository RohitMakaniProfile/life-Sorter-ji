import { useEffect, useState } from 'react';
import { getProducts } from '../../../api';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';

export default function ProductsSidebar({ isOpen, onClose }) {
  const [loading, setLoading] = useState(false);
  const [products, setProducts] = useState([]);

  useEffect(() => {
    if (!isOpen) return;
    let active = true;

    const load = async () => {
      setLoading(true);
      try {
        const res = await getProducts({ activeOnly: true });
        if (active) setProducts(Array.isArray(res?.products) ? res.products : []);
      } catch {
        if (active) setProducts([]);
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, [isOpen]);

  const handleProductClick = async (item) => {
    onClose();

    let onboarding = null;
    try {
      onboarding = await apiPost(API_ROUTES.onboarding.fromProduct, { product_id: item?.id });
    } catch {
      // Fall back to basic flow without pre-created onboarding
    }

    window.dispatchEvent(
      new CustomEvent('onboarding-product-select', {
        detail: {
          productId: item?.id,
          outcome: item?.outcome,
          domain: item?.domain,
          task: item?.task,
          onboarding,
        },
      }),
    );
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

      <aside
        className={`fixed top-0 left-0 z-50 h-full w-[300px] bg-[#1a1a1a] border-r border-white/10 flex flex-col transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#857BFF] text-white text-sm font-medium">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="1" y="1" width="6" height="6" rx="1" />
              <rect x="9" y="1" width="6" height="6" rx="1" />
              <rect x="1" y="9" width="6" height="6" rx="1" />
              <rect x="9" y="9" width="6" height="6" rx="1" />
            </svg>
            Products
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

        <div className="flex-1 overflow-y-auto py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {loading ? (
            <div className="px-5 py-4 text-sm text-white/50">Loading products...</div>
          ) : products.length === 0 ? (
            <div className="px-5 py-8 text-sm text-white/40">No products configured yet.</div>
          ) : (
            products.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => handleProductClick(item)}
                className="w-full flex items-start gap-3 px-5 py-4 text-left hover:bg-white/[0.04] transition-colors group"
              >
                <div className="w-8 h-8 rounded-lg bg-[#252525] border border-white/10 flex items-center justify-center text-white/70 group-hover:border-[#857BFF]/30">
                  {item.emoji || '🧩'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-white truncate">{item.name || 'Claw Product'}</div>
                  <div className="text-xs text-white/40 truncate">{item.description || item.task || 'Product mapping'}</div>
                  <div className="text-[11px] text-white/30 mt-1 truncate">{item.outcome} · {item.domain}</div>
                </div>
              </button>
            ))
          )}
        </div>
      </aside>
    </>
  );
}