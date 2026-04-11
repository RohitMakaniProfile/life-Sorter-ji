// Helper to convert DOMRect to plain object
export const toRectObj = (r) => ({ top: r.top, left: r.left, width: r.width, height: r.height });

// Separator used for task cache keys
export const TASK_KEY_SEP = '|||';

// Keys that can be patched to onboarding endpoint
export const ONBOARDING_PATCH_KEYS = ['outcome', 'domain', 'task', 'website_url', 'gbp_url', 'scale_answers'];

/**
 * Build a patch object with only allowed onboarding keys
 */
export function buildOnboardingPatch(fields) {
  const o = {};
  for (const k of ONBOARDING_PATCH_KEYS) {
    if (Object.prototype.hasOwnProperty.call(fields, k)) o[k] = fields[k];
  }
  return o;
}

