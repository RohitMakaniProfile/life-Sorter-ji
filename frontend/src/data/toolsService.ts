/**
 * Tools Service — Frontend
 *
 * Mirrors instant_tool_service.py — loads /public/data/tools_by_q1_q2_q3.json
 * once, caches in memory, returns tool recommendations with zero backend calls.
 *
 * JSON structure:
 *   {
 *     "lead-generation": {
 *       "Content & Social Media": {
 *         "Generate social media posts captions & hooks": [ tool, tool, ... ]
 *       }
 *     },
 *     "sales-retention": { ... },
 *     ...
 *   }
 */

export interface ToolItem {
  name: string;
  description: string;
  url?: string;
  category: string;
  rating?: number;
  composite_score?: number;
  best_use_case?: string;
  why_relevant?: string;
  review_summary?: string;
  source?: string;
}

export interface ToolsResult {
  tools: ToolItem[];
  message: string;
  match_type: 'exact' | 'domain_fallback' | 'outcome_fallback' | 'empty';
  count: number;
}

// ── Outcome label normalisation (mirrors Python _OUTCOME_LABEL_TO_ID) ──
const OUTCOME_LABEL_MAP: Record<string, string> = {
  'lead generation': 'lead-generation',
  'lead generation (marketing, seo & social)': 'lead-generation',
  'sales & retention': 'sales-retention',
  'sales & retention (calling, support & expansion)': 'sales-retention',
  'business strategy': 'business-strategy',
  'business strategy (intelligence, market & org)': 'business-strategy',
  'save time': 'save-time',
  'save time (automation workflow, extract pdf, bulk task)': 'save-time',
};

const VALID_IDS = new Set(['lead-generation', 'sales-retention', 'business-strategy', 'save-time']);

function resolveOutcomeId(outcome: string): string {
  if (!outcome) return '';
  const low = outcome.toLowerCase().trim();
  if (VALID_IDS.has(low)) return low;
  if (OUTCOME_LABEL_MAP[low]) return OUTCOME_LABEL_MAP[low];
  if (low.includes('lead gen')) return 'lead-generation';
  if (low.includes('sales') || low.includes('retention')) return 'sales-retention';
  if (low.includes('strategy') || low.includes('intelligence')) return 'business-strategy';
  if (low.includes('save time') || low.includes('automation')) return 'save-time';
  return low;
}

// ── Module-level cache ──
let _data: Record<string, any> | null = null;
let _loadPromise: Promise<Record<string, any>> | null = null;

async function loadData(): Promise<Record<string, any>> {
  if (_data) return _data;
  if (!_loadPromise) {
    _loadPromise = fetch('/data/tools_by_q1_q2_q3.json')
      .then((r) => r.json())
      .then((d) => {
        _data = d;
        _loadPromise = null;
        return d;
      });
  }
  return _loadPromise;
}

/** Pre-warm the cache. */
export function preloadToolsData(): void {
  loadData().catch(() => {/* non-blocking */});
}

function aggregateTopTools(tasksDict: Record<string, ToolItem[]>, limit: number): ToolItem[] {
  const seen = new Set<string>();
  const all: ToolItem[] = [];
  for (const tools of Object.values(tasksDict)) {
    for (const t of tools) {
      const key = t.name.toLowerCase().trim();
      if (!seen.has(key)) {
        seen.add(key);
        all.push(t);
      }
    }
  }
  all.sort((a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0));
  return all.slice(0, limit);
}

function buildResult(
  tools: ToolItem[],
  matchType: ToolsResult['match_type'],
): ToolsResult {
  return {
    tools,
    message: 'Here are the top-rated tools for your selection — curated from verified reviews and ratings.',
    match_type: matchType,
    count: tools.length,
  };
}

/**
 * Instant deterministic tool lookup by outcome × domain × task.
 * Mirrors get_tools_for_q1_q2_q3() from instant_tool_service.py.
 *
 * Lookup cascade:
 *   1. Exact outcome → domain → task
 *   2. Case-insensitive task match within domain
 *   3. Domain-level aggregate (all tasks in that domain)
 *   4. Fuzzy domain match within outcome
 *   5. Outcome-level aggregate
 *   6. Empty result
 */
export async function getToolsForQ1Q2Q3(
  outcome: string,
  domain: string,
  task: string,
  limit = 10,
): Promise<ToolsResult> {
  const data = await loadData();
  const outcomeId = resolveOutcomeId(outcome);

  const outcomeData: Record<string, Record<string, ToolItem[]>> = data[outcomeId] ?? {};
  const domainData: Record<string, ToolItem[]> = outcomeData[domain] ?? {};

  // Level 1: Exact match
  const exactTools = domainData[task];
  if (exactTools?.length) return buildResult(exactTools.slice(0, limit), 'exact');

  // Level 2: Case-insensitive task match
  const taskLower = task.toLowerCase().trim();
  for (const [storedTask, tools] of Object.entries(domainData)) {
    if (storedTask.toLowerCase().trim() === taskLower && tools.length) {
      return buildResult(tools.slice(0, limit), 'exact');
    }
  }

  // Level 3: Domain fallback (aggregate)
  if (Object.keys(domainData).length > 0) {
    const agg = aggregateTopTools(domainData, limit);
    if (agg.length) return buildResult(agg, 'domain_fallback');
  }

  // Level 4: Fuzzy domain match within outcome
  const domainLower = domain.toLowerCase().trim();
  for (const [storedDomain, storedTasks] of Object.entries(outcomeData)) {
    if (storedDomain.toLowerCase().trim() === domainLower) {
      const agg = aggregateTopTools(storedTasks, limit);
      if (agg.length) return buildResult(agg, 'domain_fallback');
    }
  }

  // Level 5: Outcome-level fallback
  if (Object.keys(outcomeData).length > 0) {
    const allTasks: Record<string, ToolItem[]> = {};
    for (const tasks of Object.values(outcomeData)) Object.assign(allTasks, tasks);
    const agg = aggregateTopTools(allTasks, limit);
    if (agg.length) return buildResult(agg, 'outcome_fallback');
  }

  return { tools: [], message: 'No tools found for this combination.', match_type: 'empty', count: 0 };
}
