export function getApiBaseRequired() {
  const raw = import.meta.env.VITE_API_URL;
  const base = typeof raw === 'string' ? raw.trim() : '';
  if (base) {
    return base.replace(/\/+$/, '');
  }
  // Local `npm run dev` works without a .env file; match page host so `localhost` vs `127.0.0.1` stays consistent.
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const h = window.location.hostname;
    if (h === 'localhost' || h === '127.0.0.1') {
      return `http://${h}:8000`;
    }
  }
  if (import.meta.env.DEV) {
    return 'http://127.0.0.1:8000';
  }
  throw new Error(
    'VITE_API_URL is required. Set frontend/.env for local and build env for deployed branches.',
  );
}

