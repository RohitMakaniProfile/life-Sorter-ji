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

  const scrollToEnd = useCallback(() => {
    const el = canvasRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ left: el.scrollWidth - el.clientWidth, behavior: 'smooth' });
    });
  }, []);

  return { canvasRef, scrollToEnd };
}
