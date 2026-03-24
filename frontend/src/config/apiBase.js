export function getApiBaseRequired() {
  const raw = import.meta.env.VITE_API_URL;
  const base = typeof raw === 'string' ? raw.trim() : '';
  if (!base) {
    throw new Error(
      'VITE_API_URL is required. Set frontend/.env for local and build env for deployed branches.'
    );
  }
  return base.replace(/\/+$/, '');
}

