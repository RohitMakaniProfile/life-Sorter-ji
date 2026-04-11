import { useCallback } from 'react';

/**
 * Clears all onboarding-related localStorage keys except auth tokens.
 */
export function useClearOnboardingStorage() {
  const clearOnboardingClientStorage = useCallback(() => {
    try {
      const keep = new Set(['ikshan-auth-token', 'luna_user_id']);
      const toDelete = [];
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (!key || keep.has(key)) continue;
        if (key.startsWith('life-sorter') || key.startsWith('doable-claw') || key.startsWith('ikshan-taskstream')) {
          toDelete.push(key);
        }
      }
      toDelete.forEach((k) => localStorage.removeItem(k));
    } catch {
      // ignore storage failures
    }
  }, []);

  return { clearOnboardingClientStorage };
}

