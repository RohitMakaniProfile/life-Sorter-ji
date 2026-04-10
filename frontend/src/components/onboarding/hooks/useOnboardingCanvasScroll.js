import { useRef, useCallback, useEffect } from 'react';

export function useOnboardingCanvasScroll() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault();
        el.scrollLeft += e.deltaY;
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const scrollToEnd = useCallback((options = {}) => {
    const el = canvasRef.current;
    if (!el) return;
    const retries = Number.isFinite(options.retries) ? Number(options.retries) : 8;
    const delayMs = Number.isFinite(options.delayMs) ? Number(options.delayMs) : 90;
    const behavior = options.behavior || 'smooth';

    let attempts = 0;
    const run = () => {
      const node = canvasRef.current;
      if (!node) return;
      const targetLeft = Math.max(0, node.scrollWidth - node.clientWidth);
      node.scrollTo({ left: targetLeft, behavior });
      if (attempts >= retries) return;
      attempts += 1;
      window.setTimeout(() => {
        requestAnimationFrame(run);
      }, delayMs);
    };

    requestAnimationFrame(run);
  }, []);

  return { canvasRef, scrollToEnd };
}
