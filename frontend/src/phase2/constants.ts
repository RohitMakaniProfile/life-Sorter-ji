/** Base path when Phase 2 app is mounted under the main SPA router. */
export const PHASE2_BASE = '/phase2';

export function phase2Path(segment: string): string {
  const s = segment.startsWith('/') ? segment.slice(1) : segment;
  return `${PHASE2_BASE}/${s}`;
}
