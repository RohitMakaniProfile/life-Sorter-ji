/**
 * RCA Decision Tree — Frontend Service
 *
 * Mirrors rca_tree_service.py — loads /public/data/rca_decision_tree.json
 * once, caches in memory, serves Q1/Q2/Q3 with zero backend calls.
 *
 * Tree structure:
 *   "outcome|domain|task" → {
 *       q1: { question, options, insight, ... },
 *       branches: {
 *           "Option A": { question, options, sub_branches: { ... } },
 *           ...
 *       },
 *       task_filter: { filtered_items, ... }
 *   }
 */

export interface RcaQuestion {
  question: string;
  options: string[];
  insight?: string;
  section?: string;
  section_label?: string;
  type?: string;
}

export interface RcaHistoryEntry {
  question: string;
  answer: string;
}

// ── Module-level cache (persists across component re-renders) ──
let _tree: Record<string, any> | null = null;
let _loadPromise: Promise<Record<string, any>> | null = null;

async function loadTree(): Promise<Record<string, any>> {
  if (_tree) return _tree;
  // Deduplicate concurrent calls — only one fetch in flight
  if (!_loadPromise) {
    _loadPromise = fetch('/data/rca_decision_tree.json')
      .then((r) => r.json())
      .then((data) => {
        _tree = data;
        _loadPromise = null;
        return data;
      });
  }
  return _loadPromise;
}

/** Pre-warm the cache. Call once at app startup or before task selection. */
export function preloadRcaTree(): void {
  loadTree().catch(() => {/* non-blocking */});
}

function makeKey(outcome: string, domain: string, task: string): string {
  return `${outcome}|${domain}|${task}`;
}

/** Case-insensitive fuzzy match — mirrors Python _fuzzy_match_option() */
function fuzzyMatch(userAnswer: string, options: string[]): string | null {
  const lower = userAnswer.trim().toLowerCase();
  for (const opt of options) {
    if (opt.trim().toLowerCase() === lower) return opt;
  }
  for (const opt of options) {
    const optLower = opt.trim().toLowerCase();
    if (lower.includes(optLower) || optLower.includes(lower)) return opt;
  }
  return null;
}

/**
 * Get Q1 for the given outcome × domain × task.
 * Returns null if no tree entry exists (custom task → fall back to backend LLM).
 */
export async function getFirstQuestion(
  outcome: string,
  domain: string,
  task: string,
): Promise<RcaQuestion | null> {
  const tree = await loadTree();
  const entry = tree[makeKey(outcome, domain, task)];
  return entry?.q1 ?? null;
}

/**
 * Get next question based on Q&A history.
 *
 * rcaHistory = [
 *   { question: "...", answer: "Option A" },   ← Q1 answer
 *   { question: "...", answer: "Option C" },   ← Q2 answer
 * ]
 *
 * Returns null when:
 *   - No tree entry exists
 *   - User typed custom text ("Something else") — no branch match
 *   - All 3 questions answered (>= 3 answers)
 */
export async function getNextFromTree(
  outcome: string,
  domain: string,
  task: string,
  rcaHistory: RcaHistoryEntry[],
): Promise<RcaQuestion | null> {
  const tree = await loadTree();
  const entry = tree[makeKey(outcome, domain, task)];
  if (!entry) return null;

  const numAnswers = rcaHistory.length;

  if (numAnswers === 0) return entry.q1 ?? null;

  if (numAnswers === 1) {
    const branches: Record<string, any> = entry.branches ?? {};
    const matched = fuzzyMatch(rcaHistory[0].answer, Object.keys(branches));
    return matched ? branches[matched] : null;
  }

  if (numAnswers === 2) {
    const branches: Record<string, any> = entry.branches ?? {};
    const matchedQ1 = fuzzyMatch(rcaHistory[0].answer, Object.keys(branches));
    if (!matchedQ1) return null;

    const subBranches: Record<string, any> = branches[matchedQ1]?.sub_branches ?? {};
    const matchedQ2 = fuzzyMatch(rcaHistory[1].answer, Object.keys(subBranches));
    return matchedQ2 ? subBranches[matchedQ2] : null;
  }

  // >= 3 answers — tree exhausted, backend LLM takes over
  return null;
}

/**
 * Get pre-generated task alignment filter.
 * Returns null if no entry found.
 */
export async function getTaskFilter(
  outcome: string,
  domain: string,
  task: string,
): Promise<any | null> {
  const tree = await loadTree();
  const entry = tree[makeKey(outcome, domain, task)];
  return entry?.task_filter ?? null;
}

/**
 * Check if tree has an entry for this combination.
 * Useful to decide whether to use local data or call backend.
 */
export async function hasTreeEntry(
  outcome: string,
  domain: string,
  task: string,
): Promise<boolean> {
  const tree = await loadTree();
  return makeKey(outcome, domain, task) in tree;
}
